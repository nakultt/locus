"""
The task board: assigned work, joined to everything Locus knows about it.

This answers the question the per-PR views cannot -- "where is this piece of
work, from the moment it landed on me to the moment testing signed off" --
by keying on the work item rather than the pull request.

**The ticket key is the join, and it already exists.** `PRReview.ticket_keys`
and `CommunicationEvent.ticket_key` have stored keys since the review loop was
built, and `worklist._task_key` already groups on the same key space with a
`repo#N` fallback. So an assigned Jira ticket finds its pull requests, its
Slack discussion and its QA thread by matching a key that was recorded when
the analysis ran. No new extraction, and nothing to keep in sync.

**Attention comes from `worklist.build`, not from here.** The worklist already
decides what is blocked on you and how urgent it is, and those rules are
pinned by tests. Recomputing them would let the board and the worklist
disagree about the same task, so this reuses that output and only adds the
pipeline position on top.

**The stage is derived, never stored.** A stored stage would need updating
from three loops that already write concurrently, and would go stale exactly
when someone is watching. It is cheap to recompute from the review state, the
QA thread and the job status, so it is.
"""

import asyncio
import json
import logging

from sqlalchemy.orm import Session

from app import models, schemas
from app.services import assigned, comms_log, review_flow, worklist

logger = logging.getLogger(__name__)

# What each stage is called on the card. Phrased as the state the work is in,
# not as the action Locus took, because the card describes the work.
STAGE_LABELS: dict[schemas.TaskStage, str] = {
    schemas.TaskStage.assigned: "Assigned",
    schemas.TaskStage.in_progress: "Pull request opened",
    schemas.TaskStage.analyzed: "Context gathered and scanned",
    schemas.TaskStage.in_review: "Senior dev review",
    schemas.TaskStage.changes_requested: "Changes requested",
    schemas.TaskStage.approved: "Approved",
    schemas.TaskStage.merged: "Merged",
    schemas.TaskStage.testing: "With the testing team",
    schemas.TaskStage.done: "Signed off",
}

# Stages that only appear once they have actually happened. A task that went
# straight from review to approval never had changes requested, and rendering
# that step greyed-out would imply a round trip that did not occur.
CONDITIONAL_STAGES = {schemas.TaskStage.changes_requested}


def _ticket_keys(review: models.PRReview) -> list[str]:
    """Every work item key recorded against a pull request."""
    return [
        line.strip()
        for line in (review.ticket_keys or "").splitlines()
        if line.strip()
    ]


def _derive_stage(
    reviews: list[models.PRReview],
    qa: models.QAThread | None,
    analyzed: bool,
    has_pr: bool = False,
) -> tuple[schemas.TaskStage, bool]:
    """
    How far this task has travelled, and whether changes were ever requested.

    Takes the furthest position across every pull request on the task: a
    ticket whose first PR merged and whose follow-up is still in review is
    genuinely still in review, but a ticket with one merged PR and one
    abandoned draft has merged. Ordering the states and taking the max
    resolves both without special-casing either.

    A `PRReview` row only exists once someone requests a review, so the early
    stages cannot be derived from it. An open pull request that has been
    analyzed but not yet sent for review is real progress, and reporting it as
    `assigned` would say no work had started at all.
    """
    if qa is not None:
        return (
            schemas.TaskStage.done if qa.resolved else schemas.TaskStage.testing
        ), any(
            r.state == schemas.ReviewState.changes_requested.value for r in reviews
        )

    if not reviews:
        if analyzed:
            return schemas.TaskStage.analyzed, False
        if has_pr:
            return schemas.TaskStage.in_progress, False
        return schemas.TaskStage.assigned, False

    # Ranked by how far along the loop each state is.
    rank = {
        schemas.ReviewState.awaiting_review.value: 0,
        schemas.ReviewState.changes_requested.value: 1,
        schemas.ReviewState.approved.value: 2,
        schemas.ReviewState.merged.value: 3,
    }
    furthest = max(reviews, key=lambda r: rank.get(r.state, 0))
    had_changes = any(
        r.state == schemas.ReviewState.changes_requested.value
        or any(
            round_.outcome == schemas.ReviewOutcome.changes_requested.value
            for round_ in r.rounds
        )
        for r in reviews
    )

    state_to_stage = {
        schemas.ReviewState.awaiting_review.value: schemas.TaskStage.in_review,
        schemas.ReviewState.changes_requested.value: schemas.TaskStage.changes_requested,
        schemas.ReviewState.approved.value: schemas.TaskStage.approved,
        schemas.ReviewState.merged.value: schemas.TaskStage.merged,
    }
    return state_to_stage.get(furthest.state, schemas.TaskStage.in_progress), had_changes


def _build_stages(
    current: schemas.TaskStage,
    had_changes: bool,
    reviews: list[models.PRReview],
) -> list[schemas.TaskStageStatus]:
    """
    The stepper: every stage, marked done, current or not yet reached.

    Every step is rendered rather than only the reached ones, so the card
    shows the shape of the whole pipeline. That is the point of the view --
    someone should be able to see that testing is coming without having got
    there yet.
    """
    order = [
        stage for stage in schemas.TASK_STAGE_ORDER
        if stage not in CONDITIONAL_STAGES or had_changes
    ]
    current_index = order.index(current) if current in order else 0

    stages: list[schemas.TaskStageStatus] = []
    for index, stage in enumerate(order):
        if index < current_index:
            state = schemas.StageState.done
        elif index == current_index:
            # The terminal stage is reached, not in flight.
            state = (
                schemas.StageState.done
                if stage is schemas.TaskStage.done
                else schemas.StageState.running
            )
        else:
            state = schemas.StageState.pending

        detail = None
        if stage is schemas.TaskStage.in_review and reviews:
            rounds = max(r.round_number for r in reviews)
            if rounds > 1:
                detail = f"round {rounds}"
        elif stage in (
            schemas.TaskStage.in_progress,
            schemas.TaskStage.analyzed,
        ) and reviews:
            detail = f"{len(reviews)} PR" + ("s" if len(reviews) > 1 else "")

        stages.append(schemas.TaskStageStatus(
            stage=stage, label=STAGE_LABELS[stage], state=state, detail=detail
        ))

    return stages


def _matching_reviews(
    reviews: list[models.PRReview], key: str, item: schemas.AssignedItem
) -> list[models.PRReview]:
    """
    The pull requests belonging to one assigned item.

    A Jira ticket matches by recorded ticket key. A GitHub issue matches the
    same way when the key was recorded, and otherwise by repo -- an issue and
    a pull request in the same repository with the issue's key in the branch
    is the common case, and the analysis records that key.
    """
    matched = [r for r in reviews if key in _ticket_keys(r)]
    if matched:
        return matched

    # The `repo#N` fallback the worklist uses for a PR with no ticket.
    if item.source is schemas.TaskSource.github and item.repo:
        return [
            r for r in reviews
            if not _ticket_keys(r) and r.repo == item.repo
            and f"{r.repo}#{r.pr_number}" == key
        ]
    return []


def _blocked_reason(items: list[schemas.WorklistItem]) -> str | None:
    """
    Why this task is stuck, in the words of whoever stuck it.

    Taken from the highest-ranked worklist item, which is already sorted so
    the thing most worth acting on comes first.
    """
    for item in items:
        if item.blocked_on_you:
            return item.headline
    return None


async def fetch_assigned(
    integration_configs: dict[str, dict],
) -> tuple[list[schemas.AssignedItem], list[str]]:
    """
    Everything assigned to this user, from every connected source.

    Both sources are queried concurrently and each swallows its own failure,
    so one dead integration costs its own half of the board and nothing else.
    Returns the items alongside the names of any source that did not answer.
    """
    github_config = integration_configs.get("github") or {}
    jira_config = integration_configs.get("jira") or {}

    tasks = []
    sources: list[str] = []
    if github_config.get("api_key"):
        tasks.append(assigned.github_assigned(github_config["api_key"]))
        sources.append("github")
    if jira_config:
        tasks.append(assigned.jira_assigned(jira_config))
        sources.append("jira")

    if not tasks:
        return [], []

    results = await asyncio.gather(*tasks, return_exceptions=True)

    items: list[schemas.AssignedItem] = []
    unavailable: list[str] = []
    for source, result in zip(sources, results, strict=True):
        if isinstance(result, BaseException):
            logger.debug("Assigned lookup failed for %s: %s", source, result)
            unavailable.append(source)
            continue
        # A connected source that returns nothing may genuinely have nothing
        # assigned, so an empty list is not treated as a failure.
        items.extend(result)

    return items, unavailable


async def build(
    db: Session,
    *,
    owner_id: int,
    integration_configs: dict[str, dict],
) -> schemas.TaskBoard:
    """
    Assemble the board for one user.

    Ordering is settled here rather than in the client, for the same reason
    the worklist settles its own: the API and the UI must not be able to
    disagree about what is most urgent.
    """
    items, unavailable = await fetch_assigned(integration_configs)

    reviews = (
        db.query(models.PRReview)
        .filter(models.PRReview.owner_id == owner_id)
        .all()
    )
    qa_threads = (
        db.query(models.QAThread)
        .filter(models.QAThread.owner_id == owner_id)
        .order_by(models.QAThread.created_at.desc())
        .all()
    )
    analyzed_prs = {
        (job.repo, job.pr_number)
        for job in db.query(models.PRJob)
        .filter(
            models.PRJob.owner_id == owner_id,
            models.PRJob.status == schemas.PRJobStatus.completed.value,
        )
        .all()
    }

    # Which pull requests belong to which work item, from the key the analysis
    # recorded. A `PRReview` row only appears once a review is requested, so
    # without this an open, analyzed pull request is invisible to the join and
    # its task reads as "assigned" -- as though nobody had started.
    prs_by_key: dict[str, set[tuple[str, int]]] = {}
    for event in (
        db.query(
            models.CommunicationEvent.ticket_key,
            models.CommunicationEvent.repo,
            models.CommunicationEvent.pr_number,
        )
        .filter(
            models.CommunicationEvent.owner_id == owner_id,
            models.CommunicationEvent.ticket_key.isnot(None),
        )
        .distinct()
        .all()
    ):
        prs_by_key.setdefault(event.ticket_key, set()).add(
            (event.repo, event.pr_number)
        )

    # Attention, computed once by the module that owns those rules.
    work = worklist.build(db, owner_id=owner_id)
    by_key = {
        task.key: task for task in (work.needs_you + work.waiting_on_others)
    }

    cards: list[schemas.TaskCard] = []
    for item in items:
        matched = _matching_reviews(reviews, item.key, item)
        pr_idents = {(r.repo, r.pr_number) for r in matched}

        # Pull requests known only from the analysis log, before any review
        # was requested. Reviewed PRs already carry richer rows, so those win.
        logged_prs = prs_by_key.get(item.key, set())
        pr_idents |= logged_prs

        qa = next(
            (
                thread for thread in qa_threads
                if (thread.repo, thread.pr_number) in pr_idents
                or item.key in json.loads(thread.ticket_keys_json or "[]")
            ),
            None,
        )
        analyzed = bool(pr_idents & analyzed_prs)

        stage, had_changes = _derive_stage(
            matched, qa, analyzed, has_pr=bool(pr_idents)
        )
        task = by_key.get(item.key)

        # Every pull request on this work item: the reviewed ones with their
        # full state, then any known only from the analysis log.
        reviewed_idents = {(r.repo, r.pr_number) for r in matched}
        pull_requests = [
            schemas.TaskPullRequest(
                repo=r.repo,
                pr_number=r.pr_number,
                url=r.pr_url,
                title=r.pr_title,
                author=r.author,
                review_state=r.state,
                round_number=r.round_number,
                last_reviewer=r.last_reviewer,
            )
            for r in sorted(matched, key=lambda r: r.pr_number)
        ]
        pull_requests += [
            schemas.TaskPullRequest(
                repo=repo,
                pr_number=number,
                url=f"https://github.com/{repo}/pull/{number}",
            )
            for repo, number in sorted(logged_prs - reviewed_idents)
        ]

        cards.append(schemas.TaskCard(
            key=item.key,
            source=item.source,
            title=item.title,
            url=item.url,
            status=item.status,
            assignee=item.assignee,
            issue_type=item.issue_type,
            priority=item.priority,
            updated_at=item.updated_at,
            stage=stage,
            stages=_build_stages(stage, had_changes, matched),
            pull_requests=pull_requests,
            items=task.items if task else [],
            needs_you=task.needs_you if task else False,
            blocked_reason=_blocked_reason(task.items) if task else None,
            age_hours=task.age_hours if task else 0.0,
            round_number=max((r.round_number for r in matched), default=1),
        ))

    # Needs-you first, then staleness -- a task that has been round-tripping
    # for a week is the signal worth surfacing, not the one with the worst
    # findings. Severity ranks findings; this is a list of conversations.
    cards.sort(key=lambda c: (not c.needs_you, -c.age_hours, -c.round_number))

    return schemas.TaskBoard(
        needs_you=[c for c in cards if c.needs_you],
        in_flight=[c for c in cards if not c.needs_you],
        total=len(cards),
        github_available="github" not in unavailable,
        jira_available="jira" not in unavailable,
        unavailable=unavailable,
    )


def detail_for(
    db: Session,
    *,
    owner_id: int,
    card: schemas.TaskCard,
    settings,
) -> schemas.TaskDetail:
    """
    One task's full pipeline: the analysis, every review round, every message.

    The message log comes from `comms_log.ticket_timeline`, which returns
    everything recorded under this work item across every pull request that
    touched it. That is deliberately wider than one PR's timeline: the second
    PR on a ticket inherits the first one's discussion, the reviewer was given
    it, and a log restricted to this PR would omit context the run used.
    """
    pr_idents = [(pr.repo, pr.pr_number) for pr in card.pull_requests]

    reviews = [
        review_flow_detail
        for review_flow_detail in (
            _review_detail(db, owner_id=owner_id, repo=repo, pr_number=number)
            for repo, number in pr_idents
        )
        if review_flow_detail is not None
    ]

    # The latest completed run on the newest pull request. Findings are never
    # reused across rounds, so this is whatever the most recent analysis
    # actually produced rather than an accumulation.
    analysis = None
    job_status = None
    job_error = None
    if pr_idents:
        repo, number = pr_idents[-1]
        job = (
            db.query(models.PRJob)
            .filter(
                models.PRJob.owner_id == owner_id,
                models.PRJob.repo == repo,
                models.PRJob.pr_number == number,
            )
            .order_by(models.PRJob.created_at.desc())
            .first()
        )
        if job is not None:
            job_status = job.status
            job_error = job.error
            if job.result_json:
                try:
                    analysis = schemas.PRAnalysisResult.model_validate_json(
                        job.result_json
                    )
                except Exception:
                    # A result stored under an older schema must not 500 the
                    # endpoint; the rest of the card is still useful.
                    analysis = None

    qa = next(
        (
            thread
            for thread in db.query(models.QAThread)
            .filter(models.QAThread.owner_id == owner_id)
            .order_by(models.QAThread.created_at.desc())
            .all()
            if (thread.repo, thread.pr_number) in pr_idents
        ),
        None,
    )

    events = comms_log.ticket_timeline(db, owner_id=owner_id, ticket_key=card.key)
    if not events and pr_idents:
        # A task whose analysis never recorded a ticket key still has a
        # message log, stored per pull request.
        repo, number = pr_idents[-1]
        events = comms_log.timeline(
            db, owner_id=owner_id, repo=repo, pr_number=number
        )

    logins = list(settings.reviewers)
    for review in reviews:
        if review.last_reviewer and review.last_reviewer not in logins:
            logins.append(review.last_reviewer)

    return schemas.TaskDetail(
        card=card,
        analysis=analysis,
        job_status=job_status,
        job_error=job_error,
        reviews=reviews,
        reviewer_contacts=[
            schemas.ReviewerContact(
                login=login,
                slack=settings.reviewer_contacts.get(login, {}).get("slack"),
                email=settings.reviewer_contacts.get(login, {}).get("email"),
            )
            for login in logins
        ],
        qa_notified=qa is not None,
        qa_resolved=bool(qa.resolved) if qa else None,
        qa_channel=qa.slack_channel if qa else settings.slack_channel,
        qa_recipients=settings.qa_emails,
        events=[schemas.CommunicationEvent.model_validate(e) for e in events],
    )


def _review_detail(
    db: Session, *, owner_id: int, repo: str, pr_number: int
) -> schemas.PRReviewDetail | None:
    """One pull request's review row, rendered with its full round history."""
    review = (
        db.query(models.PRReview)
        .filter(
            models.PRReview.repo == repo,
            models.PRReview.pr_number == pr_number,
            models.PRReview.owner_id == owner_id,
        )
        .first()
    )
    return review_flow.to_detail(review) if review else None
