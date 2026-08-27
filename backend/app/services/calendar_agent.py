"""
The calendar agent: the scheduler, running on its own rather than on request.

The solver, the parsers and the endpoints were all built already and are
entirely request-driven -- plan, review, apply. This adds the trigger. The
original objection to firing it automatically was that *"proposing calendar
changes nobody asked for"* needs somewhere to deliver the proposal, which is a
notification problem rather than a scheduling one; `schedule_proposals` plus the
board surface is that somewhere, and `POST /schedule/apply` was already the
human-confirm step.

**The agent never holds a pipeline message.** Delaying a review request until a
focus block ends manufactures the exact silence that makes an approved pull
request look like a broken feature.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app import models, schemas
from app.services.scheduler import (
    SchedulingContext,
    find_conflicts,
    plan_for_new_event,
)

logger = logging.getLogger(__name__)

# In minutes, not seconds. The ceiling on how fast a calendar changes is far
# below the ceiling on how fast Google rate-limits.
SWEEP_INTERVAL_MINUTES = int(os.getenv("LOCUS_CALENDAR_SWEEP_MINUTES") or 30)
LOOKAHEAD_DAYS = int(os.getenv("LOCUS_CALENDAR_LOOKAHEAD_DAYS") or 14)


def get_settings(db: Session, owner_id: int) -> models.TimeAgentSettings:
    """
    This user's calendar agent settings, defaulted but not persisted.

    An unsaved default row is returned rather than created, so reading a
    setting never writes one -- the same reason the task board does not create
    a report document per assigned item on a refresh.
    """
    row = db.query(models.TimeAgentSettings).filter(
        models.TimeAgentSettings.owner_id == owner_id
    ).first()
    if row is not None:
        return row

    # A transient instance reads back `None` for every column, because
    # SQLAlchemy applies `default=` at INSERT rather than at construction. Set
    # them explicitly, or "never saved" and "saved with everything off" would
    # be told apart by a NoneType error somewhere downstream.
    return models.TimeAgentSettings(
        owner_id=owner_id,
        enabled=0,
        auto_apply=0,
        auto_reply_invites=0,
        auto_reply_busy=0,
        working_hours_start="09:30",
        working_hours_end="18:30",
        protect_focus_blocks=1,
    )


def enabled_users(db: Session) -> list[models.TimeAgentSettings]:
    """Everyone who turned the agent on. Off by default, so usually nobody."""
    return db.query(models.TimeAgentSettings).filter(
        models.TimeAgentSettings.enabled == 1
    ).all()


def store_proposal(
    db: Session,
    *,
    owner_id: int,
    proposal: schemas.ScheduleProposal,
) -> models.ScheduleProposalRecord | None:
    """
    Record a proposal for a human to confirm, unless it changes nothing.

    A proposal that moves nothing is not stored. The board would otherwise
    accumulate a "nothing needs to change" card every sweep, which is the same
    failure as a "0 resolved, 0 new" findings line on every push: it trains
    people to skip the section that matters.

    An identical pending proposal is not stored twice either -- the sweep runs
    every half hour and the conflict it found at nine is the same conflict at
    half past.
    """
    if not proposal.moves and not proposal.additions and not proposal.blocked:
        return None

    body = proposal.model_dump_json()

    existing = db.query(models.ScheduleProposalRecord).filter(
        models.ScheduleProposalRecord.owner_id == owner_id,
        models.ScheduleProposalRecord.state == "pending",
        models.ScheduleProposalRecord.trigger == proposal.trigger,
    ).first()
    if existing is not None:
        if existing.proposal_json == body:
            return existing
        # The same conflict, resolved differently because the calendar moved.
        # Superseded rather than duplicated, so the board shows one live plan.
        existing.state = "superseded"
        existing.resolved_at = datetime.now(UTC)

    record = models.ScheduleProposalRecord(
        owner_id=owner_id,
        trigger=proposal.trigger,
        proposal_json=body,
        summary=proposal.summary,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def pending_proposals(db: Session, owner_id: int) -> list[models.ScheduleProposalRecord]:
    return db.query(models.ScheduleProposalRecord).filter(
        models.ScheduleProposalRecord.owner_id == owner_id,
        models.ScheduleProposalRecord.state == "pending",
    ).order_by(models.ScheduleProposalRecord.created_at.desc()).all()


def load_proposal(record: models.ScheduleProposalRecord) -> schemas.ScheduleProposal:
    """
    The stored plan, so applying it runs what was shown.

    Recomputing at apply time would silently execute a different plan from the
    one the person approved -- the calendar has moved since, and that is
    exactly why they were asked.
    """
    return schemas.ScheduleProposal.model_validate(json.loads(record.proposal_json))


def sweep_user(
    db: Session,
    settings: models.TimeAgentSettings,
    events: list[schemas.ScheduledEvent],
    timezone: str,
) -> list[models.ScheduleProposalRecord]:
    """
    Look for conflicts on one calendar and propose a resolution for each.

    Reuses `find_conflicts` and `plan_for_new_event`, both already written and
    tested. The solver is plain Python and stays that way: a model asked to
    rearrange a calendar produces plausible-looking schedules with overlaps and
    missed deadlines.
    """
    records: list[models.ScheduleProposalRecord] = []
    seen: set[str] = set()

    for first, second in find_conflicts(events):
        # The later event is treated as the one that has to fit, which matches
        # what `plan_for_new_event` is written to answer.
        newer = second if second.start >= first.start else first
        if newer.event_id in seen:
            continue
        seen.add(newer.event_id)

        proposal = plan_for_new_event(
            newer, SchedulingContext(timezone=timezone, events=events)
        )
        proposal.trigger = f"Double-booked: {first.title} and {second.title}"

        record = store_proposal(db, owner_id=settings.owner_id, proposal=proposal)
        if record is not None:
            records.append(record)

    return records


async def sweep_once() -> int:
    """
    One pass over every user who enabled the agent.

    Each user's failure is swallowed: one broken Google token must not stop the
    sweep for everybody else, the same rule the other loops follow. The
    breakage surfaces through `integration_health`, which is what it is for.
    """
    from app.database import SessionLocal
    from app.dependencies import get_integration_configs
    from app.services import calendar as calendar_service

    proposed = 0
    db = SessionLocal()
    try:
        for settings in enabled_users(db):
            user = db.query(models.User).filter(
                models.User.id == settings.owner_id
            ).first()
            if user is None:
                continue

            try:
                configs = get_integration_configs(db, user.id)
                if "calendar" not in configs:
                    continue

                # Bind this user's credentials before touching the service.
                # Tool objects are module singletons, so a module-level
                # credential dict would let one user's sweep read another's
                # calendar.
                calendar_service.get_calendar_tools(
                    credentials=configs["calendar"].get("credentials", {}),
                    timezone=user.timezone,
                )
                events = _load_events(db, user)
                proposed += len(
                    sweep_user(db, settings, events, user.timezone or "Asia/Kolkata")
                )
            except Exception:
                logger.exception(
                    "Calendar sweep failed for user %s", settings.owner_id
                )
    finally:
        db.close()

    return proposed


def _load_events(
    db: Session, user: models.User
) -> list[schemas.ScheduledEvent]:
    """
    The next fortnight from the primary calendar, in the solver's shape.

    Parsed through the same `events_from_raw` the endpoints use, so the sweep
    and a person clicking Conflicts cannot disagree about the same calendar.

    Note the known gap this inherits: only the primary calendar is read, so
    conflicts on secondary or shared calendars are invisible to the agent
    exactly as they are to the request-driven endpoints.
    """
    from app.routers.schedule import events_from_raw
    from app.services import calendar as calendar_service

    raw, error = calendar_service.fetch_events("today", f"in {LOOKAHEAD_DAYS} days")
    if error:
        raise RuntimeError(error)

    return events_from_raw(db, user, raw)


async def resolve_slack_member_id(slack_config: dict) -> str | None:
    """
    This account's Slack member id, via `auth.test`.

    Resolved once and stored, because a mention arrives in message text as
    `<@U04AB…>` while `reviewer_contacts` stores handles -- different
    namespaces that never compare equal, which is why mention matching
    silently never fires without it.

    Returns None on any failure. The setting it feeds is one the save must not
    fail for: mention matching is a feature of the busy reply, not a
    prerequisite for configuring working hours.
    """
    token = slack_config.get("bot_token") or slack_config.get("api_key")
    if not token:
        return None

    try:
        import httpx

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                "https://slack.com/api/auth.test",
                headers={"Authorization": f"Bearer {token}"},
            )
        payload = response.json()
        return payload.get("user_id") if payload.get("ok") else None
    except Exception as exc:
        logger.debug("Could not resolve the Slack member id: %s", exc)
        return None
