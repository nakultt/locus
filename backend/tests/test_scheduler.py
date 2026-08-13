"""
Adaptive Scheduler and timezone-aware date parsing.

The solver is deliberately plain Python: a model asked to rearrange a calendar
produces plausible-looking schedules with overlaps and missed deadlines. These
tests pin the properties that make the output trustworthy -- no double
bookings, nothing outside working hours, and hard-fixed events left alone.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.schemas import EventClass, ScheduledEvent
from app.services.datetimes import (
    is_workday,
    next_working_slot,
    parse_datetime,
    parse_duration_minutes,
    resolve_timezone,
    to_google_datetime,
    within_working_hours,
)
from app.services.scheduler import (
    SchedulingContext,
    classify_event,
    find_conflicts,
    find_free_slot,
    plan_for_deadline,
    plan_for_new_event,
)

IST = ZoneInfo("Asia/Kolkata")

# A Wednesday, so weekday arithmetic in the tests is unambiguous.
WEDNESDAY = datetime(2026, 8, 12, 10, 0, tzinfo=IST)


def make_event(
    event_id: str,
    title: str,
    hour: int,
    minute: int = 0,
    minutes: int = 60,
    attendees: int = 1,
    external: bool = False,
    event_class: EventClass | None = None,
    day: int = 12,
) -> ScheduledEvent:
    start = datetime(2026, 8, day, hour, minute, tzinfo=IST)
    return ScheduledEvent(
        event_id=event_id,
        title=title,
        start=start,
        end=start + timedelta(minutes=minutes),
        attendee_count=attendees,
        has_external_attendees=external,
        event_class=event_class,
    )


class TestDateParsing:
    """
    The previous parser understood "2pm", "3pm" and "10am" and silently
    returned 9am for everything else, on the server clock labelled UTC.
    """

    def test_parses_relative_days_and_times(self):
        result = parse_datetime("tomorrow at 4pm", "Asia/Kolkata", base=WEDNESDAY)
        assert result.hour == 16
        assert result.day == 13

    def test_parses_weekday_with_next_prefix(self):
        # dateparser fails on "next Tuesday 10:30"; the prefix is normalized away.
        result = parse_datetime("next Tuesday 10:30", "Asia/Kolkata", base=WEDNESDAY)
        assert result is not None
        assert result.weekday() == 1
        assert (result.hour, result.minute) == (10, 30)

    def test_parses_time_of_day_words(self):
        assert parse_datetime("Friday morning", "Asia/Kolkata", base=WEDNESDAY).hour == 9
        assert parse_datetime("tomorrow afternoon", "Asia/Kolkata", base=WEDNESDAY).hour == 14

    def test_parses_relative_offsets(self):
        result = parse_datetime("in 90 minutes", "Asia/Kolkata", base=WEDNESDAY)
        assert result.hour == 11 and result.minute == 30

    def test_unparseable_returns_none_rather_than_a_default(self):
        """
        Returning None forces the caller to decide. The old code returned a
        confident 9am, so a typo silently created an event at the wrong time.
        """
        assert parse_datetime("banana", "Asia/Kolkata") is None
        assert parse_datetime("", "Asia/Kolkata") is None
        assert parse_datetime(None, "Asia/Kolkata") is None

    def test_result_carries_the_users_timezone(self):
        result = parse_datetime("tomorrow at 4pm", "Asia/Kolkata", base=WEDNESDAY)
        assert result.utcoffset() == timedelta(hours=5, minutes=30)

    def test_unknown_timezone_falls_back(self):
        assert str(resolve_timezone("Mars/Olympus")) == "Asia/Kolkata"
        assert str(resolve_timezone(None)) == "Asia/Kolkata"


class TestGooglePayload:
    def test_sends_the_zone_rather_than_converting_to_utc(self):
        """
        Hardcoding UTC put every IST event 5h30m off. Sending the zone lets
        Google apply the offset, and keeps recurring events correct across DST.
        """
        payload = to_google_datetime(WEDNESDAY, "Asia/Kolkata")
        assert payload["timeZone"] == "Asia/Kolkata"
        assert "+05:30" in payload["dateTime"]


class TestDurations:
    def test_parses_common_forms(self):
        assert parse_duration_minutes("45 minutes") == 45
        assert parse_duration_minutes("1.5 hours") == 90
        assert parse_duration_minutes("2h") == 120
        assert parse_duration_minutes("30") == 30

    def test_defaults_and_clamps(self):
        assert parse_duration_minutes(None) == 60
        assert parse_duration_minutes("nonsense") == 60
        assert parse_duration_minutes("500 hours") == 720


class TestWorkingHours:
    def test_recognises_the_indian_working_day(self):
        assert within_working_hours(datetime(2026, 8, 12, 10, 0, tzinfo=IST))
        assert not within_working_hours(datetime(2026, 8, 12, 7, 0, tzinfo=IST))
        assert not within_working_hours(datetime(2026, 8, 12, 20, 0, tzinfo=IST))

    def test_weekends_are_not_workdays(self):
        assert is_workday(datetime(2026, 8, 14, 10, 0, tzinfo=IST))       # Friday
        assert not is_workday(datetime(2026, 8, 15, 10, 0, tzinfo=IST))   # Saturday
        assert not is_workday(datetime(2026, 8, 16, 10, 0, tzinfo=IST))   # Sunday

    def test_saturday_evening_rolls_to_monday_morning(self):
        slot = next_working_slot(datetime(2026, 8, 15, 20, 0, tzinfo=IST))
        assert slot.weekday() == 0
        assert (slot.hour, slot.minute) == (9, 30)


class TestEventClassification:
    def test_solo_time_is_flexible(self):
        assert classify_event(make_event("a", "Deep work", 14)) == EventClass.FLEXIBLE

    def test_internal_meeting_is_soft_fixed(self):
        event = make_event("b", "1:1", 15, attendees=2)
        assert classify_event(event) == EventClass.SOFT_FIXED

    def test_external_attendees_make_it_hard_fixed(self):
        event = make_event("c", "Client demo", 16, attendees=4, external=True)
        assert classify_event(event) == EventClass.HARD_FIXED

    def test_explicit_class_wins_over_the_heuristic(self):
        event = make_event("d", "Protected", 14, event_class=EventClass.HARD_FIXED)
        assert classify_event(event) == EventClass.HARD_FIXED


class TestConflictDetection:
    def test_finds_an_overlap(self):
        events = [
            make_event("a", "First", 14, minutes=60),
            make_event("b", "Second", 14, 30, minutes=60),
        ]
        assert len(find_conflicts(events)) == 1

    def test_adjacent_events_do_not_conflict(self):
        events = [
            make_event("a", "First", 14, minutes=60),
            make_event("b", "Second", 15, minutes=60),
        ]
        assert find_conflicts(events) == []

    def test_no_events_no_conflicts(self):
        assert find_conflicts([]) == []


class TestFreeSlotSearch:
    def test_avoids_existing_events(self):
        context = SchedulingContext(
            timezone="Asia/Kolkata",
            events=[make_event("busy", "Booked", 10, minutes=120)],
        )
        slot = find_free_slot(60, WEDNESDAY, context)
        # Must start after the booked block plus the gap.
        assert slot >= datetime(2026, 8, 12, 12, 0, tzinfo=IST)

    def test_stays_inside_working_hours(self):
        context = SchedulingContext(timezone="Asia/Kolkata", events=[])
        slot = find_free_slot(
            60, datetime(2026, 8, 12, 19, 0, tzinfo=IST), context
        )
        assert within_working_hours(slot)
        assert slot.day == 13  # pushed to the next morning

    def test_returns_none_when_the_deadline_is_too_close(self):
        context = SchedulingContext(timezone="Asia/Kolkata", events=[])
        slot = find_free_slot(
            120,
            WEDNESDAY,
            context,
            before=WEDNESDAY + timedelta(minutes=30),
        )
        assert slot is None


class TestPlanning:
    def test_no_conflict_means_no_moves(self):
        context = SchedulingContext(
            timezone="Asia/Kolkata",
            events=[make_event("a", "Morning standup", 9, 30, minutes=15)],
        )
        plan = plan_for_new_event(make_event("new", "Sync", 14), context)

        assert plan.moves == []
        assert "without moving anything" in plan.summary

    def test_flexible_time_moves_before_a_meeting(self):
        context = SchedulingContext(
            timezone="Asia/Kolkata",
            events=[
                make_event("focus", "Deep work", 14, minutes=120),
                make_event("oneone", "1:1", 15, minutes=30, attendees=2),
            ],
        )
        plan = plan_for_new_event(
            make_event("new", "Incident review", 14, 30, minutes=90, attendees=3),
            context,
        )

        moved = [m.title for m in plan.moves]
        assert "Deep work" in moved
        # The flexible block is dealt with first.
        assert moved[0] == "Deep work"

    def test_hard_fixed_events_are_never_moved(self):
        """
        The guarantee that matters: an external meeting is reported as a
        blocker rather than quietly rescheduled onto someone else's calendar.
        """
        context = SchedulingContext(
            timezone="Asia/Kolkata",
            events=[
                make_event("client", "Client demo", 14, attendees=4, external=True)
            ],
        )
        plan = plan_for_new_event(
            make_event("new", "Internal sync", 14, 30, attendees=2), context
        )

        assert plan.moves == []
        assert len(plan.blocked) == 1
        assert "Client demo" in plan.blocked[0]

    def test_proposed_moves_never_overlap_each_other(self):
        """A plan that resolves one clash by creating another is worthless."""
        context = SchedulingContext(
            timezone="Asia/Kolkata",
            events=[
                make_event("a", "Block A", 14, minutes=60),
                make_event("b", "Block B", 14, 15, minutes=60),
                make_event("c", "Block C", 14, 30, minutes=60),
            ],
        )
        plan = plan_for_new_event(
            make_event("new", "Big meeting", 14, minutes=120), context
        )

        placements = [
            (m.to_start, m.to_start + timedelta(minutes=m.duration_minutes))
            for m in plan.moves
        ]
        for i, (start_a, end_a) in enumerate(placements):
            for start_b, end_b in placements[i + 1:]:
                assert not (start_a < end_b and start_b < end_a), "moves overlap"

    def test_moves_with_attendees_require_approval(self):
        context = SchedulingContext(
            timezone="Asia/Kolkata",
            events=[make_event("team", "Team sync", 14, attendees=5)],
        )
        plan = plan_for_new_event(
            make_event("new", "Urgent", 14, attendees=2), context
        )
        assert plan.requires_approval is True

    def test_solo_only_plan_needs_no_approval(self):
        context = SchedulingContext(
            timezone="Asia/Kolkata",
            events=[make_event("focus", "Deep work", 14)],
        )
        plan = plan_for_new_event(
            make_event("new", "Errand", 14, attendees=1), context
        )
        assert plan.requires_approval is False


class TestDeadlinePlanning:
    def test_reserves_time_before_a_deadline(self):
        context = SchedulingContext(timezone="Asia/Kolkata", events=[])
        deadline = datetime.now(IST) + timedelta(days=3)

        plan = plan_for_deadline(context, "LOC-431", deadline, required_minutes=90)

        assert len(plan.additions) == 1
        assert plan.additions[0].duration_minutes == 90
        assert plan.additions[0].to_start < deadline

    def test_reports_when_no_time_is_available(self):
        context = SchedulingContext(timezone="Asia/Kolkata", events=[])
        # A deadline in the past leaves nowhere to put the work.
        deadline = datetime.now(IST) - timedelta(days=1)

        plan = plan_for_deadline(context, "LOC-999", deadline, required_minutes=60)

        assert plan.additions == []
        assert plan.blocked
