"""
Whether each integration is actually working.

The background loops swallow their own failures, deliberately: a dead Jira must
not take the analysis down with it, and a Gmail outage must not stop the review
loop. The cost is that a persistently failing integration is invisible. The QA
poller logs a Gmail failure at debug level and moves on, so a token that
expired on Monday is still quietly failing on Friday and the only symptom is
that QA replies stopped arriving -- which looks like nobody replying.

This records the outcome of each attempt so the failure has somewhere to
surface. It is deliberately not an alerting system: it stores the last success
and the last failure per service, and the settings page reads it.

**Recording never fails the work it describes.** Same rule as `comms_log`: a
poll that genuinely succeeded must not be reported as failed because the record
could not be written. Every helper here swallows its own errors.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app import models

logger = logging.getLogger(__name__)

# Consecutive failures before a service is called failing rather than flaky.
# One failed poll is normal -- a token refresh races, a request times out.
# Three in a row is a condition someone has to act on.
UNHEALTHY_AFTER = 3


def record_success(db: Session, *, owner_id: int, service: str) -> None:
    """
    Note that a call to this service worked.

    Clears the failure streak: a service that succeeds is healthy regardless of
    what it did an hour ago.
    """
    try:
        row = _row(db, owner_id=owner_id, service=service)
        row.last_success_at = datetime.now(UTC)
        row.consecutive_failures = 0
        row.last_error = None
        db.commit()
    except Exception:
        db.rollback()
        logger.debug("Could not record health success for %s", service)


def record_failure(
    db: Session, *, owner_id: int, service: str, error: str
) -> None:
    """
    Note that a call to this service failed, and why.

    The message is stored verbatim and truncated. It is shown to the person who
    owns the credential, who is the one who can fix an expired token.
    """
    try:
        row = _row(db, owner_id=owner_id, service=service)
        row.last_failure_at = datetime.now(UTC)
        row.consecutive_failures = (row.consecutive_failures or 0) + 1
        row.last_error = (error or "")[:1000]
        db.commit()
    except Exception:
        db.rollback()
        logger.debug("Could not record health failure for %s", service)


def _row(db: Session, *, owner_id: int, service: str) -> models.IntegrationHealth:
    """The health row for one service, created on first use."""
    row = (
        db.query(models.IntegrationHealth)
        .filter(
            models.IntegrationHealth.owner_id == owner_id,
            models.IntegrationHealth.service_name == service,
        )
        .first()
    )
    if row is None:
        row = models.IntegrationHealth(owner_id=owner_id, service_name=service)
        db.add(row)
        db.flush()
    return row


def summary(db: Session, *, owner_id: int) -> list[dict]:
    """
    Health of every service this user has an attempt recorded for.

    A service with no row has never been called, which is not the same as
    healthy and not the same as broken -- it is simply absent from this list,
    and the settings page shows connection state for those.
    """
    rows = (
        db.query(models.IntegrationHealth)
        .filter(models.IntegrationHealth.owner_id == owner_id)
        .all()
    )

    return [
        {
            "service": row.service_name,
            "healthy": (row.consecutive_failures or 0) < UNHEALTHY_AFTER,
            "consecutive_failures": row.consecutive_failures or 0,
            "last_success_at": row.last_success_at,
            "last_failure_at": row.last_failure_at,
            "last_error": row.last_error,
        }
        for row in sorted(rows, key=lambda r: r.service_name)
    ]

# Which third party each pipeline stage actually talks to.
#
# The stage list is the one place every integration call already reports its
# own outcome, with a stable key and a done/failed/skipped state. Recording
# from it means a new stage is instrumented by adding one line here, rather
# than by remembering to wrap its call site -- and the failure mode of
# forgetting is a service missing from the panel, not a wrong claim about it.
STAGE_SERVICES: dict[str, str] = {
    "read_pr": "github",
    "github_issues": "github",
    "pr_comment": "github",
    "inline_comments": "github",
    "jira": "jira",
    "slack_search": "slack",
    "slack_post": "slack",
    "docs_read": "docs",
    "docs_export": "docs",
}


def record_stages(db: Session, *, owner_id: int, stages) -> None:
    """
    Record one run's integration outcomes from its pipeline stages.

    Only `done` and `failed` are recorded. A `skipped` stage is a service that
    was never attempted -- no credential, nothing to search -- and the rule
    that absence means "never attempted" is what makes the panel readable.
    Writing a success for it would be a claim nothing supports; writing a
    failure would be worse.

    A service that both succeeded and failed within one run is recorded as
    failed, since the failure is the part someone has to act on.

    Never raises. Same rule as the rest of this module: a run that did its work
    must not be reported as broken because the record could not be written.
    """
    try:
        outcomes: dict[str, tuple[bool, str]] = {}
        for stage in stages or []:
            service = STAGE_SERVICES.get(getattr(stage, "key", None))
            if not service:
                continue
            state = getattr(stage, "state", None)
            state = getattr(state, "value", state)
            if state == "failed":
                outcomes[service] = (
                    False, str(getattr(stage, "detail", "") or "failed")
                )
            elif state == "done" and service not in outcomes:
                outcomes[service] = (True, "")

        for service, (ok, detail) in outcomes.items():
            if ok:
                record_success(db, owner_id=owner_id, service=service)
            else:
                record_failure(
                    db, owner_id=owner_id, service=service, error=detail
                )
    except Exception:
        logger.debug("Could not record stage health", exc_info=True)
