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

import logging
from datetime import UTC, datetime, timedelta

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

    return f"{thread.repo}#{thread.pr_number}"


def build(db: Session, *, owner_id: int) -> schemas.Worklist:
    """
    Assemble the worklist for one user.

    Ordering is decided here rather than in the client: the API and the UI must
    not be able to disagree about what is most urgent.
    """
    reviews = (
        db.query(models.PRReview)
        .filter(
            models.PRReview.owner_id == owner_id,
            models.PRReview.state != schemas.ReviewState.merged.value,
        )
        .all()
    )

    # Merged PRs still matter when QA rejected them, so those come from the
    # QA side rather than the review state.
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
                blocked_on_you=True,
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
    seen_rejections: set[tuple[str, int]] = set()
    for event in rejected:
        ident = (event.repo, event.pr_number)
        if ident in seen_rejections:
            continue
        seen_rejections.add(ident)

        key = event.ticket_key or f"{event.repo}#{event.pr_number}"
        task = task_for(key, event.repo, None)
        if event.pr_number not in task.pull_requests:
            task.pull_requests.append(event.pr_number)

        task.items.append(schemas.WorklistItem(
            kind=schemas.WorklistKind.qa_rejected,
            blocked_on_you=True,
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
    silent_threads = (
        db.query(models.QAThread)
        .filter(
            models.QAThread.owner_id == owner_id,
            models.QAThread.resolved == 0,
            models.QAThread.created_at < stale_cutoff,
        )
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
