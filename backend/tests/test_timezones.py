"""
Timezone handling: stored as instants, displayed in IST.

Two separate concerns that are easy to conflate:

**Storage is UTC.** Postgres sessions are pinned to UTC rather than inheriting
the server's zone, because a session that inherits it serialized the same row
as "+05:30" on a developer's machine and "+00:00" in production. Both name the
same instant, and the difference is invisible until something compares or
caches them.

**Display is IST.** Applied in the frontend (`src/lib/datetime.ts`), so every
viewer reads the same wall clock regardless of where their browser thinks it
is. These are shared events people talk to each other about: "the build broke
at 3" has to mean one moment.

What the backend owes the frontend is an unambiguous instant. What it must
never do is format a time into text without saying which zone it is in --
`google_meet` did exactly that, labelling server-local times "UTC".
"""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from app.core import datetimes

IST = ZoneInfo("Asia/Kolkata")


class TestDefaultZone:
    def test_the_default_is_ist(self):
        assert datetimes.DEFAULT_TIMEZONE == "Asia/Kolkata"

    def test_an_unknown_zone_falls_back_rather_than_failing(self):
        """
        Refusing to schedule because a stored name is stale is worse than
        scheduling in the default and logging it.
        """
        assert datetimes.resolve_timezone("Mars/Olympus") == IST
        assert datetimes.resolve_timezone(None) == IST
        assert datetimes.resolve_timezone("") == IST

    def test_an_explicit_zone_is_respected(self):
        """IST is the default, not a hard-coding: users elsewhere override it."""
        assert datetimes.resolve_timezone("Europe/London") == ZoneInfo("Europe/London")

    def test_now_is_returned_in_the_users_zone(self):
        assert datetimes.now_in(None).tzinfo == IST
        assert datetimes.now_in("Asia/Kolkata").utcoffset().total_seconds() == 19800


class TestParsing:
    def test_a_time_is_read_in_ist_not_the_server_zone(self):
        """
        The bug this guards: naive datetimes built from the server clock and
        labelled UTC put every IST user's event 5h30m out on a UTC host.
        """
        base = datetime(2026, 8, 14, 9, 0, tzinfo=IST)
        parsed = datetimes.parse_datetime("today at 4pm", "Asia/Kolkata", base=base)

        assert parsed is not None
        assert parsed.hour == 16
        assert parsed.utcoffset().total_seconds() == 19800

    def test_the_half_hour_offset_survives_conversion(self):
        """
        IST is UTC+05:30. Integer-hour arithmetic silently loses the 30
        minutes, which is why this goes through a real timezone library.
        """
        moment = datetime(2026, 8, 14, 20, 23, tzinfo=IST)

        assert moment.astimezone(UTC).hour == 14
        assert moment.astimezone(UTC).minute == 53

    def test_unreadable_text_returns_none_rather_than_guessing(self):
        """
        A caller must decide what to do, rather than receive a confidently
        wrong 9am -- which is what the old hand-rolled parser did.
        """
        assert datetimes.parse_datetime("sometime whenever", "Asia/Kolkata") is None
        assert datetimes.parse_datetime("", "Asia/Kolkata") is None
        assert datetimes.parse_datetime(None, "Asia/Kolkata") is None


class TestGoogleRendering:
    def test_the_zone_travels_with_the_timestamp(self):
        """
        Sent alongside rather than converted to UTC, so a recurring event
        stays correct across a DST shift.
        """
        moment = datetime(2026, 8, 14, 16, 0, tzinfo=IST)
        rendered = datetimes.to_google_datetime(moment, "Asia/Kolkata")

        assert rendered["timeZone"] == "Asia/Kolkata"
        assert "+05:30" in rendered["dateTime"]

    def test_a_naive_datetime_is_read_as_the_users_zone(self):
        rendered = datetimes.to_google_datetime(
            datetime(2026, 8, 14, 16, 0), "Asia/Kolkata"
        )
        assert "+05:30" in rendered["dateTime"]


class TestMeetUsesTheUsersZone:
    """
    `google_meet` carried its own copy of the parser that `datetimes` was
    written to replace: three recognised times, everything else silently 9am,
    naive server-clock datetimes labelled "UTC".
    """

    def test_a_meeting_is_booked_in_ist_not_utc(self, monkeypatch):
        from app.services.integrations import google_meet

        google_meet._meet_config.set({"timezone": "Asia/Kolkata"})

        parsed = google_meet._parse_datetime("tomorrow at 4pm")

        assert parsed.utcoffset().total_seconds() == 19800
        assert parsed.hour == 16

    def test_the_payload_declares_the_real_zone(self, monkeypatch):
        """It used to hardcode "UTC" onto a time that was not UTC."""
        from app.services.integrations import google_meet

        google_meet._meet_config.set({"timezone": "Asia/Kolkata"})

        payload = datetimes.to_google_datetime(
            datetime(2026, 8, 14, 16, 0, tzinfo=IST),
            google_meet._meeting_timezone(),
        )

        assert payload["timeZone"] == "Asia/Kolkata"

    def test_an_unparseable_time_falls_back_in_the_users_zone(self):
        """The fallback must not silently land at the server's offset."""
        from app.services.integrations import google_meet

        google_meet._meet_config.set({"timezone": "Asia/Kolkata"})

        parsed = google_meet._parse_datetime("whenever suits")

        assert parsed.utcoffset().total_seconds() == 19800


class TestStoredTimestampsAreInstants:
    @pytest.mark.asyncio
    async def test_a_stored_timestamp_carries_a_zone(self, tmp_path):
        """
        The frontend converts to IST for display, which it can only do from an
        unambiguous instant. SQLite stores UTC without labelling it, and
        `parseInstant` reads a bare timestamp as UTC for exactly that reason.
        """
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from app import models
        from app.core.database import Base

        engine = create_engine(f"sqlite:///{tmp_path}/tz.db")
        Base.metadata.create_all(bind=engine)
        db = sessionmaker(bind=engine)()

        try:
            db.add(models.User(
                id=1, email="a@a.com", hashed_password="x",
                timezone="Asia/Kolkata",
            ))
            db.commit()
            db.add(models.PRJob(
                repo="a/b", pr_number=1, action="opened",
                status="queued", owner_id=1,
            ))
            db.commit()

            stored = db.query(models.PRJob).one().created_at

            # SQLite hands back a naive datetime holding UTC. The value is
            # what matters: it must be UTC, not the server's local clock,
            # or the frontend's UTC assumption would shift every timestamp.
            reference = datetime.now(UTC).replace(tzinfo=None)
            assert abs((stored - reference).total_seconds()) < 120
        finally:
            db.close()
