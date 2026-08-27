"""
Availability, and answering somebody who reached you while you were booked.

Three rules shape this phase. Importance is decided deterministically first,
because "your reviewer, mid-round" is a fact and a classifier's opinion is not.
The reply carries a state and a time and nothing else, because it is posted
into a channel other people read. And it fires once per thread per day: a
repeating auto-responder gets the bot muted, and a muted bot takes the review
pings and the QA threads down with it.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models, schemas
from app.services import availability, interruption
from app.services import scheduler as scheduler_module


@pytest.fixture
def db(tmp_path):
    from app.database import Base

    engine = create_engine(
        f"sqlite:///{tmp_path}/i.db", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def settings(**kwargs) -> models.TimeAgentSettings:
    base = dict(
        owner_id=1, enabled=1, auto_reply_busy=1,
        working_hours_start="09:30", working_hours_end="18:30",
        protect_focus_blocks=1,
    )
    base.update(kwargs)
    return models.TimeAgentSettings(**base)


def event(title, *, start, minutes=60, attendees=2) -> schemas.ScheduledEvent:
    return schemas.ScheduledEvent(
        event_id=title.lower().replace(" ", "-"),
        title=title,
        start=start,
        end=start + timedelta(minutes=minutes),
        attendee_count=attendees,
    )


# A Wednesday at 11:00 IST, comfortably inside the default working day.
WEDNESDAY = datetime(2026, 3, 4, 11, 0, tzinfo=UTC) + timedelta(hours=-5, minutes=-30)


class TestAvailabilityType:
    def test_carries_no_title_attendee_or_location(self):
        """
        The type is the enforcement. A busy reply is posted into a channel
        other people read, and "in a 1:1 with Priya re: restructure" must not
        be able to reach it -- there is no field to leak it through.
        """
        fields = set(schemas.Availability.model_fields)

        assert fields == {"state", "until", "next_free"}


class TestCurrentStatus:
    def test_a_meeting_now_reads_busy_with_its_end_time(self):
        now = datetime(2026, 3, 4, 11, 0, tzinfo=UTC)
        status = availability.current_status(
            [event("Sync", start=now - timedelta(minutes=15))],
            settings(), "UTC", now=now,
        )

        assert status.state == "busy"
        assert status.until == now + timedelta(minutes=45)

    def test_a_focus_block_reads_focus_not_busy(self):
        """A meeting has an end time; a focus block is a choice."""
        now = datetime(2026, 3, 4, 11, 0, tzinfo=UTC)
        status = availability.current_status(
            [event("Focus time", start=now - timedelta(minutes=10), attendees=1)],
            settings(), "UTC", now=now,
        )

        assert status.state == "focus"

    def test_an_empty_calendar_in_hours_reads_free(self):
        now = datetime(2026, 3, 4, 11, 0, tzinfo=UTC)

        assert availability.current_status(
            [], settings(), "UTC", now=now
        ).state == "free"

    def test_outside_working_hours_reads_off_hours(self):
        now = datetime(2026, 3, 4, 22, 0, tzinfo=UTC)
        status = availability.current_status([], settings(), "UTC", now=now)

        assert status.state == "off_hours"
        assert status.next_free is not None

    def test_a_weekend_is_off_hours(self):
        saturday = datetime(2026, 3, 7, 11, 0, tzinfo=UTC)

        assert availability.current_status(
            [], settings(), "UTC", now=saturday
        ).state == "off_hours"

    def test_back_to_back_meetings_report_the_real_gap(self):
        """
        Reporting the end of the current meeting when the next starts
        immediately afterwards is worse than saying nothing: somebody waits for
        a gap that is not there.
        """
        now = datetime(2026, 3, 4, 11, 0, tzinfo=UTC)
        first = event("One", start=now - timedelta(minutes=30))
        second = event("Two", start=first.end)

        status = availability.current_status(
            [first, second], settings(), "UTC", now=now
        )

        assert status.until == first.end
        assert status.next_free == second.end

    def test_double_booked_is_busy_until_the_later_one_ends(self):
        now = datetime(2026, 3, 4, 11, 0, tzinfo=UTC)
        short = event("Short", start=now - timedelta(minutes=10), minutes=20)
        long = event("Long", start=now - timedelta(minutes=10), minutes=90)

        status = availability.current_status(
            [short, long], settings(), "UTC", now=now
        )

        assert status.until == long.end

    def test_the_half_hour_offset_is_handled(self):
        """
        The default zone is UTC+05:30. 05:00 UTC is 10:30 IST -- inside the
        working day -- and naive hour arithmetic gets this wrong.
        """
        moment = datetime(2026, 3, 4, 5, 0, tzinfo=UTC)

        assert availability.within_working_hours(
            moment, settings(), "Asia/Kolkata"
        ) is True
        assert availability.within_working_hours(
            moment, settings(), "UTC"
        ) is False


class TestUnreadableCalendar:
    @pytest.mark.asyncio
    async def test_an_unreadable_calendar_reads_free_never_busy(self, db, monkeypatch):
        """
        A broken token and a real meeting produce identical silence, and
        defaulting to busy fails in the direction that makes the user
        unreachable -- the responder tells everybody they are in a meeting they
        are not in, and the reply they were waiting for never comes.
        """
        user = models.User(email="u@x.com", hashed_password="x", timezone="UTC")
        db.add(user)
        db.commit()

        def explode(db, owner_id):
            raise RuntimeError("token expired")

        monkeypatch.setattr(
            "app.dependencies.get_integration_configs", explode
        )

        status = await availability.for_user(db, user, settings())
        assert status.state == "free"


class TestImportance:
    def test_a_reviewer_mid_round_is_important_deterministically(self, db):
        """
        The clearest case there is: they are blocked on you by construction,
        and the review loop exists to keep that from stalling.
        """
        db.add(models.PRReview(
            repo="acme/api", pr_number=1, state="changes_requested",
            last_reviewer="lead", owner_id=1,
        ))
        db.commit()

        assert interruption.sender_is_reviewer(db, 1, "lead") is True
        assert interruption.sender_is_reviewer(db, 1, "@lead") is True
        assert interruption.sender_is_reviewer(db, 1, "someone-else") is False

    def test_another_users_reviews_are_never_consulted(self, db):
        db.add(models.PRReview(
            repo="acme/api", pr_number=1, state="changes_requested",
            last_reviewer="lead", owner_id=2,
        ))
        db.commit()

        assert interruption.sender_is_reviewer(db, 1, "lead") is False

    @pytest.mark.parametrize("text,expected", [
        ("any update on LOC-42?", ["LOC-42"]),
        ("see acme/api#7 please", ["acme/api#7"]),
        ("nothing here", []),
        ("LOC-42 and LOC-42 again", ["LOC-42"]),
    ])
    def test_work_item_keys_are_found_by_a_regex_not_a_model(self, text, expected):
        """
        The same reasoning as the `@locus ignore` parser: this decides whether
        somebody's message interrupts a focus block, and a model deciding that
        is a model deciding when to interrupt you.
        """
        assert interruption.find_work_item_keys(text) == expected

    @pytest.mark.asyncio
    async def test_the_deterministic_tests_short_circuit_the_model(self, db, monkeypatch):
        db.add(models.PRReview(
            repo="acme/api", pr_number=1, state="approved",
            last_reviewer="lead", owner_id=1,
        ))
        db.commit()

        async def never(text):
            raise AssertionError("the classifier should not have been consulted")

        monkeypatch.setattr(interruption, "classify", never)

        importance, source = await interruption.judge(
            db, owner_id=1, participant="lead", text="ping"
        )

        assert importance == "important"
        assert source == "reviewer"

    @pytest.mark.asyncio
    async def test_unclear_resolves_to_routine(self, monkeypatch):
        """
        The busy reply goes out either way, so the two failure modes are "an
        important message got a plain reply" and "a focus block was interrupted
        over nothing". The second is worse.
        """
        class Response:
            content = '{"importance": "unclear", "reason": "cannot tell"}'

        class LLM:
            async def ainvoke(self, prompt):
                return Response()

        monkeypatch.setattr("app.services.llm.get_llm", lambda **kw: LLM())

        importance, _ = await interruption.classify("hey")
        assert importance == "routine"

    @pytest.mark.asyncio
    async def test_an_unavailable_model_resolves_to_routine(self, monkeypatch):
        def explode(**kwargs):
            raise RuntimeError("no model loaded")

        monkeypatch.setattr("app.services.llm.get_llm", explode)

        importance, reason = await interruption.classify("hey")
        assert importance == "routine"
        assert "unavailable" in reason


class TestReply:
    def test_names_its_timezone(self):
        """
        "booked until 15:30 IST", never "until 15:30". `google_meet` stamping
        "UTC" onto server-local times is the bug that rule was written from.
        """
        until = datetime(2026, 3, 4, 10, 0, tzinfo=UTC)
        body = interruption.compose_reply(
            schemas.Availability(state="busy", until=until),
            timezone="Asia/Kolkata", importance="routine",
        )

        assert "15:30" in body
        assert "IST" in body or "Asia/Kolkata" in body

    def test_carries_no_event_detail(self):
        """State and end time only."""
        until = datetime(2026, 3, 4, 10, 0, tzinfo=UTC)
        body = interruption.compose_reply(
            schemas.Availability(state="busy", until=until),
            timezone="UTC", importance="routine",
        )

        assert "meeting" in body.lower()
        assert "1:1" not in body and "Priya" not in body

    def test_focus_and_busy_read_differently(self):
        until = datetime(2026, 3, 4, 10, 0, tzinfo=UTC)

        busy = interruption.compose_reply(
            schemas.Availability(state="busy", until=until),
            timezone="UTC", importance="routine",
        )
        focus = interruption.compose_reply(
            schemas.Availability(state="focus", until=until),
            timezone="UTC", importance="routine",
        )

        assert busy != focus
        assert "heads-down" in focus

    def test_off_hours_offers_no_reschedule(self):
        """There is nothing to reschedule around."""
        body = interruption.compose_reply(
            schemas.Availability(
                state="off_hours",
                next_free=datetime(2026, 3, 5, 4, 0, tzinfo=UTC),
            ),
            timezone="UTC", importance="important",
            slots=[scheduler_module.Slot(
                start=datetime(2026, 3, 5, 5, 0, tzinfo=UTC),
                end=datetime(2026, 3, 5, 5, 30, tzinfo=UTC),
            )],
        )

        assert "open:" not in body

    def test_slots_are_offered_as_options_never_as_a_booking(self):
        """
        Writing to somebody else's calendar from an automated reply is a write
        nobody approved.
        """
        until = datetime(2026, 3, 4, 10, 0, tzinfo=UTC)
        body = interruption.compose_reply(
            schemas.Availability(state="focus", until=until),
            timezone="UTC", importance="important",
            slots=[scheduler_module.Slot(
                start=datetime(2026, 3, 4, 11, 0, tzinfo=UTC),
                end=datetime(2026, 3, 4, 11, 30, tzinfo=UTC),
            )],
        )

        assert "these are open" in body
        assert "booked you in" not in body.lower()

    def test_a_routine_message_gets_no_slots(self):
        until = datetime(2026, 3, 4, 10, 0, tzinfo=UTC)
        body = interruption.compose_reply(
            schemas.Availability(state="busy", until=until),
            timezone="UTC", importance="routine",
            slots=[scheduler_module.Slot(
                start=datetime(2026, 3, 4, 11, 0, tzinfo=UTC),
                end=datetime(2026, 3, 4, 11, 30, tzinfo=UTC),
            )],
        )

        assert "open" not in body


class TestCooldown:
    def _record(self, db, **kwargs):
        base = dict(
            owner_id=1, participant="someone", thread_ts="1.1",
            channel="C1", availability=schemas.Availability(state="busy"),
            importance="routine", importance_source="classifier",
            replied=True, reply_body="in a meeting", excerpt="hey",
        )
        base.update(kwargs)
        return interruption.record(db, **base)

    def test_one_reply_per_thread_per_day(self, db):
        """
        Load-bearing, not polish. A repeating auto-responder gets the bot
        muted, and a muted bot takes the review pings with it.
        """
        self._record(db)

        assert interruption.already_replied(
            db, owner_id=1, thread_ts="1.1", channel="C1"
        ) is True

    def test_a_different_thread_is_not_on_cooldown(self, db):
        self._record(db)

        assert interruption.already_replied(
            db, owner_id=1, thread_ts="2.2", channel="C1"
        ) is False

    def test_a_reply_that_never_sent_does_not_start_the_cooldown(self, db):
        """
        A Slack outage must not silence the responder for a day.
        """
        self._record(db, replied=False, reply_body=None)

        assert interruption.already_replied(
            db, owner_id=1, thread_ts="1.1", channel="C1"
        ) is False

    def test_the_cooldown_expires(self, db):
        row = self._record(db)
        row.occurred_at = datetime.now(UTC) - timedelta(hours=30)
        db.commit()

        assert interruption.already_replied(
            db, owner_id=1, thread_ts="1.1", channel="C1"
        ) is False

    def test_another_users_reply_is_not_your_cooldown(self, db):
        self._record(db, owner_id=2)

        assert interruption.already_replied(
            db, owner_id=1, thread_ts="1.1", channel="C1"
        ) is False

    def test_a_channel_mention_with_no_thread_uses_the_channel(self, db):
        """A top-level mention carries no thread_ts, and is the ordinary case."""
        self._record(db, thread_ts=None)

        assert interruption.already_replied(
            db, owner_id=1, thread_ts=None, channel="C1"
        ) is True
        assert interruption.already_replied(
            db, owner_id=1, thread_ts=None, channel="C2"
        ) is False


class TestRecord:
    def test_stores_the_reply_as_sent(self, db):
        """
        A reconstruction drifts from what the channel actually saw, which makes
        the record worse than useless.
        """
        row = interruption.record(
            db, owner_id=1, participant="someone", thread_ts="1.1",
            channel="C1", availability=schemas.Availability(state="focus"),
            importance="important", importance_source="reviewer",
            replied=True, reply_body="Thanks — heads-down until 15:30 IST.",
            excerpt="are you around?",
        )

        assert row.reply_body == "Thanks — heads-down until 15:30 IST."
        assert row.importance_source == "reviewer"

    def test_an_unanswered_interruption_is_still_recorded(self, db):
        """The strip should show that somebody reached them either way."""
        row = interruption.record(
            db, owner_id=1, participant="someone", thread_ts="1.1",
            channel="C1", availability=schemas.Availability(state="busy"),
            importance="routine", importance_source="classifier",
            replied=False, reply_body=None, excerpt="hey",
        )

        assert row.replied == 0
        assert row.excerpt == "hey"
