"""
Finding a pull request's work item before the analysis has run.

The pipeline records `ticket_keys` on the review row once an analysis
completes, and every later run on that pull request reads it back. That works
for the second push to a PR and every one after.

It does not work for the *first* run on a pull request, which is exactly the
case that matters when a ticket is reopened. QA rejects a merged change, the
ticket goes back to In Progress, and the fix arrives on a new branch as a new
pull request. That PR has no review row and no recorded keys, so it started
cold: none of the Slack discussion, none of the earlier rounds' review asks,
and -- worst -- no knowledge of why QA rejected it. The one piece of context
that says what to get right this time was the piece it could not see.

The key is recoverable without any of that, from the PR's own branch, title
and body, which is where `linking.extract_ticket_keys` already looks. Once the
key is known, the sibling pull requests on the same work item are a lookup, and
`comms_log`'s ticket-scoped reads already return their history.

**A sibling's key is never invented.** If the branch and title name no ticket,
this returns None and the run proceeds as a genuinely new piece of work.
Guessing a work item from a similar title would attach one team's rejection
history to another's pull request, which is worse than starting cold.
"""

import json
import logging

from sqlalchemy.orm import Session

from app import models, schemas
from app.services import linking

logger = logging.getLogger(__name__)


def resolve_key(
    db: Session,
    *,
    owner_id: int,
    repo: str,
    pr_number: int,
    title: str | None = None,
    branch: str | None = None,
    body: str | None = None,
) -> str | None:
    """
    The work item this pull request belongs to.

    Prefers what a previous run on this same pull request recorded, since that
    came from the full analysis. Falls back to reading the branch, title and
    body, which is all that exists on a first run.

    Returns None when nothing names a work item -- the caller should treat the
    pull request as new work rather than attaching it to a guess.
    """
    recorded = (
        db.query(models.PRReview.ticket_keys)
        .filter(
            models.PRReview.repo == repo,
            models.PRReview.pr_number == pr_number,
            models.PRReview.owner_id == owner_id,
        )
        .scalar()
    )
    if recorded:
        first = recorded.splitlines()[0].strip()
        if first:
            return first

    for key in linking.extract_ticket_keys(title, branch, body):
        return key

    return None


def sibling_reviews(
    db: Session,
    *,
    owner_id: int,
    ticket_key: str,
    exclude_pr: int | None = None,
    repo: str | None = None,
) -> list[models.PRReview]:
    """
    Other pull requests recorded against the same work item.

    Matched on the stored `ticket_keys` text, which holds one key per line, so
    a PR carrying several work items is found by any of them. Deliberately not
    scoped to one repository by default: a fix can land in a different repo
    from the change that broke it.

    Ordered oldest first, so "the previous attempt" is the last entry.
    """
    rows = (
        db.query(models.PRReview)
        .filter(
            models.PRReview.owner_id == owner_id,
            models.PRReview.ticket_keys.isnot(None),
        )
        .order_by(models.PRReview.pr_number)
        .all()
    )

    needle = ticket_key.strip().lower()
    matches = []
    for row in rows:
        if exclude_pr is not None and row.pr_number == exclude_pr:
            continue
        if repo is not None and row.repo != repo:
            continue
        keys = {
            line.strip().lower()
            for line in (row.ticket_keys or "").splitlines()
            if line.strip()
        }
        if needle in keys:
            matches.append(row)

    return matches


def previous_attempt(
    db: Session,
    *,
    owner_id: int,
    ticket_key: str,
    exclude_pr: int,
    repo: str | None = None,
) -> models.PRReview | None:
    """
    The most recent earlier pull request on this work item, if any.

    "Most recent" is by pull request number rather than timestamp: numbers are
    monotonic per repository and a review row's timestamp moves whenever the
    row is touched, so a stale PR that was merely re-read would otherwise
    outrank the one that actually came last.
    """
    siblings = sibling_reviews(
        db, owner_id=owner_id, ticket_key=ticket_key,
        exclude_pr=exclude_pr, repo=repo,
    )
    return siblings[-1] if siblings else None


def qa_rejection(
    db: Session,
    *,
    owner_id: int,
    ticket_key: str,
) -> models.QAThread | None:
    """
    An unresolved QA rejection against this work item.

    This is the reason a reopened ticket's next pull request needs to know its
    lineage at all. A QA thread is created when the merge notification goes
    out and marked resolved when QA says it works, so an unresolved one whose
    keys include this work item means the last attempt was rejected and this
    change is the retry.

    Returns the newest unresolved thread, or None.
    """
    threads = (
        db.query(models.QAThread)
        .filter(
            models.QAThread.owner_id == owner_id,
            models.QAThread.resolved == 0,
        )
        .order_by(models.QAThread.created_at.desc())
        .all()
    )

    needle = ticket_key.strip().lower()
    for thread in threads:
        try:
            stored = json.loads(thread.ticket_keys_json or "[]")
        except (ValueError, TypeError):
            continue
        if any(str(k).strip().lower() == needle for k in stored):
            return thread

    return None


def is_retry(
    db: Session,
    *,
    owner_id: int,
    repo: str,
    pr_number: int,
    ticket_key: str | None,
) -> tuple[bool, models.PRReview | None]:
    """
    Whether this pull request is another attempt at work already tried.

    True when the work item has an earlier pull request that merged, since
    that is the shape a reopened ticket takes: the first attempt merged, QA or
    a stakeholder rejected it, and the fix arrives as a new pull request.

    An earlier PR that is still open is a sibling, not a previous attempt --
    two pull requests being worked in parallel on one ticket is ordinary, and
    calling the second a retry would put a misleading history in front of the
    reviewer.

    Returns:
        (is a retry, the pull request being retried)
    """
    if not ticket_key:
        return False, None

    previous = previous_attempt(
        db, owner_id=owner_id, ticket_key=ticket_key, exclude_pr=pr_number,
    )
    if previous is None:
        return False, None

    if previous.state != schemas.ReviewState.merged.value:
        return False, None

    return True, previous
