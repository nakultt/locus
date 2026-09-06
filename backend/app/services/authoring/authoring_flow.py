"""
The automatic retries, and the handoff when the bound runs out.

Two triggers reach this: a reviewer requesting changes, and the testing team
rejecting a merged change. Both are the pipeline saying "this is not done",
which is exactly what an authoring attempt answers -- and both funnel through
one function so the two cannot drift into behaving differently.

The QA retry deliberately opens a *new* pull request. That is what
`work_item.resolve_key` and `sibling_reviews` were built for: the new PR
inherits the rejection history for free, so the fix opens carrying the reason
the work came back.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app import models, schemas
from app.services.authoring import authoring
from app.services.integrations import github_pr
from app.services.pipeline import comms_log, context_brief, work_item

logger = logging.getLogger(__name__)


async def maybe_retry(
    db: Session,
    *,
    owner_id: int,
    repo: str,
    pr_number: int,
    ticket_key: str | None,
    settings,
    integration_configs: dict,
    trigger: str,
    slack_channel: str | None = None,
    rejection: str | None = None,
) -> authoring.AuthoringResult | None:
    """
    Take another swing at this work item, or hand it back, or hold silently.

    Returns the result when the driver ran, None when it did not. Every path
    swallows its own failure: a retry that could not start must not take the
    review notification or the QA reopen down with it, the same rule the loops
    already follow.
    """
    if not ticket_key:
        # A work item is never guessed. Attaching a key we inferred would put
        # one team's history in front of another team's pull request.
        return None

    driver = authoring.get_driver()
    if driver.name == "none":
        return None

    retry, reason = authoring.should_retry(
        db,
        owner_id=owner_id,
        ticket_key=ticket_key,
        settings=settings,
        repo=repo,
        # A changes-requested rework pushes to the pull request the reviewer
        # is already reading, so it opens nothing and the throughput cap has
        # nothing to protect. A QA rejection does open one, and is capped.
        continuing=trigger == "changes_requested",
    )

    if not retry:
        await _refuse(
            db,
            owner_id=owner_id,
            repo=repo,
            pr_number=pr_number,
            ticket_key=ticket_key,
            settings=settings,
            integration_configs=integration_configs,
            reason=reason,
            slack_channel=slack_channel,
        )
        return None

    attempt = authoring.next_attempt_number(
        db, owner_id=owner_id, ticket_key=ticket_key
    )
    review = db.query(models.PRReview).filter(
        models.PRReview.owner_id == owner_id,
        models.PRReview.repo == repo,
        models.PRReview.pr_number == pr_number,
    ).first()

    # A QA rejection opens a new pull request on a new branch; a rework
    # continues the branch the reviewer has already read.
    #
    # This used to pass None for both, which meant the branch name picked up
    # the attempt number and every rework opened a *second* pull request. The
    # reviewer's changes-requested review then sat on a PR that never received
    # the fix, `PRReview.round_number` stopped tracking the round trip, and the
    # abandoned PR -- still unmerged, still `changes_requested` -- pinned the
    # task board's stage forever, because `_derive_stage` reads the furthest
    # state among *unmerged* pull requests.
    continue_branch = (
        await head_branch(repo, pr_number, integration_configs)
        if trigger == "changes_requested"
        else None
    )

    request = authoring.AuthoringRequest(
        ticket_key=ticket_key,
        title=bare_title(
            (review.pr_title if review else None) or ticket_key, ticket_key
        ),
        repo=repo,
        existing_branch=continue_branch,
        context=_context(db, owner_id, repo, pr_number, ticket_key),
        asks=authoring.gather_asks(
            db, owner_id=owner_id, ticket_key=ticket_key,
            repo=repo, pr_number=pr_number,
        ),
        rejection=rejection,
        attempt=attempt,
        trigger=trigger,
        settings={
            "source_path": settings.source_path,
            "prepare_command": settings.prepare_command,
            "test_command": settings.test_command,
            "attempts_remaining": max(
                0, settings.autonomous_max_rounds + 1 - attempt
            ),
        },
    ).scoped()

    # Same reason as the board path: a rework takes minutes, and the card has
    # to be able to say so.
    started = authoring.begin_attempt(db, owner_id=owner_id, request=request)

    try:
        result = await driver.author(request, integration_configs)
    except Exception as exc:
        logger.warning("Authoring retry failed for %s: %s", ticket_key, exc)
        result = authoring.AuthoringResult(
            opened=False, error=f"The driver raised: {exc}", driver=driver.name
        )

    authoring.record_attempt(
        db, owner_id=owner_id, request=request, result=result, started=started
    )

    if result.hand_back_reason:
        await _hand_back(
            db,
            owner_id=owner_id,
            repo=repo,
            pr_number=pr_number,
            ticket_key=ticket_key,
            reason=result.hand_back_reason,
            integration_configs=integration_configs,
            slack_channel=slack_channel,
            pr_url=result.pr_url,
        )
        return result

    if not result.opened:
        # The attempt is spent either way. Check whether that was the last one
        # and hand it back now rather than waiting for the next event, which
        # may never come.
        spent, spent_reason = authoring.should_retry(
            db, owner_id=owner_id, ticket_key=ticket_key,
            settings=settings, repo=repo,
        )
        if not spent and "already open" not in spent_reason:
            await _hand_back(
                db,
                owner_id=owner_id,
                repo=repo,
                pr_number=pr_number,
                ticket_key=ticket_key,
                reason=f"{spent_reason}. Last error: {result.error}",
                integration_configs=integration_configs,
                slack_channel=slack_channel,
            )

    return result


async def _refuse(
    db: Session,
    *,
    owner_id: int,
    repo: str,
    pr_number: int,
    ticket_key: str,
    settings,
    integration_configs: dict,
    reason: str,
    slack_channel: str | None,
) -> None:
    """
    Handle a refusal to retry.

    The throughput cap holds **silently**: a held retry that reports every time
    trains people to ignore the channel, the same rule `automerge.sweep_once`
    follows. A spent bound is announced once, because the work is now waiting
    on a person who does not otherwise know that.
    """
    if "already open" in reason:
        return
    if settings.authoring_mode != "autonomous" or getattr(settings, "handed_back", False):
        # Not a refusal so much as the mode simply being off. Nothing to say.
        return

    await _hand_back(
        db,
        owner_id=owner_id,
        repo=repo,
        pr_number=pr_number,
        ticket_key=ticket_key,
        reason=reason,
        integration_configs=integration_configs,
        slack_channel=slack_channel,
    )


async def _hand_back(
    db: Session,
    *,
    owner_id: int,
    repo: str,
    pr_number: int,
    ticket_key: str,
    reason: str,
    integration_configs: dict,
    slack_channel: str | None,
    pr_url: str | None = None,
) -> None:
    """
    End autonomous mode for this work item and say so.

    **The database write commits before the announcement.** The reverse --
    announcing a handoff that did not persist -- re-triggers the driver on the
    next event, so the team reads "it is yours now" while the agent keeps
    working. A failed announcement leaves the work correctly stopped; a failed
    write leaves it running with everybody told otherwise.
    """
    existing = db.query(models.WorkItemSettings).filter(
        models.WorkItemSettings.owner_id == owner_id,
        models.WorkItemSettings.ticket_key == ticket_key,
    ).first()
    if existing is not None and existing.handed_back_at is not None:
        # Already handed back. Announcing again is the repeat that gets a bot
        # muted, and a muted bot takes the review pings with it.
        return

    authoring.hand_back(db, owner_id=owner_id, ticket_key=ticket_key, reason=reason)

    attempts = len(authoring.attempts_for(db, owner_id, ticket_key))
    message = authoring.handoff_message(
        ticket_key, attempts=attempts, reason=reason, pr_url=pr_url
    )

    sent = False
    if slack_channel and "slack" in integration_configs:
        try:
            from app.services.pipeline.review_flow import post_review_notification

            sent = await post_review_notification(
                integration_configs["slack"], slack_channel, message
            )
        except Exception as exc:
            logger.warning("Could not announce the handoff for %s: %s", ticket_key, exc)

    comms_log.record(
        db, owner_id=owner_id, repo=repo, pr_number=pr_number,
        ticket_key=ticket_key,
        loop="review", direction="sent", channel="slack",
        target=slack_channel or "(no channel configured)",
        body=message,
        outcome="handed_back",
        succeeded=sent,
    )


def bare_title(title: str, ticket_key: str) -> str:
    """
    The pull request title without the ticket key the driver re-adds.

    Public because the board's "write it now" button reworks an open pull
    request too, and a manual rework that re-prefixed the title would produce
    the same "KEY: KEY: Title" this exists to prevent.

    The driver builds its title as `f"{ticket_key}: {title}"`, and the stored
    `PRReview.pr_title` is a previous run's output, which already carries that
    prefix. Passing it back unchanged produced "KEY: KEY: Title" on the second
    attempt and would have added a third on the next one.
    """
    prefix = f"{ticket_key}: "
    while title.startswith(prefix):
        title = title[len(prefix):]
    return title or ticket_key


async def head_branch(
    repo: str, pr_number: int, integration_configs: dict
) -> str | None:
    """
    The branch this pull request is on, so a rework can push to it.

    Shared with the board's manual run for one reason: the two triggers must
    not be able to disagree about where a rework lands. Reconstructing the
    branch name in one of them is how the manual button came to open a second
    pull request while the reviewer's changes-requested review sat on the
    first.

    Read from GitHub rather than reconstructed from the ticket key and attempt
    number: the branch may have been created by a human, by the Development
    panel, or by an earlier attempt, and only GitHub knows which. A failure
    returns None, which falls back to the previous behaviour of cutting a new
    branch -- worse, but not a lost attempt.
    """
    config = integration_configs.get("github") or {}
    token = config.get("api_key") or config.get("token")
    if not token:
        return None
    try:
        details = await github_pr.get_pull_request(token, repo, pr_number)
    except Exception as exc:
        logger.warning("Could not read the head branch for %s#%s: %s", repo, pr_number, exc)
        return None
    if not isinstance(details, dict):
        return None
    # GitHub returns an explicit null for optional objects, so guard the value
    # rather than the key's presence.
    head = details.get("head") or {}
    return (head.get("ref") or None) if isinstance(head, dict) else None


def _context(
    db: Session, owner_id: int, repo: str, pr_number: int, ticket_key: str
) -> str:
    """The work item's accumulated context, or nothing if it cannot be built."""
    try:
        return context_brief.build(
            db, owner_id=owner_id, repo=repo, pr_number=pr_number,
            ticket_key=ticket_key,
        )
    except Exception as exc:
        logger.debug("Context brief unavailable for %s: %s", ticket_key, exc)
        return ""


async def human_pushed_since_last_attempt(
    db: Session,
    *,
    owner_id: int,
    repo: str,
    pr_number: int,
    ticket_key: str,
    integration_configs: dict,
) -> bool:
    """
    Whether somebody other than the agent has pushed to this pull request.

    Read from GitHub rather than from a local checkout, because the branch a
    reviewer is looking at is the remote one. A failure returns False: refusing
    to retry because a lookup failed would make the mode stop working whenever
    GitHub is slow, which is indistinguishable from the bound being spent.
    """
    token = (integration_configs.get("github") or {}).get("api_key") or (
        integration_configs.get("github") or {}
    ).get("token")
    if not token:
        return False

    last = db.query(models.AuthoringAttempt).filter(
        models.AuthoringAttempt.owner_id == owner_id,
        models.AuthoringAttempt.ticket_key == ticket_key,
        models.AuthoringAttempt.opened == 1,
    ).order_by(models.AuthoringAttempt.created_at.desc()).first()
    if last is None:
        return False

    try:
        authors = await github_pr.get_pr_commit_authors(token, repo, pr_number)
    except Exception:
        return False

    from app.services.authoring.opencode_driver import agent_email

    # The resolved identity, not the module constant: an account that set its
    # own commit address would otherwise have every one of its agent's own
    # commits read as a human's, handing back work the agent itself wrote.
    address = agent_email().lower()
    return any(email.lower() != address for email in authors)


def key_for(db: Session, *, owner_id: int, repo: str, pr_number: int) -> str | None:
    """The work item behind a pull request, never guessed into existence."""
    return work_item.resolve_key(
        db, owner_id=owner_id, repo=repo, pr_number=pr_number
    )


# --- shared with the board endpoint ---------------------------------------
#
# These moved out of `routers/tasks.py` when the assignment trigger was added.
# Locus already holds the rule that **both triggers reach the driver the same
# way, including the board's button** -- it exists because the webhook path was
# fixed to continue an open pull request and the board path was not, so the
# same click meant different things depending on which arm ran. A third
# trigger copying the orchestration would reintroduce exactly that, so the
# orchestration lives here and every arm calls `start_for_card`.

def pr_to_continue(card: schemas.TaskCard) -> schemas.TaskPullRequest | None:
    """
    The open pull request a manual run should push to, if there is one.

    In flight means open, not merely un-merged -- the same rule
    `task_board._derive_stage` reads the board by. A merged pull request is
    finished and a closed one was abandoned or superseded; pushing to either
    puts commits somewhere nobody is looking. Everything else is a pull request
    a reviewer either has read or is being asked to read, and the branch it is
    on is where the next attempt belongs.

    The latest is taken when several are open, which matches `_derive_stage`
    consulting the furthest state among them: two open pull requests on one
    work item is already unusual, and the newest is the one carrying the
    current attempt.
    """
    finished = {schemas.ReviewState.merged, schemas.ReviewState.closed}
    open_prs = [
        pr
        for pr in card.pull_requests
        if pr.review_state is not None and pr.review_state not in finished
    ]
    return open_prs[-1] if open_prs else None


def repo_from_card(card: schemas.TaskCard) -> str | None:
    """
    The repo a work item belongs to when it has no pull request yet.

    A linked branch names one, and a GitHub issue key is `owner/repo#N`. A Jira
    ticket with neither genuinely has no repo, and saying so beats guessing --
    pointing the agent at the wrong codebase produces a confident, entirely
    wrong pull request.
    """
    for branch in card.linked_branches:
        if branch.repo:
            return branch.repo
    if "#" in card.key:
        candidate = card.key.rsplit("#", 1)[0]
        if "/" in candidate:
            return candidate
    return None


def context_for(
    db: Session, owner_id: int, task_key: str, card: schemas.TaskCard
) -> str:
    """
    The accumulated context for this work item, rendered on demand.

    Keyed by work item rather than pull request, so a retry after a QA
    rejection opens carrying the first attempt's discussion and the rejection
    that caused it to exist. A task with no pull request yet has no brief to
    build from and gets the ticket alone, which the driver's prompt states
    outright rather than presenting an empty section as context.
    """
    if not card.pull_requests:
        return ""
    return context_brief.build(
        db,
        owner_id=owner_id,
        repo=card.pull_requests[-1].repo,
        pr_number=card.pull_requests[-1].pr_number,
        ticket_key=task_key,
    )


def rejection_for(db: Session, owner_id: int, task_key: str) -> str | None:
    """
    The tester's own words, when the last QA verdict on this item was a
    rejection.

    Read from `communication_events`, which is where the QA loop records what
    a tester actually said alongside the verdict the classifier reached -- the
    thread row carries the correlation, not the reply. In the tester's words
    rather than a summary: "it does not work" and the specific thing they tried
    are very different amounts of help to whoever writes the fix.

    Scoped to the whole work item, not one pull request, because the rejection
    that matters is usually against the attempt before this one -- and to this
    owner, with no fallback past them.

    An owner-less retry was here, from the same workaround as the ones in
    `report_sync.find_report` and `task_board._registration_for`. This one is
    the worst of the set: the text it returns becomes the *primary goal* of the
    authoring prompt, so another account's tester saying "this does not work"
    would be handed to this account's coding agent as the thing to fix -- and,
    on any hosted driver, sent to a third party. No rejection found is the
    correct answer; the run then goes out as `initial`, which is what a work
    item with no rejection is.
    """
    event = db.query(models.CommunicationEvent).filter(
        models.CommunicationEvent.owner_id == owner_id,
        models.CommunicationEvent.ticket_key == task_key,
        models.CommunicationEvent.loop == "qa",
        models.CommunicationEvent.direction == "received",
        models.CommunicationEvent.outcome == "broken",
    ).order_by(models.CommunicationEvent.created_at.desc()).first()

    return (event.body or None) if event else None


class StartRefused(Exception):
    """
    Why a run was not started, as data rather than an HTTP error.

    The board endpoint raises 409/429/503 and the assignment sweep logs and
    moves on, so the shared path cannot raise `HTTPException` -- a service that
    did would make a background loop depend on a web framework to decide
    whether to skip a ticket. `code` is what the router maps to a status.
    """

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


async def start_for_card(
    db: Session,
    *,
    owner_id: int,
    card: schemas.TaskCard,
    settings,
    integration_configs: dict,
    doc_url_hook=None,
) -> tuple[authoring.AuthoringResult, int, str]:
    """
    Run the driver once against a work item, from a board card.

    The single path from "this work item should be written" to the driver. The
    board button and the assignment sweep both call it. Locus already holds the
    rule that **both triggers reach the driver the same way, including the
    board's button** -- and it exists because the webhook path was fixed to
    continue an open pull request while the board path was not, so the same
    click meant different things depending on which arm ran. A third caller
    copying this orchestration would reintroduce that failure one arm at a time.

    Raises `StartRefused` for every condition the caller must report rather
    than proceed through: no repo, handed back, mode off, no driver, cap
    reached. The caller decides whether that is a 409 or a log line.

    Args:
        doc_url_hook: Optional async callable taking the resolved repo and
            returning a report URL for the pull request body. Passed in rather
            than called here because creating the document is a *write*, and a
            sweep must not make one per assigned ticket -- the same reason
            `report_sync.ensure_for_ticket` is never called from the board
            listing.

    Returns:
        (result, attempt number, trigger). The trigger is returned because it
        is derived here and the caller reports it.
    """
    repo = card.pull_requests[0].repo if card.pull_requests else repo_from_card(card)
    if not repo:
        raise StartRefused(
            "no_repo",
            "This work item is not attached to a repository, so there is "
            "nothing to write against. Link it to a repo or open a branch "
            "from the issue first.",
        )

    if settings.handed_back:
        raise StartRefused(
            "handed_back",
            "This work item was handed back: "
            f"{settings.handed_back_reason or 'no reason recorded'}. "
            "Switch it back to autonomous on the card to try again.",
        )
    if settings.authoring_mode != "autonomous":
        raise StartRefused(
            "mode_off",
            "Autonomous mode is off for this work item "
            f"(set by: {settings.sources.get('authoring_mode', 'unset')})",
        )

    driver = authoring.get_driver()
    if driver.name == "none":
        raise StartRefused(
            "no_driver",
            "No authoring driver configured. Choose one under Settings > "
            "Automation > Agent runtime, or set LOCUS_AUTHORING_DRIVER.",
        )

    # A rework continues the pull request the reviewer already read; anything
    # else cuts a fresh branch. `head_branch` returning None falls back to the
    # previous behaviour, which is worse but is not a lost attempt.
    continuing = pr_to_continue(card)
    continue_branch = (
        await head_branch(continuing.repo, continuing.pr_number, integration_configs)
        if continuing
        else None
    )

    # Resolved before the cap is consulted, because it decides whether the cap
    # applies at all: the limit is on reviewer attention, and a rework spends
    # none -- the reviewer is already reading that pull request.
    if not continue_branch and authoring.throughput_exceeded(
        db, owner_id=owner_id, repo=repo
    ):
        raise StartRefused(
            "cap",
            f"{authoring.max_open_autonomous_prs()} agent-authored pull "
            f"requests are already open on {repo}. Reviewer attention is "
            "what this mode spends; land or close one first.",
        )

    attempt = authoring.next_attempt_number(
        db, owner_id=owner_id, ticket_key=card.key
    )

    doc_url = await doc_url_hook(repo) if doc_url_hook else None

    continuing_repo = continuing.repo if continuing else repo
    continuing_pr_num = continuing.pr_number if continuing else None

    asks = authoring.gather_asks(
        db, owner_id=owner_id, ticket_key=card.key,
        repo=continuing_repo, pr_number=continuing_pr_num,
    )
    rejection = rejection_for(db, owner_id, card.key)

    continuing_state = (
        getattr(continuing.review_state, "value", continuing.review_state)
        if continuing
        else None
    )
    is_changes_requested = bool(
        continue_branch
        and continuing
        and (
            continuing_state in (
                "changes_requested",
                "awaiting_review",
                schemas.ReviewState.changes_requested,
                schemas.ReviewState.awaiting_review,
            )
            or bool(asks)
        )
    )
    trigger = (
        "changes_requested"
        if is_changes_requested
        else ("qa_rejected" if rejection else "initial")
    )

    request = authoring.AuthoringRequest(
        # The stored title is a previous run's output and already carries the
        # key the driver re-adds, so it is stripped before going back out.
        title=(
            bare_title(continuing.title or card.title, card.key)
            if continuing and continue_branch
            else card.title
        ),
        ticket_key=card.key,
        description=card.description,
        repo=repo,
        existing_branch=(
            continue_branch
            or (card.linked_branches[0].name if card.linked_branches else None)
        ),
        context=context_for(db, owner_id, card.key, card),
        asks=asks,
        rejection=rejection,
        attempt=attempt,
        # Recorded on the attempt and stated in the pull request body, so the
        # trigger has to describe what the run is answering rather than which
        # arm started it.
        trigger=trigger,
        settings={
            "source_path": settings.source_path,
            "prepare_command": settings.prepare_command,
            "test_command": settings.test_command,
            # What the test gate consults on a failure: with attempts left it
            # opens nothing and retries, on the last one it opens the pull
            # request anyway with the failure stated.
            "attempts_remaining": max(
                0, settings.autonomous_max_rounds + 1 - attempt
            ),
            "doc_url": doc_url,
        },
    ).scoped()

    # Marked as running before the driver is invoked: the call below takes
    # minutes, and until it returns the board would otherwise show this work
    # item as merely `assigned` -- indistinguishable from one nobody started.
    started = authoring.begin_attempt(db, owner_id=owner_id, request=request)

    try:
        result = await driver.author(request, integration_configs)
    except Exception as exc:
        # The board endpoint let this propagate as a 500. A sweep cannot: one
        # ticket whose driver raised must not stop the rest, and the attempt is
        # spent either way, so it is recorded as the failure it is.
        logger.warning("Authoring run failed for %s: %s", card.key, exc)
        result = authoring.AuthoringResult(
            opened=False, error=f"The driver raised: {exc}", driver=driver.name
        )

    authoring.record_attempt(
        db, owner_id=owner_id, request=request, result=result, started=started
    )

    if result.hand_back_reason:
        # Persisted before anything is announced. Announcing a handoff that did
        # not persist re-triggers the driver on the next event.
        authoring.hand_back(
            db, owner_id=owner_id, ticket_key=card.key,
            reason=result.hand_back_reason,
        )

    return result, attempt, trigger
