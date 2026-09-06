"""
The third authoring trigger: a work item being assigned to you.

The other two are events. A reviewer requesting changes and a tester reporting
a failure both arrive as webhooks, so the pipeline hears about them the moment
they happen. Assignment has no such event -- GitHub's `assigned` webhook fires
on the *repository*, and a Jira ticket landing on someone fires nothing Locus
receives at all -- so this is a sweep, which is why it looks like the calendar
agent rather than like `review_flow`.

**Off by default, and the reason is blast radius.** The board endpoint's
docstring already says it: authoring on assignment "has that shape with a far
worse blast radius -- a morning's tickets would open a dozen pull requests
together". That reasoning has not changed, and this does not contradict it. It
makes it a setting an account turns on deliberately, with the throughput cap as
the bound, rather than behaviour nobody chose.

Four rules hold it together.

**A work item is started once, ever.** The guard is an `AuthoringAttempt` row,
not a timestamp or an in-memory set: a sweep that ran, opened a pull request
and then restarted must not open a second one, and the attempt row is the only
record that survives a restart. This is the sweep equivalent of `PR comments
are idempotent` -- the mechanism differs, the requirement does not.

**Only genuinely untouched work.** An item with a pull request, a linked
branch, or any prior attempt is somebody's work in progress, and starting a
fresh branch under it is the duplicate-PR failure the rework fix exists to
prevent. Reworks stay with the event triggers, which know which branch to
continue.

**One item per user per sweep.** The cap bounds how many pull requests can be
*open*; it does nothing about how many arrive at once. A reviewer opening
GitHub to eight machine-authored pull requests filed in the same minute is how
this mode gets switched off, so the sweep takes the oldest untouched item and
leaves the rest for the next tick.

**A failure costs one user, never the loop.** Each user is swept inside its own
try, like every other loop here: an account with a dead GitHub token must not
stop the account after it in the iteration order.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app import models, schemas
from app.core.database import SessionLocal
from app.core.dependencies import get_integration_configs
from app.services.authoring import authoring, authoring_flow
from app.services.pipeline import task_board
from app.services.pipeline.agent_settings import resolve_settings

logger = logging.getLogger(__name__)

# How often the loop wakes. Assignment is not latency-sensitive in the way a
# review reply is -- nobody is waiting on the agent to start within seconds --
# and every tick costs a GitHub and a Jira call per enabled user.
TICK_MINUTES = 5


def _enabled_owner_ids(db: Session) -> list[int]:
    """
    Accounts that asked for this.

    Read off the defaults row rather than resolved per work item, because the
    trigger is account-level: there is no per-repo layer to consult before
    knowing whether to build a board at all. The per-item `authoring_mode` is
    still checked later, by `start_for_card`, so an account with the trigger on
    still writes nothing for an item somebody put in assisted mode.
    """
    rows = db.query(models.PRAgentDefaults).filter(
        models.PRAgentDefaults.auto_start_on_assignment == 1
    ).all()
    return [row.owner_id for row in rows]


def is_untouched(db: Session, *, owner_id: int, card: schemas.TaskCard) -> bool:
    """
    Whether nobody -- and no previous sweep -- has started this work item.

    Three separate signals, because each covers a case the others miss. A pull
    request means the work exists and any further attempt is a rework, which
    belongs to the event triggers that know which branch to continue. A linked
    branch means somebody opened one from the issue and is presumably writing
    in it, which is exactly the state the board renders as `branch_created`
    rather than `assigned`. And an attempt row means this sweep already ran --
    including the run that opened the pull request the board has not learned
    about yet, and including a run that failed, because a failure spends an
    attempt and retrying it here would be a loop that never ends.
    """
    if card.pull_requests:
        return False
    if card.linked_branches:
        return False

    attempts = db.query(models.AuthoringAttempt).filter(
        models.AuthoringAttempt.owner_id == owner_id,
        models.AuthoringAttempt.ticket_key == card.key,
    ).count()
    return attempts == 0


def _candidates(
    db: Session, *, owner_id: int, board: schemas.TaskBoard
) -> list[schemas.TaskCard]:
    """
    Untouched assigned items, oldest first.

    Oldest first because the sweep takes one per tick: a queue drained newest
    first leaves the oldest ticket permanently last, which is the opposite of
    what somebody watching a backlog wants. `recently_done` is excluded -- it
    is a record rather than a queue.
    """
    cards = [*board.needs_you, *board.in_flight]
    untouched = [c for c in cards if is_untouched(db, owner_id=owner_id, card=c)]
    # `updated_at` is None on a source that does not report one; those sort
    # last rather than first, since an unknown age is not evidence of being old.
    return sorted(
        untouched,
        key=lambda c: (c.updated_at is None, c.updated_at),
    )


async def sweep_user(db: Session, *, owner_id: int) -> str | None:
    """
    Start at most one untouched assigned work item for this account.

    Returns the key it started, or None. Everything the run itself needs --
    the mode, the bound, the driver, the cap -- is decided by
    `start_for_card`, which the board button also calls, so a swept item and a
    clicked one cannot behave differently.
    """
    integration_configs = get_integration_configs(db, owner_id)
    board = await task_board.build(
        db, owner_id=owner_id, integration_configs=integration_configs
    )

    for card in _candidates(db, owner_id=owner_id, board=board):
        repo = authoring_flow.repo_from_card(card)
        if not repo:
            # A Jira ticket with no branch and no pull request genuinely has no
            # repository. Skipped silently rather than reported: it is the
            # ordinary state of a ticket nobody has started, not a fault.
            continue

        registration = db.query(models.RepoWebhook).filter(
            models.RepoWebhook.repo == repo,
            models.RepoWebhook.owner_id == owner_id,
        ).first()
        settings = resolve_settings(
            db, owner_id, registration, ticket_key=card.key
        )
        if settings.authoring_mode != "autonomous" or settings.handed_back:
            # Checked here as well as inside `start_for_card` so the common
            # case -- an account with the trigger on and most items assisted --
            # costs nothing. `start_for_card` remains the authority.
            continue

        try:
            result, attempt, _trigger = await authoring_flow.start_for_card(
                db,
                owner_id=owner_id,
                card=card,
                settings=settings,
                integration_configs=integration_configs,
                # Deliberately no doc hook. `report_sync.ensure_for_ticket`
                # creates a Google Doc, and a sweep that called it would make
                # one per assigned item -- the exact mistake that function
                # avoids by never running from the board listing. The document
                # is created when somebody opens the task.
                doc_url_hook=None,
            )
        except authoring_flow.StartRefused as refused:
            # Data, not an exception to propagate: a capped or handed-back item
            # is a reason to move on, and the next tick will find it again if
            # the reason clears.
            logger.info(
                "Assignment sweep skipped %s: %s", card.key, refused.detail
            )
            continue

        logger.info(
            "Assignment sweep started %s (attempt %s): opened=%s pr=%s",
            card.key, attempt, result.opened, result.pr_number,
        )
        # One per user per tick. The cap bounds how many can be open; this
        # bounds how many arrive at once, which is the number a reviewer sees.
        return card.key

    return None


async def sweep_once() -> int:
    """
    One pass over every account with the assignment trigger on.

    Returns how many work items were started. Its own session, like the other
    loops: this runs on a timer with no request behind it.
    """
    db = SessionLocal()
    started = 0
    try:
        owner_ids = _enabled_owner_ids(db)
        if not owner_ids:
            return 0

        if authoring.get_driver().name == "none":
            # Nothing to do, and worth saying once rather than per user: a
            # deployment with the trigger enabled and no driver configured is a
            # misconfiguration that otherwise looks like the sweep never
            # finding anything.
            logger.debug(
                "Assignment sweep skipped: no authoring driver is configured"
            )
            return 0

        for owner_id in owner_ids:
            try:
                if await sweep_user(db, owner_id=owner_id):
                    started += 1
            except Exception:
                # One account's dead token must not cost the accounts after it.
                logger.exception(
                    "Assignment sweep failed for user %s", owner_id
                )
    finally:
        db.close()

    return started
