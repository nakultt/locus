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
