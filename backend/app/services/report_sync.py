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
from app.services import comms_log

logger = logging.getLogger(__name__)


def document_url(
    db: Session, *, owner_id: int, repo: str, pr_number: int
) -> str | None:
    """
    This pull request's report URL, without touching Google.

    Read from the report row: the document is rewritten in place, so its id is
    stable and one row is the truth about which document this is.
    """
    report = (
        db.query(models.PRReport)
        .filter(
            models.PRReport.owner_id == owner_id,
            models.PRReport.repo == repo,
            models.PRReport.pr_number == pr_number,
        )
        .first()
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
    stored_url = document_url(
        db, owner_id=owner_id, repo=repo, pr_number=pr_number
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
            ticket_key=(
                result.context.ticket_keys[0]
                if result.context.ticket_keys else None
            ),
        )
        return await export_to_google_doc(
            result, docs_config, db=db, user_id=owner_id,
            timeline_events=events, review_row=review_row,
        )
    except Exception as e:
        logger.warning("Could not refresh the report document: %s", e)
        return stored_url
