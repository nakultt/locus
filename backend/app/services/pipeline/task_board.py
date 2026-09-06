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

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app import models, schemas
from app.services.authoring import authoring
from app.services.integrations import issue_links
from app.services.pipeline import (
    assigned,
    comms_log,
    report_sync,
    review_flow,
    worklist,
)
from app.services.pipeline.agent_settings import resolve_settings

logger = logging.getLogger(__name__)

# What each stage is called on the card. Phrased as the state the work is in,
# not as the action Locus took, because the card describes the work.
STAGE_LABELS: dict[schemas.TaskStage, str] = {
    schemas.TaskStage.assigned: "Assigned",
    schemas.TaskStage.authoring: "Locus is writing it",
    schemas.TaskStage.branch_created: "Branch created",
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
#
# `branch_created` is conditional for the same reason and one more: it is
# observable only for GitHub issues, whose Development panel records the link.
# A Jira ticket has no such edge, so rendering the step on every card would
# show most tasks permanently skipping a stage that was never available to
# them.
CONDITIONAL_STAGES = {
    schemas.TaskStage.changes_requested,
    schemas.TaskStage.branch_created,
    # Rendered only when the resolved mode is autonomous. Showing it greyed-out
    # on every assisted task would imply a step that was skipped, where in fact
    # it was never available -- the same argument as `changes_requested`.
    schemas.TaskStage.authoring,
}


def _ticket_keys(review: models.PRReview) -> list[str]:
    """Every work item key recorded against a pull request."""
    return [
        line.strip()
        for line in (review.ticket_keys or "").splitlines()
        if line.strip()
    ]


def _matches_qa(
    thread: models.QAThread,
    pr_idents: set[tuple[str, int]],
    ticket_key: str,
) -> bool:
    if thread.repo and thread.pr_number and (thread.repo, thread.pr_number) in pr_idents:
        return True
    if thread.ticket_keys_json:
        try:
            keys = json.loads(thread.ticket_keys_json)
            if ticket_key in keys:
                return True
        except Exception:
            pass
    return False


def _derive_stage(
    reviews: list[models.PRReview],
    qa: models.QAThread | None,
    analyzed: bool,
    has_pr: bool = False,
    has_branch: bool = False,
    has_attempt: bool = False,
    merged_idents: set[tuple[str, int]] | None = None,
    has_qa_event: bool = False,
    item_status: str | None = None,
) -> tuple[schemas.TaskStage, bool]:
    """
    How far this task has travelled, and whether changes were ever requested.

    **Work still in flight decides the stage.** A task is a sequence of
    attempts, not a set of them: when QA rejects a merged change the ticket
    reopens, the fix arrives as a fresh pull request, and the task is back at
    the start of the review loop. The first attempt is history. Reading the
    task as "the furthest any of its pull requests ever got" reports that
    reopened ticket as merged, or -- because the rejected QA thread stays
    unresolved by design -- as still with the testing team, for the whole of
    the second review round. Both readings say the work is further along than
    it is, on exactly the round trip this pipeline exists to automate.

    So an unmerged pull request wins over both the QA thread and any earlier
    merged one. Among several in flight at once the furthest still wins, which
    is what a task with two open pull requests actually means.

    Once every pull request has merged there is nothing in flight and the
    ordinary reading resumes: the QA thread decides, then the merge.

    A `PRReview` row only exists once someone requests a review, so the early
    stages cannot be derived from it. An open pull request that has been
    analyzed but not yet sent for review is real progress, and reporting it as
    `assigned` would say no work had started at all.

    A linked branch is the earliest evidence there is. It ranks below every
    pull-request stage rather than replacing them: the branch stays linked
    after its PR opens, and letting it win would walk a reviewed task
    backwards to "branch created" on every refresh.

    An authoring attempt ranks below even that, for exactly the same reason:
    the attempt row is append-only and stays behind forever, so a rule letting
    it win would walk a reviewed card back to "Locus is writing it" on every
    refresh.
    """
    # Computed across every attempt, in flight or not: a round trip on the
    # first pull request is still something that happened to this task.
    had_changes = any(
        r.state == schemas.ReviewState.changes_requested.value
        or any(
            round_.outcome == schemas.ReviewOutcome.changes_requested.value
            for round_ in r.rounds
        )
        for r in reviews
    )

    merged_set = set(merged_idents or ())
    if qa is not None and qa.repo and qa.pr_number:
        merged_set.add((qa.repo, qa.pr_number))

    # In flight means open, not merely un-merged. A pull request closed
    # without merging is abandoned work: it is not going to advance, and
    # letting it stay in this list pinned the task at whatever state it was
    # abandoned in -- forever, and regardless of how far its replacement got.
    finished = {
        schemas.ReviewState.merged.value,
        schemas.ReviewState.closed.value,
    }
    in_flight = [
        r for r in reviews
        if r.state not in finished and (r.repo, r.pr_number) not in merged_set
    ]

    if not in_flight:
        if qa is not None:
            return (
                schemas.TaskStage.done if qa.resolved
                else schemas.TaskStage.testing
            ), had_changes

        if has_qa_event:
            return schemas.TaskStage.testing, had_changes

        # Only an actual merge reports as merged. Every pull request having
        # been closed unmerged means the work was abandoned, not landed, so
        # the task falls back to what the evidence below it supports.
        if (
            any(r.state == schemas.ReviewState.merged.value for r in reviews)
            or any((r.repo, r.pr_number) in merged_set for r in reviews)
        ):
            return schemas.TaskStage.merged, had_changes

        if item_status:
            normalized = item_status.strip().lower()
            if normalized in {"done", "closed", "resolved", "released"}:
                return schemas.TaskStage.done, had_changes
            if normalized in {
                "qa", "in qa", "testing", "test", "ready for qa",
                "ready for test", "qa in progress", "under test",
            }:
                return schemas.TaskStage.testing, had_changes

        if analyzed:
            return schemas.TaskStage.analyzed, False
        if has_pr:
            return schemas.TaskStage.in_progress, False
        if has_branch:
            return schemas.TaskStage.branch_created, False
        if has_attempt:
            return schemas.TaskStage.authoring, False
        return schemas.TaskStage.assigned, False

    # Ranked by how far along the loop each state is.
    rank = {
        schemas.ReviewState.awaiting_review.value: 0,
        schemas.ReviewState.changes_requested.value: 1,
        schemas.ReviewState.approved.value: 2,
    }
    furthest = max(in_flight, key=lambda r: rank.get(r.state, 0))

    state_to_stage = {
        schemas.ReviewState.awaiting_review.value: schemas.TaskStage.in_review,
        schemas.ReviewState.changes_requested.value: schemas.TaskStage.changes_requested,
        schemas.ReviewState.approved.value: schemas.TaskStage.approved,
    }
    return state_to_stage.get(furthest.state, schemas.TaskStage.in_progress), had_changes


def _build_stages(
    current: schemas.TaskStage,
    had_changes: bool,
    reviews: list[models.PRReview],
    branches: list[schemas.LinkedBranch] | None = None,
    autonomous: bool = False,
    attempts: int = 0,
) -> list[schemas.TaskStageStatus]:
    """
    The stepper: every stage, marked done, current or not yet reached.

    Every step is rendered rather than only the reached ones, so the card
    shows the shape of the whole pipeline. That is the point of the view --
    someone should be able to see that testing is coming without having got
    there yet.
    """
    branches = branches or []
    shown: dict[schemas.TaskStage, bool] = {
        schemas.TaskStage.changes_requested: had_changes,
        # Rendered whenever a branch is linked, and also when the task is
        # sitting on that stage -- the two coincide today, but deriving the
        # step from the current stage as well means the stepper can never
        # render a card whose current stage is missing from its own order.
        schemas.TaskStage.branch_created: bool(branches)
        or current is schemas.TaskStage.branch_created,
        # Only for a work item actually set to autonomous. Deriving it from
        # the current stage as well means the stepper can never render a card
        # whose current stage is missing from its own order.
        schemas.TaskStage.authoring: autonomous
        or current is schemas.TaskStage.authoring,
    }
    order = [
        stage for stage in schemas.TASK_STAGE_ORDER
        if stage not in CONDITIONAL_STAGES or shown.get(stage, False)
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
        if stage is schemas.TaskStage.branch_created and branches:
            detail = branches[0].name
            if len(branches) > 1:
                detail += f" +{len(branches) - 1}"
        elif stage is schemas.TaskStage.authoring and attempts:
            detail = f"{attempts} attempt" + ("s" if attempts > 1 else "")
        elif stage is schemas.TaskStage.in_review and reviews:
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
    reviews: list[models.PRReview],
    key: str,
    item: schemas.AssignedItem,
    links: schemas.IssueLinks | None = None,
) -> list[models.PRReview]:
    """
    The pull requests belonging to one assigned item.

    A Jira ticket matches by recorded ticket key. A GitHub issue matches the
    same way when the key was recorded, and otherwise by repo -- an issue and
    a pull request in the same repository with the issue's key in the branch
    is the common case, and the analysis records that key.

    GitHub's own link graph is consulted last and unions rather than replaces.
    It catches the two cases the recorded key cannot: a pull request attached
    through the Development panel, which carries no closing keyword for the
    analysis to have read, and any pull request on an issue whose analysis has
    not run yet. Union rather than fallback because the two disagree in a
    normal way -- a task with three PRs may have one linked in the panel and
    two recorded from keywords, and either alone is an incomplete list.
    """
    matched = {
        (r.repo, r.pr_number): r for r in reviews if key in _ticket_keys(r)
    }

    if not matched and item.source is schemas.TaskSource.github and item.repo:
        # The `repo#N` fallback the worklist uses for a PR with no ticket.
        matched = {
            (r.repo, r.pr_number): r
            for r in reviews
            if not _ticket_keys(r) and r.repo == item.repo
            and f"{r.repo}#{r.pr_number}" == key
        }

    if links:
        linked_idents = {(pr.repo, pr.pr_number) for pr in links.pull_requests}
        for review in reviews:
            ident = (review.repo, review.pr_number)
            if ident in linked_idents:
                matched.setdefault(ident, review)

    return [matched[ident] for ident in sorted(matched, key=lambda i: i[1])]


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
    *,
    done: bool = False,
) -> tuple[list[schemas.AssignedItem], list[str]]:
    """
    Everything assigned to this user, from every connected source.

    Both sources are queried concurrently and each swallows its own failure,
    so one dead integration costs its own half of the board and nothing else.
    Returns the items alongside the names of any source that did not answer.

    Args:
        done: Fetch recently-completed work instead of open work. The two are
            separate queries rather than one widened one, because the open
            board is what someone opens this page for and it must not be made
            slower, or failable, by the completed section beside it.
    """
    github_config = integration_configs.get("github") or {}
    jira_config = integration_configs.get("jira") or {}

    tasks = []
    sources: list[str] = []
    if github_config.get("api_key"):
        tasks.append(
            assigned.github_recently_done(github_config["api_key"]) if done
            else assigned.github_assigned(github_config["api_key"])
        )
        sources.append("github")
    if jira_config:
        tasks.append(
            assigned.jira_recently_done(jira_config) if done
            else assigned.jira_assigned(jira_config)
        )
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


def _persist_links(
    db: Session,
    *,
    owner_id: int,
    item: schemas.AssignedItem,
    links: schemas.IssueLinks,
    reviews: list[models.PRReview],
) -> None:
    """
    Record a Development-panel link on the review rows it names.

    The edge came from GitHub's link graph, so writing it as a ticket key is
    recording what GitHub reports rather than inferring a work item -- the
    distinction `work_item` draws. Once stored, the pull request is findable as
    a sibling of the work item, which is what lets a reopened ticket's next PR
    inherit the history, and the board no longer depends on the links call
    having succeeded.

    Only ever adds. A pull request routinely belongs to several work items, and
    replacing the recorded keys would drop the Jira key an analysis found in
    the branch name -- costing exactly the context this exists to preserve.

    Never fails the board: the links are already rendered from the live query
    by the time this runs, so a write that cannot happen costs persistence and
    nothing the user sees. This follows `comms_log`'s rule that recording never
    breaks the work it describes.
    """
    linked_idents = {(pr.repo, pr.pr_number) for pr in links.pull_requests}
    if not linked_idents:
        return

    changed = False
    for review in reviews:
        if (review.repo, review.pr_number) not in linked_idents:
            continue
        keys = _ticket_keys(review)
        if item.key in keys:
            continue
        review.ticket_keys = "\n".join([*keys, item.key])
        changed = True

    if not changed:
        return

    try:
        db.commit()
    except Exception as e:
        logger.debug("Recording issue links failed for %s: %s", item.key, e)
        db.rollback()


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

    # Work that finished recently, rendered in its own section.
    #
    # Both source queries above ask only for unfinished work, so a ticket
    # vanished from the board the moment QA sign-off closed it -- and with it
    # the only surface that assembles the pipeline record. The successful run
    # became the one you could no longer look at.
    #
    # `unavailable` is deliberately not extended by this: a source that
    # answered the open query and failed this one has not left the board
    # degraded in the way that flag means, and reporting it would put a
    # warning on a board that is showing everything it is being asked for.
    done_items, _ = await fetch_assigned(integration_configs, done=True)
    done_keys = {item.key for item in done_items}

    # Built through the same path, so a finished card carries the same stages,
    # pull requests and history as a live one. A separate renderer would drift.
    items = [*items, *done_items]

    # What GitHub itself says is being done about each assigned issue. Costs
    # one request for the whole board and degrades to an empty mapping, so a
    # failure here loses the Development-panel links and nothing else.
    github_token = (integration_configs.get("github") or {}).get("api_key") or ""
    links_by_key = await issue_links.fetch(github_token, items)

    # Collect PR identifiers known to be associated with this user's assigned items
    # and authoring attempts, so team-registered webhooks or co-authored PRs are
    # correctly visible on this user's task board.
    user_pr_idents: set[tuple[str, int]] = set()
    user_ticket_keys: set[str] = {item.key for item in items}
    for links in links_by_key.values():
        for pr in links.pull_requests:
            if pr.repo and pr.pr_number:
                user_pr_idents.add((pr.repo, pr.pr_number))

    for row in (
        db.query(
            models.AuthoringAttempt.ticket_key,
            models.AuthoringAttempt.repo,
            models.AuthoringAttempt.pr_number,
        )
        .filter(models.AuthoringAttempt.owner_id == owner_id)
        .all()
    ):
        if row.ticket_key:
            user_ticket_keys.add(row.ticket_key)
        if row.repo and row.pr_number:
            user_pr_idents.add((row.repo, row.pr_number))

    for rev in (
        db.query(
            models.PRReview.repo,
            models.PRReview.pr_number,
            models.PRReview.ticket_keys,
        )
        .filter(models.PRReview.owner_id == owner_id)
        .all()
    ):
        if rev.repo and rev.pr_number:
            user_pr_idents.add((rev.repo, rev.pr_number))
        if rev.ticket_keys:
            for k in rev.ticket_keys.splitlines():
                if k.strip():
                    user_ticket_keys.add(k.strip())

    # Every report document this owner has or associated with their PRs/tickets,
    # in one query, so the per-card resolution below is a dict lookup rather
    # than a round trip each.
    docs_by_ticket, docs_by_pr = report_sync.document_urls_for(
        db, owner_id=owner_id, pr_idents=user_pr_idents, ticket_keys=user_ticket_keys
    )

    review_clauses = [models.PRReview.owner_id == owner_id]
    for r, p in user_pr_idents:
        review_clauses.append(
            (models.PRReview.repo == r) & (models.PRReview.pr_number == p)
        )
    reviews = (
        db.query(models.PRReview)
        .filter(or_(*review_clauses))
        .all()
    )
    for rev in reviews:
        if rev.repo and rev.pr_number:
            user_pr_idents.add((rev.repo, rev.pr_number))

    qa_threads = (
        db.query(models.QAThread)
        .order_by(models.QAThread.created_at.desc())
        .all()
    )

    system_merged_idents: set[tuple[str, int]] = {
        (t.repo, t.pr_number)
        for t in qa_threads
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

    qa_event_prs: set[tuple[str, int]] = {
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
    qa_event_tickets: set[str] = {
        e.ticket_key
        for e in db.query(models.CommunicationEvent.ticket_key)
        .filter(
            models.CommunicationEvent.loop == "qa",
            models.CommunicationEvent.direction == "sent",
            models.CommunicationEvent.outcome == "ready_to_test",
            models.CommunicationEvent.succeeded == 1,
            models.CommunicationEvent.ticket_key.isnot(None),
        )
        .all()
        if e.ticket_key
    }

    job_clauses = [models.PRJob.owner_id == owner_id]
    for r, p in user_pr_idents:
        job_clauses.append(
            (models.PRJob.repo == r) & (models.PRJob.pr_number == p)
        )
    analyzed_prs = {
        (job.repo, job.pr_number)
        for job in db.query(models.PRJob)
        .filter(
            or_(*job_clauses),
            models.PRJob.status == schemas.PRJobStatus.completed.value,
        )
        .all()
    }

    # Which pull requests belong to which work item, from the key the analysis
    # recorded. A `PRReview` row only appears once a review is requested, so
    # without this an open, analyzed pull request is invisible to the join and
    # its task reads as "assigned" -- as though nobody had started.
    comm_clauses = [models.CommunicationEvent.owner_id == owner_id]
    for r, p in user_pr_idents:
        comm_clauses.append(
            (models.CommunicationEvent.repo == r)
            & (models.CommunicationEvent.pr_number == p)
        )
    for k in user_ticket_keys:
        comm_clauses.append(models.CommunicationEvent.ticket_key == k)

    prs_by_key: dict[str, set[tuple[str, int]]] = {}
    for event in (
        db.query(
            models.CommunicationEvent.ticket_key,
            models.CommunicationEvent.repo,
            models.CommunicationEvent.pr_number,
        )
        .filter(
            or_(*comm_clauses),
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

    # Attempt counts for every work item at once, rather than a query per card.
    attempts_by_key: dict[str, int] = {}
    for row in db.query(models.AuthoringAttempt).filter(
        models.AuthoringAttempt.owner_id == owner_id
    ).all():
        attempts_by_key[row.ticket_key] = attempts_by_key.get(row.ticket_key, 0) + 1

    # Which work items the driver is mid-run on. One query for the whole board,
    # for the same reason as the counts above.
    running_by_key = authoring.running_attempts(db, owner_id=owner_id)

    cards: list[schemas.TaskCard] = []
    for item in items:
        links = links_by_key.get(item.key)
        matched = _matching_reviews(reviews, item.key, item, links)
        pr_idents = {(r.repo, r.pr_number) for r in matched}

        # Pull requests known only from the analysis log, before any review
        # was requested. Reviewed PRs already carry richer rows, so those win.
        logged_prs = prs_by_key.get(item.key, set())
        pr_idents |= logged_prs

        # Pull requests GitHub links to this issue that Locus has never seen --
        # opened moments ago, or attached in the panel before any webhook. They
        # belong on the card: a PR the board omits reads as work not started.
        linked_prs = {(pr.repo, pr.pr_number) for pr in (links.pull_requests if links else [])}
        pr_idents |= linked_prs

        card_merged_idents = set(system_merged_idents)
        if links:
            for pr in links.pull_requests:
                if (pr.merged or pr.state == "merged") and pr.repo and pr.pr_number:
                    card_merged_idents.add((pr.repo, pr.pr_number))

        for r in matched:
            if (
                (r.repo, r.pr_number) in card_merged_idents
                and r.state != schemas.ReviewState.merged.value
                and r.state != schemas.ReviewState.changes_requested.value
            ):
                r.state = schemas.ReviewState.merged.value
                r.pending_asks = None
                try:
                    db.commit()
                except Exception:
                    db.rollback()

        qa = next(
            (
                thread for thread in qa_threads
                if _matches_qa(thread, pr_idents, item.key)
            ),
            None,
        )
        has_qa_event = bool(pr_idents & qa_event_prs or item.key in qa_event_tickets)
        analyzed = bool(pr_idents & analyzed_prs)

        if links is not None:
            _persist_links(
                db, owner_id=owner_id, item=item, links=links, reviews=matched
            )

        branches = links.branches if links else []

        # The mode this work item would actually run in, resolved through the
        # same chain the worker uses, against the registration of the repo the
        # work is happening in. Reading it here rather than in the UI is what
        # keeps the chip and the run from disagreeing.
        item_settings = resolve_settings(
            db,
            owner_id,
            _registration_for(db, owner_id, pr_idents, branches),
            ticket_key=item.key,
        )
        attempts = attempts_by_key.get(item.key, 0)

        stage, had_changes = _derive_stage(
            matched, qa, analyzed,
            has_pr=bool(pr_idents),
            has_branch=bool(branches),
            has_attempt=bool(attempts),
            merged_idents=card_merged_idents,
            has_qa_event=has_qa_event,
            item_status=item.status,
        )
        if item.key in done_keys:
            stage = schemas.TaskStage.done

        # A run happening right now outranks the derived stage only while
        # nothing further along exists. A rework runs against a pull request
        # that is already in review, and reporting that card as "writing it"
        # would walk it backwards -- the same rule that keeps a linked branch
        # below every pull-request stage.
        if item.key in running_by_key and stage in (
            schemas.TaskStage.assigned,
            schemas.TaskStage.authoring,
        ):
            stage = schemas.TaskStage.authoring
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
        # Titles and URLs for anything GitHub linked, so a PR Locus has not
        # analyzed still renders as itself rather than as a bare number.
        linked_meta = {
            (pr.repo, pr.pr_number): pr
            for pr in (links.pull_requests if links else [])
        }
        for repo, number in sorted((logged_prs | linked_prs) - reviewed_idents):
            meta = linked_meta.get((repo, number))
            pull_requests.append(schemas.TaskPullRequest(
                repo=repo,
                pr_number=number,
                url=(meta.url if meta and meta.url else
                     f"https://github.com/{repo}/pull/{number}"),
                title=meta.title if meta else None,
            ))

        # The report link, resolved the way `find_report` resolves it: by
        # ticket first, then by any pull request on this work item. Read from
        # the two maps loaded once above rather than queried per card.
        doc_url = docs_by_ticket.get(item.key)
        if doc_url is None:
            for pr in pull_requests:
                doc_url = docs_by_pr.get((pr.repo, pr.pr_number))
                if doc_url:
                    break

        card_items = [
            i for i in (task.items if task else [])
            if not (
                stage in (schemas.TaskStage.testing, schemas.TaskStage.merged, schemas.TaskStage.done)
                and i.kind == schemas.WorklistKind.approved_not_merged
            )
        ]
        card_needs_you = any(i.blocked_on_you for i in card_items)

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
            description=item.body,
            stage=stage,
            stages=_build_stages(
                stage, had_changes, matched, branches,
                autonomous=item_settings.authoring_mode == "autonomous",
                attempts=attempts,
            ),
            pull_requests=pull_requests,
            linked_branches=branches,
            doc_url=doc_url,
            items=card_items,
            needs_you=card_needs_you,
            blocked_reason=_blocked_reason(card_items) if card_items else None,
            age_hours=task.age_hours if task else 0.0,
            round_number=max((r.round_number for r in matched), default=1),
            authoring_mode=schemas.AuthoringMode(item_settings.authoring_mode),
            authoring_source=item_settings.sources.get("authoring_mode", "unset"),
            handed_back=item_settings.handed_back,
            handed_back_reason=item_settings.handed_back_reason,
            authoring_attempts=attempts,
            authoring_active=item.key in running_by_key,
            authoring_started_at=(
                running_by_key[item.key].created_at
                if item.key in running_by_key else None
            ),
        ))

    # Needs-you first, then staleness -- a task that has been round-tripping
    # for a week is the signal worth surfacing, not the one with the worst
    # findings. Severity ranks findings; this is a list of conversations.
    cards.sort(key=lambda c: (not c.needs_you, -c.age_hours, -c.round_number))

    # A finished card is never "needs you" and never in flight, whatever the
    # attention rules computed: the work is done, and leaving it in the queue
    # would ask somebody to act on a closed ticket.
    return schemas.TaskBoard(
        needs_you=[c for c in cards if c.needs_you and c.key not in done_keys],
        in_flight=[
            c for c in cards if not c.needs_you and c.key not in done_keys
        ],
        recently_done=[c for c in cards if c.key in done_keys],
        total=len([c for c in cards if c.key not in done_keys]),
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

    qa_clauses = [models.QAThread.owner_id == owner_id]
    if pr_idents:
        for r, p in pr_idents:
            qa_clauses.append(
                (models.QAThread.repo == r) & (models.QAThread.pr_number == p)
            )
    qa = next(
        (
            thread
            for thread in db.query(models.QAThread)
            .filter(or_(*qa_clauses))
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


def _registration_for(
    db: Session,
    owner_id: int,
    pr_idents: set,
    branches: list[schemas.LinkedBranch],
) -> models.RepoWebhook | None:
    """
    The repo registration behind a work item, from wherever the work is.

    A pull request names its repo; before one exists a linked branch does. A
    work item with neither has no repo settings to resolve against, and falls
    back to the account defaults -- which is correct, not a gap.

    **Scoped to the owner, with no fallback past it.** A retry that took any
    *enabled* registration for the repo was here, from the same workaround as
    the ones in `report_sync.find_report` and the board's authoring endpoint: a
    board running as one account while the registrations belonged to another.
    It is not only a cross-user read -- `resolve_settings` turns a registration
    into `source_path`, `prepare_command` and `test_command`, so a card
    rendered from a borrowed row shows another account's mode, and a run
    started from that card executes their shell commands against their source
    tree. An unregistered repo resolving to this account's own defaults is the
    correct answer, and is what the paragraph above already says.
    """
    repo = None
    if pr_idents:
        repo = sorted(pr_idents)[0][0]
    elif branches:
        repo = next((b.repo for b in branches if b.repo), None)

    if not repo:
        return None

    reg = (
        db.query(models.RepoWebhook)
        .filter(
            models.RepoWebhook.repo == repo,
            models.RepoWebhook.owner_id == owner_id,
        )
        .first()
    )
    return reg
