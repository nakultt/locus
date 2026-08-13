"""
Scheduling Router
Propose and apply calendar rearrangements.

Planning and applying are separate endpoints on purpose. Moving a meeting sends
invite updates to every attendee, so a plan touching other people is shown to
the user first and applied only on their say-so.
"""

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.dependencies import get_current_user, get_integration_configs
from app.services import calendar as calendar_service
from app.services.datetimes import parse_datetime, resolve_timezone
from app.services.scheduler import SchedulingContext, find_conflicts, plan_for_new_event

logger = logging.getLogger(__name__)

router = APIRouter()


def _load_calendar(
    db: Session,
    user: models.User,
    days: int = 14,
) -> list[schemas.ScheduledEvent]:
    """
    Read the user's upcoming events into the solver's shape.

    Raises:
        HTTPException 400 if Calendar is not connected.
    """
    configs = get_integration_configs(db, user.id)
    if "calendar" not in configs:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google Calendar is not connected",
        )

    # Bind credentials for this task before touching the service.
    calendar_service.get_calendar_tools(
        credentials=configs["calendar"].get("credentials", {}),
        timezone=user.timezone,
    )

    raw, error = calendar_service.fetch_events("today", f"in {days} days")
    if error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not read the calendar: {error}",
        )

    tz = resolve_timezone(user.timezone)
    own_domain = user.email.split("@")[-1].lower() if user.email else ""

    events: list[schemas.ScheduledEvent] = []
    for item in raw:
        start_raw = (item.get("start") or {}).get("dateTime")
        end_raw = (item.get("end") or {}).get("dateTime")
        if not start_raw or not end_raw:
            # All-day entries have no time to reason about.
            continue

        try:
            start = datetime.fromisoformat(start_raw).astimezone(tz)
            end = datetime.fromisoformat(end_raw).astimezone(tz)
        except ValueError:
            continue

        attendees = item.get("attendees") or []
        external = any(
            own_domain
            and a.get("email", "").split("@")[-1].lower() != own_domain
            for a in attendees
        )

        events.append(schemas.ScheduledEvent(
            event_id=item.get("id", ""),
            title=item.get("summary", "(no title)"),
            start=start,
            end=end,
            attendee_count=max(1, len(attendees)),
            has_external_attendees=external,
        ))

    return events


@router.get(
    "/conflicts",
    summary="Overlapping events in the next two weeks",
)
async def list_conflicts(
    days: int = 14,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Find double-bookings the user may not have noticed."""
    events = _load_calendar(db, current_user, days)
    pairs = find_conflicts(events)

    return {
        "total_events": len(events),
        "conflicts": [
            {
                "first": {"title": a.title, "start": a.start, "id": a.event_id},
                "second": {"title": b.title, "start": b.start, "id": b.event_id},
            }
            for a, b in pairs
        ],
        "total_conflicts": len(pairs),
    }


@router.post(
    "/plan",
    response_model=schemas.ScheduleProposal,
    summary="Plan what would move to fit a new event",
)
async def plan_event(
    request: schemas.SchedulePlanRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> schemas.ScheduleProposal:
    """
    Work out which meetings would move to accommodate a new event.

    Changes nothing. The response says what it would do, and whether that needs
    approval because other people are involved.
    """
    start = parse_datetime(request.start, current_user.timezone)
    if start is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not understand the time '{request.start}'",
        )

    events = _load_calendar(db, current_user)

    new_event = schemas.ScheduledEvent(
        event_id="__proposed__",
        title=request.title,
        start=start,
        end=start + timedelta(minutes=request.duration_minutes),
        attendee_count=request.attendees,
    )

    return plan_for_new_event(
        new_event,
        SchedulingContext(timezone=current_user.timezone, events=events),
    )


@router.post(
    "/apply",
    summary="Apply a reviewed schedule plan",
)
async def apply_plan(
    request: schemas.ScheduleApplyRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """
    Carry out the moves in a plan the user has seen.

    Applied only when called explicitly -- the planning endpoint never writes.
    Each move is independent, so one failure does not abandon the rest.
    """
    configs = get_integration_configs(db, current_user.id)
    if "calendar" not in configs:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google Calendar is not connected",
        )

    tools = {
        t.name: t
        for t in calendar_service.get_calendar_tools(
            credentials=configs["calendar"].get("credentials", {}),
            timezone=current_user.timezone,
        )
    }

    applied: list[str] = []
    failed: list[str] = []

    for move in request.moves:
        try:
            result = tools["calendar_move_event"].invoke({
                "event_id": move.event_id,
                "new_start": move.to_start.isoformat(),
                "duration_minutes": move.duration_minutes,
            })
            (failed if str(result).startswith("Error") else applied).append(
                f"{move.title}: {result}"
            )
        except Exception as e:
            failed.append(f"{move.title}: {e}")

    for addition in request.additions:
        try:
            result = tools["calendar_create_event"].invoke({
                "title": addition.title,
                "start_datetime": addition.to_start.isoformat(),
            })
            (failed if str(result).startswith("Error") else applied).append(
                f"{addition.title}: {result}"
            )
        except Exception as e:
            failed.append(f"{addition.title}: {e}")

    return {"applied": applied, "failed": failed}
