"""
Whether the owner can be reached right now, and when they next can.

This is what the calendar exists to answer for other people, and it is the one
question the pipeline itself never asks: the calendar agent runs *alongside*
the pipeline, never inside it. Delaying a review request until a focus block
ends manufactures the exact silence that makes an approved pull request look
like a broken feature.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta

from sqlalchemy.orm import Session

from app import models, schemas
from app.services.datetimes import resolve_timezone

logger = logging.getLogger(__name__)

# Titles that mean "this is protected time" rather than "this is a meeting".
# A meeting has an end time; a focus block is a choice, and the reply reads
# differently for each.
FOCUS_MARKERS = ("focus", "deep work", "heads down", "do not disturb", "dnd", "blocked")


def is_focus(event: schemas.ScheduledEvent) -> bool:
    title = (event.title or "").lower()
    return event.attendee_count <= 1 and any(m in title for m in FOCUS_MARKERS)


def within_working_hours(
    moment: datetime, settings: models.TimeAgentSettings, timezone: str | None
) -> bool:
    """
    Whether this instant falls inside the configured working day.

    Read through a real timezone library rather than by adding an integer
    offset: the default zone is UTC+05:30, and the half hour breaks naive hour
    arithmetic in a way that only shows up for half the day.
    """
    tz = resolve_timezone(timezone)
    local = moment.astimezone(tz)

    start = _parse_hhmm(settings.working_hours_start, time(9, 30))
    end = _parse_hhmm(settings.working_hours_end, time(18, 30))

    # Weekends are outside the working week; a team that works Saturdays says
    # so by leaving the agent off rather than by having the reply lie.
    if local.weekday() >= 5:
        return False

    return start <= local.time() <= end


def _parse_hhmm(value: str | None, fallback: time) -> time:
    try:
        hour, _, minute = (value or "").partition(":")
        return time(int(hour), int(minute))
    except (TypeError, ValueError):
        return fallback


def current_status(
    events: list[schemas.ScheduledEvent],
    settings: models.TimeAgentSettings,
    timezone: str | None,
    now: datetime | None = None,
) -> schemas.Availability:
    """
    The owner's reachability, and nothing else about their day.

    Carries no event title, attendee, location or description. **The type is
    the enforcement**: a busy reply is posted into a channel other people read,
    and "in a 1:1 with Priya re: restructure" must not be able to reach it.
    There is no field to leak it through.
    """
    tz = resolve_timezone(timezone)
    moment = (now or datetime.now(tz)).astimezone(tz)

    live = [
        event for event in events
        if event.start.astimezone(tz) <= moment < event.end.astimezone(tz)
    ]

    if live:
        # The latest end among overlapping events: someone double-booked is
        # busy until the last of them finishes, not the first.
        until = max(event.end.astimezone(tz) for event in live)
        state = "focus" if all(is_focus(event) for event in live) else "busy"
        return schemas.Availability(
            state=state,
            until=until,
            next_free=_next_free(events, until, tz),
        )

    if not within_working_hours(moment, settings, timezone):
        return schemas.Availability(
            state="off_hours",
            until=None,
            next_free=_next_working_start(moment, settings, tz),
        )

    return schemas.Availability(state="free", until=None, next_free=None)


def _next_free(
    events: list[schemas.ScheduledEvent], after: datetime, tz
) -> datetime:
    """
    The first moment nothing is booked, walking through back-to-back events.

    Reporting the end of the current meeting when the next starts immediately
    afterwards is worse than saying nothing: somebody waits for a gap that is
    not there.
    """
    cursor = after
    moved = True

    while moved:
        moved = False
        for event in events:
            start = event.start.astimezone(tz)
            end = event.end.astimezone(tz)
            if start <= cursor < end:
                cursor = end
                moved = True

    return cursor


def _next_working_start(moment: datetime, settings, tz) -> datetime:
    """The next weekday morning the working day opens."""
    start = _parse_hhmm(settings.working_hours_start, time(9, 30))
    candidate = moment.replace(
        hour=start.hour, minute=start.minute, second=0, microsecond=0
    )
    if candidate <= moment:
        candidate += timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


async def for_user(
    db: Session, user: models.User, settings: models.TimeAgentSettings
) -> schemas.Availability:
    """
    Read the calendar and answer for this user.

    **Returns `free` when the calendar cannot be read.** A broken token and a
    real meeting produce identical silence, and defaulting to busy fails in the
    direction that makes the user unreachable -- the auto-responder tells
    everybody they are in a meeting they are not in, and the reply they were
    waiting for never comes. The breakage surfaces through
    `integration_health`, which is what that table is for.

    The token is refreshed rather than read raw. A Google access token lives an
    hour; reading `credentials["access_token"]` directly works for exactly one
    hour after the integration is connected and returns 401 forever after.
    """
    from app.dependencies import get_integration_configs
    from app.routers.schedule import events_from_raw
    from app.services import calendar as calendar_service

    try:
        configs = get_integration_configs(db, user.id)
        if "calendar" not in configs:
            return schemas.Availability(state="free")

        calendar_service.get_calendar_tools(
            credentials=configs["calendar"].get("credentials", {}),
            timezone=user.timezone,
        )
        raw, error = calendar_service.fetch_events("today", "in 2 days")
        if error:
            logger.debug("Availability lookup failed for %s: %s", user.id, error)
            return schemas.Availability(state="free")

        events = events_from_raw(db, user, raw)
    except Exception as exc:
        logger.debug("Availability lookup failed for %s: %s", user.id, exc)
        return schemas.Availability(state="free")

    return current_status(events, settings, user.timezone)
