"""
Timezone-aware natural-language date parsing.

The previous parser recognised exactly three times -- "2pm", "3pm", "10am" --
and silently defaulted everything else to 9am. It also built naive datetimes
from the *server* clock and labelled them UTC, so on a UTC host every event a
user in IST created landed 5h30m off.

Both failures were silent: the event was created, the API returned success, and
only the wall clock disagreed.

Times are resolved in the user's own timezone and sent to Google with that
zone attached, so the API applies the correct offset rather than guessing.
"""

import logging
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import dateparser

logger = logging.getLogger(__name__)

# Locus is built for IST first; users elsewhere override this on their profile.
DEFAULT_TIMEZONE = "Asia/Kolkata"

# Indian working day. Used when scheduling has to pick a slot rather than
# being told one.
DEFAULT_WORK_START_HOUR = 9
DEFAULT_WORK_START_MINUTE = 30
DEFAULT_WORK_END_HOUR = 18
DEFAULT_WORK_END_MINUTE = 30

# Monday-Friday. Saturday=5, Sunday=6 in Python's weekday numbering.
DEFAULT_WORKDAYS = frozenset({0, 1, 2, 3, 4})


def resolve_timezone(name: str | None) -> ZoneInfo:
    """
    Turn a timezone name into a ZoneInfo, falling back to the default.

    A stored name can be stale or misspelled; refusing to schedule is worse
    than scheduling in the default zone and saying so in the log.
    """
    try:
        return ZoneInfo(name or DEFAULT_TIMEZONE)
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning("Unknown timezone %r; using %s", name, DEFAULT_TIMEZONE)
        return ZoneInfo(DEFAULT_TIMEZONE)


def now_in(timezone_name: str | None) -> datetime:
    """Current time in the user's timezone."""
    return datetime.now(resolve_timezone(timezone_name))


# dateparser fails outright on "next Tuesday 10:30" but handles "Tuesday
# 10:30" fine, and PREFER_DATES_FROM=future already means the upcoming one.
# Dropping the redundant prefix turns a None into a correct answer.
_REDUNDANT_PREFIX = re.compile(r"^\s*(next|this|coming|upcoming)\s+", re.I)

# "Friday morning" / "Monday evening" carry a time humans understand but
# dateparser does not; map them onto the hour they mean.
_TIME_OF_DAY = {
    "morning": "9am",
    "afternoon": "2pm",
    "evening": "6pm",
    "night": "8pm",
    "noon": "12pm",
    "midday": "12pm",
}


def _normalize(text: str) -> str:
    """Rewrite phrasings dateparser mishandles into ones it understands."""
    cleaned = _REDUNDANT_PREFIX.sub("", text.strip())

    for word, replacement in _TIME_OF_DAY.items():
        boundary = r"\b"
        pattern = re.compile(boundary + word + boundary, re.I)
        if pattern.search(cleaned):
            cleaned = pattern.sub(replacement, cleaned)
            break

    return cleaned


def parse_datetime(
    text: str | None,
    timezone_name: str | None = None,
    base: datetime | None = None,
) -> datetime | None:
    """
    Parse a natural-language date/time in the user's timezone.

    Handles "tomorrow at 4pm", "next Tuesday 10:30", "in 2 hours", "Friday
    morning", and ISO strings.

    Args:
        text: What the user said
        timezone_name: IANA name, e.g. "Asia/Kolkata"
        base: Reference point for relative expressions; defaults to now

    Returns:
        A timezone-aware datetime, or None when the text names no time. None
        is deliberate: a caller must decide what to do rather than receive a
        confidently wrong 9am.
    """
    if not text or not text.strip():
        return None

    tz = resolve_timezone(timezone_name)
    reference = base or datetime.now(tz)

    parsed = dateparser.parse(
        _normalize(text),
        settings={
            "TIMEZONE": str(tz),
            "RETURN_AS_TIMEZONE_AWARE": True,
            # "Tuesday at 3pm" means the next one, not the one that just passed.
            "PREFER_DATES_FROM": "future",
            "RELATIVE_BASE": reference.replace(tzinfo=None),
        },
    )

    if parsed is None:
        return None

    # dateparser can return the reference zone rather than the requested one.
    return parsed.astimezone(tz) if parsed.tzinfo else parsed.replace(tzinfo=tz)


def parse_duration_minutes(text: str | None, default: int = 60) -> int:
    """
    Parse a duration such as "45 minutes", "1.5 hours", "2h".

    Returns:
        Minutes, clamped to a sane range.
    """
    if not text:
        return default

    cleaned = text.strip().lower()

    match = re.search(r"(\d+(?:\.\d+)?)\s*(h|hr|hour|hours|m|min|minute|minutes)", cleaned)
    if not match:
        # A bare number is read as minutes.
        bare = re.fullmatch(r"\d+", cleaned)
        return max(5, min(int(bare.group()), 60 * 12)) if bare else default

    value = float(match.group(1))
    unit = match.group(2)
    minutes = value * 60 if unit.startswith("h") else value

    return max(5, min(int(minutes), 60 * 12))


def to_google_datetime(moment: datetime, timezone_name: str | None) -> dict[str, str]:
    """
    Render a datetime for the Google Calendar API.

    The zone is sent alongside the timestamp rather than converting to UTC, so
    a recurring event stays correct across a DST shift.
    """
    tz = resolve_timezone(timezone_name)
    aware = moment.astimezone(tz) if moment.tzinfo else moment.replace(tzinfo=tz)

    return {"dateTime": aware.isoformat(), "timeZone": str(tz)}


def is_workday(moment: datetime, workdays: frozenset[int] = DEFAULT_WORKDAYS) -> bool:
    """Whether a date falls on a configured working day."""
    return moment.weekday() in workdays


def within_working_hours(
    moment: datetime,
    start_hour: int = DEFAULT_WORK_START_HOUR,
    start_minute: int = DEFAULT_WORK_START_MINUTE,
    end_hour: int = DEFAULT_WORK_END_HOUR,
    end_minute: int = DEFAULT_WORK_END_MINUTE,
) -> bool:
    """Whether a time falls inside the working day."""
    minutes = moment.hour * 60 + moment.minute
    return (start_hour * 60 + start_minute) <= minutes <= (end_hour * 60 + end_minute)


def next_working_slot(
    after: datetime,
    duration_minutes: int = 60,
    workdays: frozenset[int] = DEFAULT_WORKDAYS,
) -> datetime:
    """
    The next time a meeting of this length fits inside working hours.

    Ignores existing events -- the scheduler layers conflict avoidance on top.
    """
    candidate = after.replace(second=0, microsecond=0)

    # Two weeks is far more than enough; the bound stops a pathological loop.
    for _ in range(14 * 24 * 4):
        end = candidate + timedelta(minutes=duration_minutes)

        if (
            is_workday(candidate, workdays)
            and within_working_hours(candidate)
            and within_working_hours(end)
        ):
            return candidate

        # Past the working day, jump to the next morning.
        if not within_working_hours(candidate) and candidate.hour >= DEFAULT_WORK_END_HOUR:
            candidate = (candidate + timedelta(days=1)).replace(
                hour=DEFAULT_WORK_START_HOUR, minute=DEFAULT_WORK_START_MINUTE
            )
        elif not is_workday(candidate, workdays):
            candidate = (candidate + timedelta(days=1)).replace(
                hour=DEFAULT_WORK_START_HOUR, minute=DEFAULT_WORK_START_MINUTE
            )
        elif candidate.hour < DEFAULT_WORK_START_HOUR:
            candidate = candidate.replace(
                hour=DEFAULT_WORK_START_HOUR, minute=DEFAULT_WORK_START_MINUTE
            )
        else:
            candidate += timedelta(minutes=15)

    return candidate
