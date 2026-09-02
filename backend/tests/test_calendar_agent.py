"""
The calendar agent: the scheduler, running on its own rather than on request.

The solver and the endpoints were built already and are entirely
request-driven. This phase adds the trigger, and the rules being tested are
about what a trigger is allowed to do without being asked: propose, never act,
and never repeat itself.
"""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models, schemas
from app.services.scheduling import calendar_agent


@pytest.fixture
def db(tmp_path):
    from app.core.database import Base

    engine = create_engine(
        f"sqlite:///{tmp_path}/c.db", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def event(title: str, *, hours_from_now: float, duration=1.0, attendees=1,
          external=False) -> schemas.ScheduledEvent:
    start = datetime.now(UTC) + timedelta(hours=hours_from_now)
    return schemas.ScheduledEvent(
        event_id=title.lower().replace(" ", "-"),
        title=title,
        start=start,
        end=start + timedelta(hours=duration),
        attendee_count=attendees,
        has_external_attendees=external,
    )


def proposal(**kwargs) -> schemas.ScheduleProposal:
    base = dict(trigger="Double-booked: A and B", timezone="Asia/Kolkata")
    base.update(kwargs)
    return schemas.ScheduleProposal(**base)


class TestSettings:
    def test_everything_dangerous_is_off_by_default(self, db):
        """
        `enabled`, because a feature that starts touching a calendar unasked is
        the worst first impression available. `auto_apply`, because a moved
        meeting is visible to everyone invited. Both auto-replies, because they
        post to real people.
        """
        row = calendar_agent.get_settings(db, owner_id=1)

        assert not row.enabled
        assert not row.auto_apply
        assert not row.auto_reply_invites
        assert not row.auto_reply_busy

    def test_reading_a_setting_never_writes_one(self, db):
        """
        The same rule the task board follows: a read that creates a row means
        a refresh creates rows for everybody.
        """
        calendar_agent.get_settings(db, owner_id=1)

        assert db.query(models.TimeAgentSettings).count() == 0

    def test_working_hours_carry_a_half_hour_offset_by_default(self, db):
        """
        The default zone is UTC+05:30. Nothing here is an integer offset,
        because the half hour breaks naive hour arithmetic.
        """
        row = calendar_agent.get_settings(db, owner_id=1)

        assert row.working_hours_start == "09:30"
        assert row.working_hours_end == "18:30"

    def test_only_enabled_users_are_swept(self, db):
        db.add(models.TimeAgentSettings(owner_id=1, enabled=1))
        db.add(models.TimeAgentSettings(owner_id=2, enabled=0))
        db.commit()

        assert [s.owner_id for s in calendar_agent.enabled_users(db)] == [1]


class TestStoreProposal:
    def test_a_proposal_that_changes_nothing_is_not_stored(self, db):
        """
        The board would otherwise accumulate a "nothing needs to change" card
        every sweep -- the same failure as a "0 resolved, 0 new" findings line
        on every push, which trains people to skip the section that matters.
        """
        assert calendar_agent.store_proposal(
            db, owner_id=1, proposal=proposal(summary="Everything fits.")
        ) is None
        assert db.query(models.ScheduleProposalRecord).count() == 0

    def test_a_blocked_conflict_is_stored_even_with_no_moves(self, db):
        """
        A conflict the solver could not resolve is the most important thing it
        found, not the least. Anything with external attendees lands here.
        """
        record = calendar_agent.store_proposal(
            db, owner_id=1,
            proposal=proposal(blocked=["'Board review' has external attendees"]),
        )

        assert record is not None
        assert record.state == "pending"

    def test_the_same_proposal_twice_is_stored_once(self, db):
        """
        The sweep runs every half hour and the conflict it found at nine is the
        same conflict at half past.
        """
        for _ in range(3):
            calendar_agent.store_proposal(
                db, owner_id=1, proposal=proposal(blocked=["clash"])
            )

        assert db.query(models.ScheduleProposalRecord).count() == 1

    def test_a_changed_plan_supersedes_rather_than_duplicating(self, db):
        """The board shows one live plan for one conflict."""
        calendar_agent.store_proposal(
            db, owner_id=1, proposal=proposal(blocked=["clash"])
        )
        calendar_agent.store_proposal(
            db, owner_id=1, proposal=proposal(blocked=["clash", "and another"])
        )

        states = [r.state for r in db.query(models.ScheduleProposalRecord).all()]
        assert sorted(states) == ["pending", "superseded"]
        assert len(calendar_agent.pending_proposals(db, 1)) == 1


class TestSweep:
    def test_a_clear_calendar_proposes_nothing(self, db):
        settings = models.TimeAgentSettings(owner_id=1, enabled=1)

        records = calendar_agent.sweep_user(
            db, settings,
            [event("Standup", hours_from_now=1),
             event("Review", hours_from_now=3)],
            "Asia/Kolkata",
        )

        assert records == []

    def test_a_double_booking_produces_one_proposal(self, db):
        settings = models.TimeAgentSettings(owner_id=1, enabled=1)

        records = calendar_agent.sweep_user(
            db, settings,
            [event("Focus block", hours_from_now=1, duration=2),
             event("Sync", hours_from_now=1.5)],
            "Asia/Kolkata",
        )

        assert len(records) == 1
        assert "Double-booked" in records[0].trigger

    def test_an_external_meeting_is_reported_blocked_not_moved(self, db):
        """
        `scheduler.classify_event`'s existing behaviour, which this phase must
        not weaken: moving a meeting with external attendees sends invite
        updates to people outside the company.
        """
        settings = models.TimeAgentSettings(owner_id=1, enabled=1)

        records = calendar_agent.sweep_user(
            db, settings,
            [
                event("Customer call", hours_from_now=1, duration=2,
                      attendees=4, external=True),
                event("Board review", hours_from_now=1.5,
                      attendees=5, external=True),
            ],
            "Asia/Kolkata",
        )

        assert records
        plan = calendar_agent.load_proposal(records[0])
        assert not any(m.attendee_count > 1 and m.event_id == "customer-call"
                       for m in plan.moves) or plan.blocked

    def test_sweeping_twice_does_not_duplicate(self, db):
        settings = models.TimeAgentSettings(owner_id=1, enabled=1)
        events = [
            event("Focus block", hours_from_now=1, duration=2),
            event("Sync", hours_from_now=1.5),
        ]

        calendar_agent.sweep_user(db, settings, events, "Asia/Kolkata")
        calendar_agent.sweep_user(db, settings, events, "Asia/Kolkata")

        assert len(calendar_agent.pending_proposals(db, 1)) == 1


class TestLoadProposal:
    def test_the_stored_plan_round_trips(self, db):
        """
        Applying runs what was shown. Recomputing at apply time would silently
        execute a different plan from the one the person approved -- the
        calendar has moved since, which is exactly why they were asked.
        """
        record = calendar_agent.store_proposal(
            db, owner_id=1,
            proposal=proposal(blocked=["one"], summary="Move the focus block"),
        )

        loaded = calendar_agent.load_proposal(record)
        assert loaded.blocked == ["one"]
        assert loaded.summary == "Move the focus block"


# --- API -------------------------------------------------------------------


@pytest.fixture
def client(tmp_path):
    from app import main
    from app.core.database import Base, get_db

    engine = create_engine(
        f"sqlite:///{tmp_path}/api.db", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    main.app.dependency_overrides[get_db] = override
    with TestClient(main.app) as c:
        signup = c.post(
            "/auth/signup", json={"email": "cal@x.com", "password": "secret123"}
        ).json()
        c.headers["Authorization"] = f"Bearer {signup['token']}"
        yield c
    main.app.dependency_overrides.clear()


class TestApi:
    def test_defaults_before_anything_is_saved(self, client):
        body = client.get("/api/schedule/agent").json()

        assert body["enabled"] is False
        assert body["auto_apply"] is False
        assert body["working_hours_start"] == "09:30"

    def test_settings_round_trip(self, client):
        client.put("/api/schedule/agent", json={
            "enabled": True,
            "auto_apply": False,
            "auto_reply_invites": False,
            "auto_reply_busy": True,
            "working_hours_start": "10:00",
            "working_hours_end": "19:00",
            "protect_focus_blocks": True,
        })

        body = client.get("/api/schedule/agent").json()
        assert body["enabled"] is True
        assert body["auto_reply_busy"] is True
        assert body["working_hours_start"] == "10:00"

    def test_a_malformed_time_is_rejected(self, client):
        assert client.put("/api/schedule/agent", json={
            "enabled": True, "working_hours_start": "half nine",
        }).status_code == 422

    def test_no_proposals_before_a_sweep(self, client):
        assert client.get("/api/schedule/proposals").json() == []

    def test_another_users_proposal_is_404_not_403(self, client):
        from app import main
        from app.core.database import get_db

        session = next(main.app.dependency_overrides[get_db]())
        session.add(models.ScheduleProposalRecord(
            owner_id=999, trigger="theirs",
            proposal_json=proposal().model_dump_json(),
        ))
        session.commit()
        their_id = session.query(models.ScheduleProposalRecord).first().id

        assert client.get("/api/schedule/proposals").json() == []
        assert client.delete(f"/api/schedule/proposals/{their_id}").status_code == 404
        assert client.post(
            f"/api/schedule/proposals/{their_id}/apply"
        ).status_code == 404

    def test_dismissing_marks_rather_than_deletes(self, client):
        """Deleted, the next sweep would simply propose it again."""
        from app import main
        from app.core.database import get_db

        session = next(main.app.dependency_overrides[get_db]())
        user_id = session.query(models.User).first().id
        session.add(models.ScheduleProposalRecord(
            owner_id=user_id, trigger="clash",
            proposal_json=proposal(blocked=["x"]).model_dump_json(),
        ))
        session.commit()
        record_id = session.query(models.ScheduleProposalRecord).filter(
            models.ScheduleProposalRecord.owner_id == user_id
        ).first().id

        assert client.delete(f"/api/schedule/proposals/{record_id}").status_code == 204
        assert client.get("/api/schedule/proposals").json() == []

        session.expire_all()
        assert session.query(models.ScheduleProposalRecord).filter(
            models.ScheduleProposalRecord.id == record_id
        ).first().state == "dismissed"

    def test_requires_authentication(self, client):
        assert client.get(
            "/api/schedule/agent", headers={"Authorization": "Bearer bad"}
        ).status_code == 401


class TestSlackMemberId:
    @pytest.mark.asyncio
    async def test_no_token_resolves_to_none(self):
        assert await calendar_agent.resolve_slack_member_id({}) is None

    @pytest.mark.asyncio
    async def test_a_failure_costs_mention_matching_not_the_save(self, monkeypatch):
        """
        Mention matching is a feature of the busy reply, not a prerequisite for
        configuring working hours.
        """
        import httpx

        class Boom:
            async def __aenter__(self):
                raise RuntimeError("Slack is down")

            async def __aexit__(self, *args):
                return False

        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: Boom())

        assert await calendar_agent.resolve_slack_member_id(
            {"bot_token": "x"}
        ) is None
