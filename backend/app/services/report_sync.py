"""
Keeping the report document current as the flow moves.

The document is written during an analysis, which is the only step that reads
the code. But the events worth reading about mostly happen afterwards: the
reviewer's verdict in their own words, the round trip that followed, the
testing team's answer. None of those re-run an analysis, so without this the
record froze at the last push -- and the link sent to the reviewer described a
round that had already moved on.

One document per pull request, rewritten in place. A new file per event would
scatter the history and, worse, leave every link already sent pointing at a
stale snapshot. The same reasoning as the PR comment's hidden marker: this is a
living record, not an append-only stream.

The analysis body is reused from the last completed run, since that is still
the truth about the code. What is re-read on every call is the history around
it: the review rounds, and every message sent and received.
"""

import json
import logging

from sqlalchemy.orm import Session

from app import models, schemas
from app.services import comms_log, work_item

logger = logging.getLogger(__name__)


def find_report(
    db: Session,
    *,
    owner_id: int,
    repo: str,
    pr_number: int,
    ticket_key: str | None = None,
    adopt: bool = False,
) -> models.PRReport | None:
    """
    The document row for this work, by ticket first and pull request second.

    The two-step lookup is what makes the change from per-PR to per-task safe
    on an existing install. Rows written before this existed are keyed by pull
    request with no ticket; finding them only by ticket would hand every one of
    those a second document and leave the link already sent pointing at the
    older, now-frozen one -- the exact failure this design exists to avoid.

    Args:
        adopt: When true and a pull-request-keyed row is found for work that
            does have a ticket, claim it for the ticket. The first pull request
            on a task keeps its document and that document becomes the task's,
            so the second pull request finds it rather than starting over.
            Callers that only read (rather than write the document) leave this
            off so a lookup never mutates.
    """
    if ticket_key:
        by_ticket = (
            db.query(models.PRReport)
            .filter(
                models.PRReport.owner_id == owner_id,
                models.PRReport.ticket_key == ticket_key,
            )
            .order_by(models.PRReport.created_at)
            .first()
        )
        if by_ticket is not None:
            return by_ticket

    by_pr = (
        db.query(models.PRReport)
        .filter(
            models.PRReport.owner_id == owner_id,
            models.PRReport.repo == repo,
            models.PRReport.pr_number == pr_number,
        )
        .first()
    )

    if by_pr is not None and ticket_key and adopt and not by_pr.ticket_key:
        by_pr.ticket_key = ticket_key
        try:
            db.commit()
        except Exception as e:
            # The document is fine either way; failing here would discard a
            # working lookup over bookkeeping.
            logger.warning("Could not claim report for %s: %s", ticket_key, e)
            db.rollback()

    return by_pr


def document_url(
    db: Session,
    *,
    owner_id: int,
    repo: str,
    pr_number: int,
    ticket_key: str | None = None,
) -> str | None:
    """
    This work item's report URL, without touching Google.

    Read from the report row: the document is rewritten in place, so its id is
    stable and one row is the truth about which document this is.
    """
    report = find_report(
        db, owner_id=owner_id, repo=repo, pr_number=pr_number,
        ticket_key=ticket_key,
    )
    if report is None:
        return None

    return f"https://docs.google.com/document/d/{report.document_id}/edit"


def _last_analysis(
    db: Session, *, owner_id: int, repo: str, pr_number: int
) -> schemas.PRAnalysisResult | None:
    """The most recent completed run's result, or None if there is none."""
    previous = (
        db.query(models.PRJob)
        .filter(
            models.PRJob.owner_id == owner_id,
            models.PRJob.repo == repo,
            models.PRJob.pr_number == pr_number,
            models.PRJob.status == schemas.PRJobStatus.completed.value,
            models.PRJob.result_json.isnot(None),
        )
        .order_by(models.PRJob.created_at.desc())
        .first()
    )
    if previous is None:
        return None

    try:
        return schemas.PRAnalysisResult(**json.loads(previous.result_json))
    except Exception as e:
        # A result stored under an older schema must not break the document it
        # was only meant to fill in.
        logger.warning("Could not read the last analysis for the report: %s", e)
        return None


async def refresh(
    db: Session,
    *,
    owner_id: int,
    repo: str,
    pr_number: int,
    integration_configs: dict[str, dict],
) -> str | None:
    """
    Rewrite the report with everything known right now.

    Safe to call from any event. Does nothing and returns the existing URL when
    there is no document yet -- the first one is created by an analysis, which
    is the only step that has the code to describe.

    Returns:
        The document URL, or None when this pull request has no report. Failure
        is swallowed and the stored URL returned: the notification this
        decorates is worth sending whether or not the document is current.
    """
    # Resolved before the lookup so a later pull request on the same task finds
    # the task's document rather than concluding it has none.
    ticket_key = work_item.resolve_key(
        db, owner_id=owner_id, repo=repo, pr_number=pr_number
    )

    stored_url = document_url(
        db, owner_id=owner_id, repo=repo, pr_number=pr_number,
        ticket_key=ticket_key,
    )
    docs_config = (
        integration_configs.get("docs") or integration_configs.get("drive")
    )
    if stored_url is None or not docs_config:
        return stored_url

    result = _last_analysis(
        db, owner_id=owner_id, repo=repo, pr_number=pr_number
    )
    if result is None:
        return stored_url

    try:
        # Imported here rather than at module scope: pr_agent is a heavy import
        # and this module is pulled in by the webhook router at startup.
        from app.services.pr_agent import export_to_google_doc

        review_row = (
            db.query(models.PRReview)
            .filter(
                models.PRReview.repo == repo,
                models.PRReview.pr_number == pr_number,
                models.PRReview.owner_id == owner_id,
            )
            .first()
        )
        events = comms_log.timeline(
            db, owner_id=owner_id, repo=repo, pr_number=pr_number,
            ticket_key=ticket_key,
        )
        return await export_to_google_doc(
            result, docs_config, db=db, user_id=owner_id,
            timeline_events=events, review_row=review_row,
            report_ticket_key=ticket_key,
        )
    except Exception as e:
        logger.warning("Could not refresh the report document: %s", e)
        return stored_url


def _ticket_brief(
    *,
    key: str,
    title: str,
    url: str | None,
    status: str | None,
    assignee: str | None,
    priority: str | None,
    description: str | None,
    events: list,
) -> str:
    """
    The document body for work that has no pull request yet.

    Deliberately not `full_report.render`: that describes an analysis -- a
    diff, two scan passes, review rounds -- and none of it exists yet. Rendering
    it here would produce a document that is mostly empty headings, which reads
    as a broken feature rather than as work not yet started.

    What does exist is the part people most need and most often cannot find:
    the requirement as the person who filed it stated it, and whatever has
    already been said about it.
    """
    heading = f"{key} — {title}"
    lines: list[str] = [
        heading,
        "=" * min(len(heading), 78),
        "",
    ]

    meta = [d for d in (status, assignee, priority) if d]
    if meta:
        lines.append(" · ".join(meta))
    if url:
        lines.append(url)
    lines.append("")

    lines.append("DESCRIPTION")
    lines.append("-" * 40)
    if description and description.strip():
        lines.append(description.strip())
    else:
        # Said plainly rather than left blank: an empty section reads as a
        # failure to fetch, where this is a fact about the ticket.
        lines.append("The ticket has no description.")
    lines.append("")

    discussion = [
        e for e in events
        if e.channel == "slack" and e.direction == "received" and e.body
    ]
    if discussion:
        lines.append("DISCUSSION SO FAR")
        lines.append("-" * 40)
        for event in discussion:
            who = event.participant or "someone"
            where = f"#{event.target}" if event.target else "slack"
            lines.append(f"{who} in {where}:")
            for line in event.body.strip().splitlines():
                lines.append(f"  {line}")
            if event.permalink:
                lines.append(f"  {event.permalink}")
            lines.append("")

    lines.append("")
    lines.append(
        "No pull request has been opened for this work yet. This document is "
        "rewritten in place as the work moves -- the analysis, the review "
        "rounds, and the testing outcome are added here as they happen."
    )

    return "\n".join(lines)


async def ensure_for_ticket(
    db: Session,
    *,
    owner_id: int,
    key: str,
    title: str,
    integration_configs: dict[str, dict],
    url: str | None = None,
    status: str | None = None,
    assignee: str | None = None,
    priority: str | None = None,
    description: str | None = None,
    repo: str | None = None,
    pr_number: int | None = None,
) -> str | None:
    """
    Create this work item's document if it does not have one yet.

    The document belongs to the work item, so it can exist before any pull
    request does -- which is the whole window in which someone is deciding
    what to build, and the window in which a written requirement is most
    useful. An analysis later rewrites the same document in place; because
    `find_report` resolves by ticket, it finds this one rather than starting
    a second.

    Idempotent. Returns the existing URL untouched when there already is one,
    so this is safe to call whenever a task is opened.

    Returns None when Docs is not connected or the document could not be
    created -- the caller renders the task without a link rather than failing.

    Takes the work item's fields rather than a schema object because the two
    callers hold different shapes of the same thing: the board holds a
    `TaskCard`, the assigned-work query an `AssignedItem`, and neither is
    convertible to the other without inventing fields.

    Args:
        repo, pr_number: A pull request already on this work item, if there is
            one. Only used to find and claim a document written before
            documents were keyed by ticket, so a task that started life as a
            pull request keeps the link that was already sent out.
    """
    existing = find_report(
        db, owner_id=owner_id, repo=repo or "", pr_number=pr_number or 0,
        ticket_key=key, adopt=True,
    )
    if existing is not None:
        return f"https://docs.google.com/document/d/{existing.document_id}/edit"

    docs_config = (
        integration_configs.get("docs") or integration_configs.get("drive")
    )
    if not docs_config:
        return None

    events = comms_log.ticket_timeline(db, owner_id=owner_id, ticket_key=key)

    try:
        # Imported here rather than at module scope: pr_agent pulls in the
        # whole agent stack, and this module is imported by the router at
        # startup.
        from app.services.pr_agent import create_google_doc

        document_id = await create_google_doc(
            docs_config,
            title=f"{key} — {title}"[:200],
            body=_ticket_brief(
                key=key, title=title, url=url, status=status,
                assignee=assignee, priority=priority, description=description,
                events=events,
            ),
            db=db,
            user_id=owner_id,
        )
    except Exception as e:
        # A task is worth showing without its document; the document is not
        # worth failing the task board for.
        logger.warning("Could not create document for %s: %s", key, e)
        return None

    if not document_id:
        return None

    try:
        db.add(models.PRReport(
            repo=repo,
            pr_number=pr_number,
            ticket_key=key,
            document_id=document_id,
            owner_id=owner_id,
        ))
        db.commit()
    except Exception as e:
        logger.warning("Could not record document for %s: %s", key, e)
        db.rollback()

    return f"https://docs.google.com/document/d/{document_id}/edit"
