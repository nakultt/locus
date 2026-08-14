"""
Integration health, and the loops that record it.

The background loops swallow their own failures on purpose -- one dead
integration must not stop the others. The cost is silence: the QA poller logs a
Gmail failure at debug level and continues, so a token that expired days ago
shows up only as QA replies no longer arriving, which reads as nobody replying.

Two rules here:

**Recording never fails the work it describes.** Same as `comms_log`: a poll
that genuinely succeeded must not be reported as failed because the health row
could not be written.

**One failure is not "broken".** A token refresh races, a request times out.
Only a streak is a condition someone has to act on.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.database import Base
from app.services import integration_health

OWNER = 1


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    session.add(models.User(
        id=OWNER, email="d@a.com", hashed_password="x", timezone="UTC"))
    session.commit()
    try:
        yield session
    finally:
        session.close()


class TestRecording:
    def test_a_failure_is_recorded_with_its_reason(self, db):
        integration_health.record_failure(
            db, owner_id=OWNER, service="gmail", error="invalid_grant"
        )
        entry = integration_health.summary(db, owner_id=OWNER)[0]

        assert entry["service"] == "gmail"
        assert entry["consecutive_failures"] == 1
        assert "invalid_grant" in entry["last_error"]
        assert entry["last_failure_at"] is not None

    def test_one_failure_is_not_yet_unhealthy(self, db):
        """A token refresh races; a single miss is ordinary."""
        integration_health.record_failure(
            db, owner_id=OWNER, service="gmail", error="timeout"
        )
        assert integration_health.summary(db, owner_id=OWNER)[0]["healthy"] is True

    def test_a_streak_is_unhealthy(self, db):
        for _ in range(integration_health.UNHEALTHY_AFTER):
            integration_health.record_failure(
                db, owner_id=OWNER, service="gmail", error="invalid_grant"
            )

        entry = integration_health.summary(db, owner_id=OWNER)[0]
        assert entry["healthy"] is False
        assert entry["consecutive_failures"] == integration_health.UNHEALTHY_AFTER

    def test_a_success_clears_the_streak(self, db):
        """A service that works is healthy regardless of an hour ago."""
        for _ in range(5):
            integration_health.record_failure(
                db, owner_id=OWNER, service="gmail", error="boom"
            )
        integration_health.record_success(db, owner_id=OWNER, service="gmail")

        entry = integration_health.summary(db, owner_id=OWNER)[0]
        assert entry["healthy"] is True
        assert entry["consecutive_failures"] == 0
        assert entry["last_error"] is None
        assert entry["last_success_at"] is not None

    def test_services_are_tracked_separately(self, db):
        integration_health.record_failure(
            db, owner_id=OWNER, service="gmail", error="boom"
        )
        integration_health.record_success(db, owner_id=OWNER, service="slack")

        by_service = {
            e["service"]: e
            for e in integration_health.summary(db, owner_id=OWNER)
        }
        assert by_service["gmail"]["consecutive_failures"] == 1
        assert by_service["slack"]["consecutive_failures"] == 0

    def test_health_does_not_leak_across_users(self, db):
        integration_health.record_failure(
            db, owner_id=OWNER, service="gmail", error="boom"
        )
        assert integration_health.summary(db, owner_id=2) == []

    def test_a_service_never_called_is_absent_not_healthy(self, db):
        """
        Never attempted is not the same as working. Reporting it healthy would
        be a claim nothing supports.
        """
        assert integration_health.summary(db, owner_id=OWNER) == []

    def test_a_long_error_is_truncated(self, db):
        integration_health.record_failure(
            db, owner_id=OWNER, service="gmail", error="x" * 5000
        )
        entry = integration_health.summary(db, owner_id=OWNER)[0]

        assert len(entry["last_error"]) <= 1000


class TestRecordingNeverFailsTheWork:
    def test_a_broken_session_does_not_raise(self, db):
        """
        A poll that genuinely succeeded must not be reported as failed
        because the record could not be written.
        """
        db.close()  # Any use now raises.

        # Neither call may propagate.
        integration_health.record_success(db, owner_id=OWNER, service="gmail")
        integration_health.record_failure(
            db, owner_id=OWNER, service="gmail", error="boom"
        )


class TestQAPollerRecordsHealth:
    """
    The poller is the reason this exists: its Gmail failure was logged at
    debug level and otherwise invisible.
    """

    @pytest.mark.asyncio
    async def test_a_gmail_failure_is_recorded(self, db, monkeypatch):
        from app import crud
        from app.services import qa_email_poller

        db.add(models.QAThread(
            repo="acme/api", pr_number=7, pr_url="u", slack_channel="#qa",
            slack_thread_ts="1", email_message_id="<m@x>", resolved=0,
            owner_id=OWNER,
        ))
        db.commit()

        monkeypatch.setattr(
            qa_email_poller, "SessionLocal", lambda: db
        )
        monkeypatch.setattr(
            crud, "get_integration_credentials",
            lambda *a, **kw: {"access_token": "tok"},
        )

        async def boom(*_a, **_kw):
            raise RuntimeError("invalid_grant")

        monkeypatch.setattr(qa_email_poller, "fetch_replies", boom)

        assert await qa_email_poller.poll_once() == 0

        entry = integration_health.summary(db, owner_id=OWNER)[0]
        assert entry["service"] == "gmail"
        assert entry["consecutive_failures"] == 1
        assert "invalid_grant" in entry["last_error"]

    @pytest.mark.asyncio
    async def test_a_working_poll_records_success(self, db, monkeypatch):
        from app import crud
        from app.services import qa_email_poller

        db.add(models.QAThread(
            repo="acme/api", pr_number=7, pr_url="u", slack_channel="#qa",
            slack_thread_ts="1", email_message_id="<m@x>", resolved=0,
            owner_id=OWNER,
        ))
        db.commit()

        monkeypatch.setattr(qa_email_poller, "SessionLocal", lambda: db)
        monkeypatch.setattr(
            crud, "get_integration_credentials",
            lambda *a, **kw: {"access_token": "tok"},
        )

        async def none_waiting(*_a, **_kw):
            return []

        monkeypatch.setattr(qa_email_poller, "fetch_replies", none_waiting)

        await qa_email_poller.poll_once()

        entry = integration_health.summary(db, owner_id=OWNER)[0]
        assert entry["healthy"] is True
        assert entry["last_success_at"] is not None
