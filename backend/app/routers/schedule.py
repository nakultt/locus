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
from app.services.scheduler import (
    SchedulingContext,
    find_conflicts,
    plan_for_deadline,
    plan_for_new_event,
)

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

    # A stored override always beats the attendee-count heuristic.
    overrides = {
        c.event_id: schemas.EventClass(c.event_class)
        for c in db.query(models.EventConstraint).filter(
            models.EventConstraint.owner_id == user.id
        ).all()
    }

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
            event_class=overrides.get(item.get("id", "")),
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


@router.get(
    "/deadlines",
    response_model=list[schemas.DeadlineResponse],
    summary="Deadlines the scheduler protects",
)
async def list_deadlines(
    include_completed: bool = False,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[schemas.DeadlineResponse]:
    """List the caller's tracked deadlines, soonest first."""
    query = db.query(models.Deadline).filter(
        models.Deadline.owner_id == current_user.id
    )
    if not include_completed:
        query = query.filter(models.Deadline.completed == 0)

    rows = query.order_by(models.Deadline.due_at).all()
    return [
        schemas.DeadlineResponse(
            id=r.id, key=r.key, title=r.title, due_at=r.due_at,
            estimated_minutes=r.estimated_minutes, source=r.source,
            url=r.url, completed=bool(r.completed),
        )
        for r in rows
    ]


@router.post(
    "/deadlines",
    response_model=schemas.DeadlineResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Track a deadline",
)
async def create_deadline(
    request: schemas.DeadlineCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> schemas.DeadlineResponse:
    """
    Register a due date. Re-registering the same key updates it rather than
    creating a duplicate, so a Jira sync can run repeatedly.
    """
    existing = db.query(models.Deadline).filter(
        models.Deadline.owner_id == current_user.id,
        models.Deadline.key == request.key,
    ).first()

    if existing:
        existing.title = request.title
        existing.due_at = request.due_at
        existing.estimated_minutes = request.estimated_minutes
        existing.source = request.source
        existing.url = request.url
        existing.completed = 0
        deadline = existing
    else:
        deadline = models.Deadline(
            key=request.key,
            title=request.title,
            due_at=request.due_at,
            estimated_minutes=request.estimated_minutes,
            source=request.source,
            url=request.url,
            owner_id=current_user.id,
        )
        db.add(deadline)

    db.commit()
    db.refresh(deadline)

    return schemas.DeadlineResponse(
        id=deadline.id, key=deadline.key, title=deadline.title,
        due_at=deadline.due_at, estimated_minutes=deadline.estimated_minutes,
        source=deadline.source, url=deadline.url,
        completed=bool(deadline.completed),
    )


@router.delete(
    "/deadlines/{deadline_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Stop tracking a deadline",
)
async def delete_deadline(
    deadline_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Remove one of the caller's deadlines."""
    deadline = db.query(models.Deadline).filter(
        models.Deadline.id == deadline_id,
        models.Deadline.owner_id == current_user.id,
    ).first()

    if not deadline:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Deadline not found"
        )

    db.delete(deadline)
    db.commit()


@router.post(
    "/constraints",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Override how movable an event is",
)
async def set_constraint(
    request: schemas.EventConstraintSet,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """
    Pin an event as fixed or flexible.

    The solver infers a class from attendee count, but that is wrong often
    enough to need an override: a solo block can be immovable, and a large
    meeting can be trivial to reschedule.
    """
    existing = db.query(models.EventConstraint).filter(
        models.EventConstraint.owner_id == current_user.id,
        models.EventConstraint.event_id == request.event_id,
    ).first()

    if existing:
        existing.event_class = request.event_class.value
        existing.note = request.note
    else:
        db.add(models.EventConstraint(
            event_id=request.event_id,
            event_class=request.event_class.value,
            note=request.note,
            owner_id=current_user.id,
        ))

    db.commit()


@router.post(
    "/plan-deadline/{deadline_id}",
    response_model=schemas.ScheduleProposal,
    summary="Reserve working time before a deadline",
)
async def plan_deadline(
    deadline_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> schemas.ScheduleProposal:
    """
    Find room to do the work before a deadline falls due.

    Changes nothing; the returned plan must be applied explicitly.
    """
    deadline = db.query(models.Deadline).filter(
        models.Deadline.id == deadline_id,
        models.Deadline.owner_id == current_user.id,
    ).first()

    if not deadline:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Deadline not found"
        )

    events = _load_calendar(db, current_user)
    due = deadline.due_at
    if due.tzinfo is None:
        due = due.replace(tzinfo=resolve_timezone(current_user.timezone))

    return plan_for_deadline(
        SchedulingContext(timezone=current_user.timezone, events=events),
        deadline_key=deadline.key,
        deadline=due,
        required_minutes=deadline.estimated_minutes,
        title=f"Work on {deadline.key}",
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
