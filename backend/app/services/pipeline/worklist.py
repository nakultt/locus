"""
What is waiting on the user, across everything they have open.

The dashboard is a record: it answers "what happened on PR #42". The question
a developer actually has is the inverse -- "across everything open, what is
waiting on me" -- and answering it meant expanding six pull requests to find
the two that needed action.

Two decisions shape this module.

**Grouped by task, not by pull request.** The unit a developer thinks in is
the work item. One ticket routinely spans several PRs: the feature, the fix
after QA rejected it, the follow-up. Keyed by PR, a task that has been
round-tripping for two weeks reads as three unrelated young items, which loses
exactly the signal worth surfacing.

**Sorted by who is blocked, then by staleness.** Not by severity. A task on
round five for three days is a conversation that is not converging, and that
is what nobody sees today. Severity ranks findings; staleness ranks
conversations, and this is a list of conversations.

The risk here is precision rather than complexity: a list that shows things
which do not actually need you is ignored within a week, and once ignored it
is very hard to win back. The sources below are deliberately few.
"""

import json
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app import models, schemas

logger = logging.getLogger(__name__)

# How many verbatim quotes to carry per item. The asker's own sentence is what
# makes an item actionable; a second and third are usually the same request
# restated.
MAX_QUOTES = 3

# How long a testing thread may go unanswered before it is something waiting on
# you. Long enough that an ordinary weekend or a busy day does not raise it --
# QA replying next morning is normal -- and short enough that a forgotten thread
# surfaces while the change is still fresh.
QA_SILENT_DAYS = 3


def _age_hours(stamp: datetime | None) -> float:
    if stamp is None:
        return 0.0
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    return max(0.0, (datetime.now(UTC) - stamp).total_seconds() / 3600.0)


def _task_key(review: models.PRReview) -> str:
    """
    The work item a pull request belongs to.

    Falls back to the PR itself when no ticket is known -- a PR without a
    ticket is ordinary, and dropping it from the worklist would hide real work
    rather than tidy the list.
    """
    keys = [
        line.strip()
        for line in (review.ticket_keys or "").splitlines()
        if line.strip()
    ]
    return keys[0] if keys else f"{review.repo}#{review.pr_number}"


def _thread_key(db: Session, thread: models.QAThread) -> str:
    """
    The work item a QA thread belongs to.

    A thread stores no ticket key of its own, so this reads the one the
    analysis recorded on the review row. Grouping matters here: without it an
    unanswered thread would open a second card for a ticket that already has
    one, and the board would show one piece of work as two.
    """
    review = (
        db.query(models.PRReview)
        .filter(
            models.PRReview.repo == thread.repo,
            models.PRReview.pr_number == thread.pr_number,
            models.PRReview.owner_id == thread.owner_id,
        )
        .first()
    )

    if review is not None:
        return _task_key(review)

    if thread.ticket_keys_json:
        try:
            keys = json.loads(thread.ticket_keys_json)
            if keys and keys[0]:
                return keys[0]
        except Exception:
            pass

    return f"{thread.repo}#{thread.pr_number}"



# Cached per build, because the board renders every assigned work item and this
# resolves settings and counts attempts for each. Keyed by work item, which is
# what the settings themselves are keyed by.
_HandlingCache = dict



def _as_utc(stamp):
    """
    A timestamp that can be compared with another, whatever the store returned.

    Both sides go through this, not just one. SQLite stores UTC without
    labelling it, so a row can come back naive while the one beside it is
    aware -- and comparing those raises `TypeError` rather than sorting wrong.
    That matters more here than usual: this comparison is inside
    `worklist.build`, so an exception takes down the whole board rather than
    misplacing one item. Read as UTC because that is what every writer stores,
    which is the same assumption `datetimes.parseInstant` makes on the client.
    """
    if stamp is None:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=UTC)


def _merged_at(review):
    """
    When a pull request merged, as best the review row can say.

    `updated_at` rather than a dedicated column, because there is not one --
    the row is written on every review event and the merge is the last of them.
    Good enough for "did the fix land after the tester complained", which is a
    question about ordering across hours, not seconds.
    """
    return _as_utc(
        getattr(review, "updated_at", None) or getattr(review, "created_at", None)
    )


def _agent_handles(
    db: Session,
    *,
    owner_id: int,
    repo: str,
    ticket_key: str | None,
    trigger: str,
    cache: dict,
) -> bool:
    """
    Whether the authoring agent will answer this without a person.

    `blocked_on_you` used to be unconditionally true for a reviewer's
    changes-requested and for a QA rejection. In autonomous mode with the
    matching auto-start trigger on, neither is blocked on anyone: the agent
    picks it up within seconds of the webhook, and the card said "Needs you"
    while the agent was already writing the fix.

    That is the failure this module's own docstring names -- "a list that shows
    things which do not actually need you is ignored within a week, and once
    ignored it is very hard to win back". A queue that cries wolf on the one
    kind of item the pipeline exists to handle automatically is the fastest way
    to get there.

    Every reason the agent might *not* pick it up still leaves the item blocked
    on you, and they are the reasons that matter: the mode is off, the work item
    was handed back, the attempts are spent, a human has committed on the
    branch, or no driver is configured. `should_retry` already decides all of
    them, and is reused rather than restated so the queue and the run cannot
    disagree about whether anyone needs to act.
    """
    if not ticket_key:
        # A work item that cannot be identified cannot be handed to the agent:
        # `maybe_retry` refuses a missing key rather than guessing one.
        return False

    key = (repo, ticket_key, trigger)
    if key in cache:
        return cache[key]

    cache[key] = handled = _resolve_agent_handles(
        db, owner_id=owner_id, repo=repo, ticket_key=ticket_key, trigger=trigger
    )
    return handled


def _resolve_agent_handles(
    db: Session, *, owner_id: int, repo: str, ticket_key: str, trigger: str
) -> bool:
    """The uncached decision. Swallows its own failure as "you deal with it"."""
    from app.services.authoring import authoring
    from app.services.pipeline.agent_settings import resolve_settings

    try:
        registration = db.query(models.RepoWebhook).filter(
            models.RepoWebhook.repo == repo,
            models.RepoWebhook.owner_id == owner_id,
        ).first()
        settings = resolve_settings(db, owner_id, registration, ticket_key=ticket_key)

        # The mode says the agent may write this; the trigger says nobody has
        # to press the button. Both, or a person does.
        if settings.authoring_mode != "autonomous":
            return False
        if not getattr(settings, f"auto_start_on_{trigger}", False):
            return False
        if authoring.get_driver().name == "none":
            return False

        # A rework continues the pull request the reviewer is already reading,
        # so it opens nothing and the throughput cap does not apply -- the same
        # distinction `authoring_flow.maybe_retry` draws.
        retry, _reason = authoring.should_retry(
            db,
            owner_id=owner_id,
            ticket_key=ticket_key,
            settings=settings,
            repo=repo,
            continuing=trigger == "review",
        )
        return retry
    except Exception:
        # If we cannot tell, say it needs you. The failure that matters is the
        # other one: a queue that hides work nobody is doing.
        logger.debug(
            "Could not decide whether the agent handles %s; treating as yours",
            ticket_key,
        )
        return False


def build(db: Session, *, owner_id: int) -> schemas.Worklist:
    """
    Assemble the worklist for one user.

    Ordering is decided here rather than in the client: the API and the UI must
    not be able to disagree about what is most urgent.
    """
    # Pull requests that are already merged or sent to QA across the system.
    # A PR sent to QA has already merged; treating it as "approved, not merged"
    # keeps the card stuck in needs_you on the review loop.
    merged_idents: set[tuple[str, int]] = {
        (t.repo, t.pr_number)
        for t in db.query(models.QAThread.repo, models.QAThread.pr_number).all()
        if t.repo and t.pr_number
    } | {
        (r.repo, r.pr_number)
        for r in db.query(models.PRReview.repo, models.PRReview.pr_number)
        .filter(models.PRReview.state == schemas.ReviewState.merged.value)
        .all()
        if r.repo and r.pr_number
    } | {
        (j.repo, j.pr_number)
        for j in db.query(models.PRJob.repo, models.PRJob.pr_number)
        .filter(
            models.PRJob.action == "merged",
            models.PRJob.status == schemas.PRJobStatus.completed.value,
        )
        .all()
        if j.repo and j.pr_number
    } | {
        (e.repo, e.pr_number)
        for e in db.query(models.CommunicationEvent.repo, models.CommunicationEvent.pr_number)
        .filter(
            models.CommunicationEvent.loop == "qa",
            models.CommunicationEvent.direction == "sent",
            models.CommunicationEvent.outcome == "ready_to_test",
            models.CommunicationEvent.succeeded == 1,
        )
        .all()
        if e.repo and e.pr_number
    }

    # Merged and closed are both finished: nobody is waiting on either. A
    # pull request closed without merging was abandoned, and listing it as
    # blocked on you forever is exactly the noise that trains people to stop
    # reading the list.
    reviews = (
        db.query(models.PRReview)
        .filter(
            models.PRReview.owner_id == owner_id,
            models.PRReview.state.notin_([
                schemas.ReviewState.merged.value,
                schemas.ReviewState.closed.value,
            ]),
        )
        .all()
    )

    # Reconcile any reviews known to be merged
    for r in reviews:
        if (
            (r.repo, r.pr_number) in merged_idents
            and r.state != schemas.ReviewState.changes_requested.value
        ):
            r.state = schemas.ReviewState.merged.value
            r.pending_asks = None
            try:
                db.commit()
            except Exception:
                db.rollback()

    reviews = [r for r in reviews if r.state != schemas.ReviewState.merged.value]

    # Merged PRs still matter when QA rejected them, so those come from the
    # QA side rather than the review state.
    # One decision per work item per trigger, reused across items.
    agent_cache: dict = {}

    rejected = (
        db.query(models.CommunicationEvent)
        .filter(
            models.CommunicationEvent.owner_id == owner_id,
            models.CommunicationEvent.loop == "qa",
            models.CommunicationEvent.direction == "received",
            models.CommunicationEvent.outcome == "broken",
        )
        .order_by(models.CommunicationEvent.created_at.desc())
        .all()
    )

    failed_sends = (
        db.query(models.CommunicationEvent)
        .filter(
            models.CommunicationEvent.owner_id == owner_id,
            models.CommunicationEvent.direction == "sent",
            models.CommunicationEvent.succeeded == 0,
        )
        .order_by(models.CommunicationEvent.created_at.desc())
        .all()
    )

    tasks: dict[str, schemas.WorklistTask] = {}

    def task_for(key: str, repo: str, title: str | None) -> schemas.WorklistTask:
        if key not in tasks:
            tasks[key] = schemas.WorklistTask(
                key=key, repo=repo, title=title, items=[], pull_requests=[]
            )
        task = tasks[key]
        task.title = task.title or title
        return task

    # --- Review loop -----------------------------------------------------
    for review in reviews:
        if (review.repo, review.pr_number) in merged_idents or review.state in (
            schemas.ReviewState.merged.value,
            schemas.ReviewState.closed.value,
        ):
            continue

        key = _task_key(review)
        task = task_for(key, review.repo, review.pr_title)
        if review.pr_number not in task.pull_requests:
            task.pull_requests.append(review.pr_number)
        task.round_number = max(task.round_number, review.round_number)

        age = _age_hours(review.updated_at or review.created_at)

        if review.state == schemas.ReviewState.changes_requested.value:
            asks = [
                line.strip()
                for line in (review.pending_asks or "").splitlines()
                if line.strip()
            ]
            # The reviewer's own words. The checklist is for scanning; the
            # quote is what someone acts on.
            quotes = [
                r.body.strip()
                for r in reversed(review.rounds)
                if r.outcome == schemas.ReviewOutcome.changes_requested.value
                and r.body and r.body.strip()
            ][:1]

            task.items.append(schemas.WorklistItem(
                kind=schemas.WorklistKind.changes_requested,
                blocked_on_you=not _agent_handles(
                    db, owner_id=owner_id, repo=review.repo,
                    ticket_key=_task_key(review), trigger="review",
                    cache=agent_cache,
                ),
                repo=review.repo,
                pr_number=review.pr_number,
                pr_url=review.pr_url,
                headline=(
                    f"{review.last_reviewer or 'A reviewer'} requested changes"
                ),
                detail=asks,
                quotes=quotes,
                actor=review.last_reviewer,
                age_hours=age,
                round_number=review.round_number,
                # A human asked. Ranked above anything a model produced.
                from_human=True,
            ))

        elif review.state == schemas.ReviewState.awaiting_review.value:
            task.items.append(schemas.WorklistItem(
                kind=schemas.WorklistKind.awaiting_review,
                blocked_on_you=False,
                repo=review.repo,
                pr_number=review.pr_number,
                pr_url=review.pr_url,
                headline="Waiting on review",
                actor=review.last_reviewer,
                age_hours=age,
                round_number=review.round_number,
                from_human=True,
            ))

        elif review.state == schemas.ReviewState.approved.value:
            # Approved but not merged. Either auto-merge is off and a human
            # should merge it, or the gate is holding on something.
            task.items.append(schemas.WorklistItem(
                kind=schemas.WorklistKind.approved_not_merged,
                blocked_on_you=True,
                repo=review.repo,
                pr_number=review.pr_number,
                pr_url=review.pr_url,
                headline="Approved, not merged",
                actor=review.last_reviewer,
                age_hours=age,
                round_number=review.round_number,
                from_human=True,
            ))

    # --- Testing loop ----------------------------------------------------
    # When the fix for a rejection has already landed, the rejection is
    # answered. Its own query, because the review loop above deliberately
    # excludes merged and closed rows in SQL -- nobody is waiting on a finished
    # pull request, which is right for that loop and is exactly the rows this
    # question needs.
    merged_after: dict[str, list] = {}
    for review in (
        db.query(models.PRReview)
        .filter(
            models.PRReview.owner_id == owner_id,
            models.PRReview.state == schemas.ReviewState.merged.value,
        )
        .all()
    ):
        merged_after.setdefault(_task_key(review), []).append(review)

    seen_rejections: set[tuple[str, int]] = set()
    for event in rejected:
        ident = (event.repo, event.pr_number)
        if ident in seen_rejections:
            continue
        seen_rejections.add(ident)

        key = event.ticket_key or f"{event.repo}#{event.pr_number}"

        # A rejection answered by a later merge is history, not a queue item.
        #
        # The tester said it did not work, the agent (or a person) wrote the
        # fix, and it landed -- at which point the QA loop starts again on the
        # new pull request and *that* thread is what anyone should be waiting
        # on. Reporting the original rejection forever means a work item that
        # completed its whole round trip still reads "Needs you", which is the
        # same cry-wolf failure as reporting one the agent is mid-way through
        # handling, arriving one step later.
        #
        # Keyed on the merge being newer than the rejection, not merely
        # existing: the merge that the tester rejected is older than their
        # reply, and treating that one as the answer would silence every
        # rejection ever made.
        rejected_at = _as_utc(event.created_at)
        if rejected_at and any(
            (merged := _merged_at(review)) and merged > rejected_at
            for review in merged_after.get(key, [])
        ):
            continue
        task = task_for(key, event.repo, None)
        if event.pr_number not in task.pull_requests:
            task.pull_requests.append(event.pr_number)

        task.items.append(schemas.WorklistItem(
            kind=schemas.WorklistKind.qa_rejected,
            blocked_on_you=not _agent_handles(
                db, owner_id=owner_id, repo=event.repo,
                ticket_key=event.ticket_key, trigger="qa",
                cache=agent_cache,
            ),
            repo=event.repo,
            pr_number=event.pr_number,
            headline=f"{event.participant or 'A tester'} reported it broken",
            quotes=[event.body.strip()] if event.body else [],
            actor=event.participant,
            age_hours=_age_hours(event.created_at),
            from_human=True,
        ))

    # --- Unanswered testing threads --------------------------------------
    #
    # The safety net for closing on sign-off rather than at merge. A work item
    # now stays open until a tester replies, so a thread nobody answers would
    # otherwise leave it open forever with nothing chasing it -- trading a
    # ticket that closed too early for one that never closes, which is no
    # better for being quieter. Only unresolved threads count: a resolved one
    # got its answer.
    stale_cutoff = datetime.now(UTC) - timedelta(days=QA_SILENT_DAYS)
    user_pr_idents = {
        (r.repo, r.pr_number)
        for r in db.query(models.PRReview.repo, models.PRReview.pr_number)
        .filter(models.PRReview.owner_id == owner_id)
        .all()
        if r.repo and r.pr_number
    }
    silent_clauses = [
        (models.QAThread.owner_id == owner_id)
        & (models.QAThread.resolved == 0)
        & (models.QAThread.created_at < stale_cutoff)
    ]
    for r, p in user_pr_idents:
        silent_clauses.append(
            (models.QAThread.repo == r)
            & (models.QAThread.pr_number == p)
            & (models.QAThread.resolved == 0)
            & (models.QAThread.created_at < stale_cutoff)
        )
    silent_threads = (
        db.query(models.QAThread)
        .filter(or_(*silent_clauses))
        .all()
    )

    for thread in silent_threads:
        # A thread that was answered "broken" is already reported above as a
        # rejection; listing it again as unanswered would double-count one
        # conversation.
        if (thread.repo, thread.pr_number) in seen_rejections:
            continue

        key = _thread_key(db, thread)
        task = task_for(key, thread.repo, None)
        if thread.pr_number not in task.pull_requests:
            task.pull_requests.append(thread.pr_number)

        days = int(_age_hours(thread.created_at) / 24)
        task.items.append(schemas.WorklistItem(
            kind=schemas.WorklistKind.qa_unanswered,
            blocked_on_you=True,
            repo=thread.repo,
            pr_number=thread.pr_number,
            pr_url=thread.pr_url,
            headline=(
                f"No word from the testing team in {days} days"
                if days else "The testing team has not replied"
            ),
            detail=["The work item stays open until someone signs off."],
            age_hours=_age_hours(thread.created_at),
            # Nobody said this; it is the absence of anyone saying anything.
            from_human=False,
        ))

    # --- Delivery --------------------------------------------------------
    for event in failed_sends:
        key = event.ticket_key or f"{event.repo}#{event.pr_number}"
        task = task_for(key, event.repo, None)
        if event.pr_number not in task.pull_requests:
            task.pull_requests.append(event.pr_number)

        task.items.append(schemas.WorklistItem(
            kind=schemas.WorklistKind.delivery_failed,
            blocked_on_you=True,
            repo=event.repo,
            pr_number=event.pr_number,
            headline=f"A {event.channel} message was not delivered",
            quotes=[event.body.strip()] if event.body else [],
            age_hours=_age_hours(event.created_at),
            # Locus failed to send this, not a person. Ranked below human asks.
            from_human=False,
        ))

    # --- Ordering --------------------------------------------------------
    for task in tasks.values():
        # Within a task: things you can act on, humans before machines, then
        # oldest first.
        task.items.sort(
            key=lambda i: (
                not i.blocked_on_you,
                not i.from_human,
                -i.age_hours,
            )
        )
        task.needs_you = any(i.blocked_on_you for i in task.items)
        task.age_hours = max((i.age_hours for i in task.items), default=0.0)

    ordered = sorted(
        tasks.values(),
        key=lambda t: (
            not t.needs_you,
            # Staleness, not severity. A long-running round trip is the thing
            # worth seeing, and round count breaks the tie when ages match.
            -t.age_hours,
            -t.round_number,
        ),
    )

    needs_you = [t for t in ordered if t.needs_you]
    waiting = [t for t in ordered if not t.needs_you]

    return schemas.Worklist(
        needs_you=needs_you,
        waiting_on_others=waiting,
        total_needs_you=sum(
            len([i for i in t.items if i.blocked_on_you]) for t in needs_you
        ),
    )
