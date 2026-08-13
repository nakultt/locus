"""
Adaptive Scheduler.

When a new event or a deadline arrives, works out which existing meetings need
to move so the deadline is still met, and proposes the changes.

The solver is plain Python. Constraint satisfaction is what language models are
worst at: asked to rearrange a calendar they produce plausible-looking
schedules with overlapping events and missed deadlines, and the error is hard
to spot precisely because the output reads well. The model explains a plan it
did not compute.

Nothing is applied automatically when other people are involved. Moving a
meeting sends invite updates to every attendee, so a wrong move is visible to
the whole team and cannot be quietly undone.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.schemas import EventClass, ScheduledEvent, ScheduleMove, ScheduleProposal
from app.services.datetimes import (
    DEFAULT_WORKDAYS,
    is_workday,
    resolve_timezone,
    within_working_hours,
)

logger = logging.getLogger(__name__)

# Meetings are not scheduled back to back; people need a moment between calls.
DEFAULT_GAP_MINUTES = 5

# How far ahead to look before treating a move as unworkable.
MAX_SEARCH_DAYS = 14


@dataclass
class Slot:
    """A span of time on the calendar."""

    start: datetime
    end: datetime

    def overlaps(self, other: "Slot") -> bool:
        return self.start < other.end and other.start < self.end

    @property
    def duration_minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)


@dataclass
class SchedulingContext:
    """Everything the solver needs to rearrange a calendar."""

    timezone: str
    events: list[ScheduledEvent] = field(default_factory=list)
    # Deadlines by event id; nothing may be pushed past these.
    deadlines: dict[str, datetime] = field(default_factory=dict)
    workdays: frozenset[int] = DEFAULT_WORKDAYS


def classify_event(event: ScheduledEvent) -> EventClass:
    """
    Decide how movable an event is.

    An explicit classification always wins. Otherwise attendee count decides: a
    solo block is the owner's own time, while anything with external attendees
    is fixed, because moving it inconveniences people outside the team.
    """
    if event.event_class is not None:
        return event.event_class

    if event.has_external_attendees:
        return EventClass.HARD_FIXED

    if event.attendee_count <= 1:
        return EventClass.FLEXIBLE

    return EventClass.SOFT_FIXED


def find_conflicts(
    events: list[ScheduledEvent],
) -> list[tuple[ScheduledEvent, ScheduledEvent]]:
    """
    Find pairs of events that overlap.

    Returns:
        Overlapping pairs, earliest first.
    """
    ordered = sorted(events, key=lambda e: e.start)
    conflicts: list[tuple[ScheduledEvent, ScheduledEvent]] = []

    for i, first in enumerate(ordered):
        for second in ordered[i + 1:]:
            if second.start >= first.end:
                # Sorted by start, so nothing later can overlap this one.
                break
            conflicts.append((first, second))

    return conflicts


def _is_free(
    candidate: Slot,
    events: list[ScheduledEvent],
    ignore_id: str | None = None,
    gap_minutes: int = DEFAULT_GAP_MINUTES,
) -> bool:
    """Whether a slot is clear, allowing a small gap either side."""
    padded = Slot(
        start=candidate.start - timedelta(minutes=gap_minutes),
        end=candidate.end + timedelta(minutes=gap_minutes),
    )

    for event in events:
        if ignore_id and event.event_id == ignore_id:
            continue
        if padded.overlaps(Slot(event.start, event.end)):
            return False

    return True


def find_free_slot(
    duration_minutes: int,
    after: datetime,
    context: SchedulingContext,
    before: datetime | None = None,
    ignore_id: str | None = None,
) -> datetime | None:
    """
    Find the earliest working-hours slot that fits.

    Args:
        duration_minutes: How long the meeting needs
        after: Do not schedule before this
        context: Existing events and working-day configuration
        before: A deadline the slot must finish by
        ignore_id: Event being moved, so it does not block itself

    Returns:
        The slot start, or None if nothing fits in the search window.
    """
    tz = resolve_timezone(context.timezone)
    cursor = after.astimezone(tz).replace(second=0, microsecond=0)

    # Round up to the next quarter hour; nobody schedules at 14:07.
    remainder = cursor.minute % 15
    if remainder:
        cursor += timedelta(minutes=15 - remainder)

    horizon = min(
        before or (cursor + timedelta(days=MAX_SEARCH_DAYS)),
        cursor + timedelta(days=MAX_SEARCH_DAYS),
    )

    while cursor + timedelta(minutes=duration_minutes) <= horizon:
        candidate = Slot(cursor, cursor + timedelta(minutes=duration_minutes))

        if (
            is_workday(cursor, context.workdays)
            and within_working_hours(cursor)
            and within_working_hours(candidate.end)
            and _is_free(candidate, context.events, ignore_id)
        ):
            return cursor

        cursor += timedelta(minutes=15)

    return None


def _disruption_rank(event: ScheduledEvent) -> tuple[int, int]:
    """
    Order events by how disruptive moving them would be.

    Flexible solo time first, then meetings with fewer people.
    """
    order = {
        EventClass.FLEXIBLE: 0,
        EventClass.SOFT_FIXED: 1,
        EventClass.HARD_FIXED: 2,
    }
    return order[classify_event(event)], event.attendee_count


def _describe(proposal: ScheduleProposal) -> str:
    """A plain-language summary of the plan, computed rather than generated."""
    if not proposal.moves and not proposal.blocked and not proposal.additions:
        return "Nothing needs to move."

    parts = []
    if proposal.moves:
        parts.append(f"{len(proposal.moves)} event(s) would move")
    if proposal.additions:
        parts.append(f"{len(proposal.additions)} block(s) would be added")
    if proposal.blocked:
        parts.append(
            f"{len(proposal.blocked)} conflict(s) cannot be resolved automatically"
        )

    return "; ".join(parts) + "."


def plan_for_new_event(
    new_event: ScheduledEvent,
    context: SchedulingContext,
) -> ScheduleProposal:
    """
    Work out what must move to fit a new event in.

    The new event is treated as fixed -- the user just asked for it. Anything
    it collides with moves in order of how movable it is: flexible blocks
    first, then soft-fixed meetings. Hard-fixed events never move, and when one
    blocks the way the proposal says so rather than dropping the conflict.
    """
    proposal = ScheduleProposal(
        trigger=f"New event: {new_event.title}",
        timezone=context.timezone,
    )

    colliding = [
        event
        for event in context.events
        if event.event_id != new_event.event_id
        and Slot(event.start, event.end).overlaps(
            Slot(new_event.start, new_event.end)
        )
    ]

    if not colliding:
        proposal.summary = f"'{new_event.title}' fits without moving anything."
        return proposal

    # Least disruptive first, so a focus block moves before a 1:1.
    working = list(context.events) + [new_event]

    for event in sorted(colliding, key=_disruption_rank):
        event_class = classify_event(event)

        if event_class == EventClass.HARD_FIXED:
            proposal.blocked.append(
                f"'{event.title}' cannot move (external attendees or marked "
                f"fixed), so it still clashes with '{new_event.title}'"
            )
            continue

        deadline = context.deadlines.get(event.event_id)
        new_start = find_free_slot(
            duration_minutes=event.duration_minutes,
            after=new_event.end,
            context=SchedulingContext(
                timezone=context.timezone,
                events=working,
                deadlines=context.deadlines,
                workdays=context.workdays,
            ),
            before=deadline,
            ignore_id=event.event_id,
        )

        if new_start is None:
            proposal.blocked.append(
                f"No free slot for '{event.title}'"
                + (f" before its {deadline:%a %d %b} deadline" if deadline else "")
            )
            continue

        proposal.moves.append(
            ScheduleMove(
                event_id=event.event_id,
                title=event.title,
                from_start=event.start,
                to_start=new_start,
                duration_minutes=event.duration_minutes,
                event_class=event_class,
                attendee_count=event.attendee_count,
                reason=f"Clashes with '{new_event.title}'",
            )
        )

        # Reflect the move so later placements see it.
        working = [e for e in working if e.event_id != event.event_id]
        working.append(
            ScheduledEvent(
                event_id=event.event_id,
                title=event.title,
                start=new_start,
                end=new_start + timedelta(minutes=event.duration_minutes),
                attendee_count=event.attendee_count,
                has_external_attendees=event.has_external_attendees,
                event_class=event.event_class,
            )
        )

    proposal.summary = _describe(proposal)
    return proposal


def plan_for_deadline(
    context: SchedulingContext,
    deadline_key: str,
    deadline: datetime,
    required_minutes: int,
    title: str = "Focus time",
) -> ScheduleProposal:
    """
    Reserve working time before a deadline.

    Used when a ticket comes due and no room is booked to do the work.
    """
    proposal = ScheduleProposal(
        trigger=f"Deadline: {deadline_key} due {deadline:%a %d %b}",
        timezone=context.timezone,
    )

    now = datetime.now(resolve_timezone(context.timezone))

    slot = find_free_slot(
        duration_minutes=required_minutes,
        after=now,
        context=context,
        before=deadline,
    )

    if slot is not None:
        proposal.additions.append(
            ScheduleMove(
                event_id="",
                title=title,
                from_start=None,
                to_start=slot,
                duration_minutes=required_minutes,
                event_class=EventClass.FLEXIBLE,
                attendee_count=1,
                reason=f"Work time before {deadline_key} is due",
            )
        )
        proposal.summary = (
            f"{required_minutes} minutes reserved on "
            f"{slot:%a %d %b at %H:%M} for {deadline_key}."
        )
        return proposal

    # Nothing free: name a candidate the user could shorten themselves.
    for event in sorted(context.events, key=_disruption_rank):
        if classify_event(event) != EventClass.FLEXIBLE:
            continue
        if event.duration_minutes < required_minutes:
            continue
        proposal.blocked.append(
            f"No free time before the deadline. Consider shortening or moving "
            f"'{event.title}' on {event.start:%a %d %b}."
        )
        break
    else:
        proposal.blocked.append(
            f"No working time available before {deadline:%a %d %b}. "
            f"The deadline may need to move."
        )

    proposal.summary = _describe(proposal)
    return proposal
