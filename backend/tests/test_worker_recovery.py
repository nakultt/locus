"""
The worker loop: claiming jobs, and rescuing the ones a crash dropped.

Two failures this covers, both silent before it existed:

**An orphaned job is never retried.** The GitHub webhook is answered the moment
the job is queued, so nothing sits behind it waiting. A job left `running` by a
process that died is simply never analyzed, and the pull request gets no
comment -- with no error anywhere to say so.

**Two workers claiming the same job analyze it twice.** That posts the PR
comment twice and, on a merge job, notifies QA twice. The claim is a
conditional UPDATE so the database picks one winner.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models, schemas
from app.core.database import Base
from app.services import worker


@pytest.fixture
def session_factory(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr(worker, "SessionLocal", Session)

    db = Session()
    db.add(models.User(id=1, email="d@a.com", hashed_password="x", timezone="UTC"))
    db.commit()
    db.close()
    return Session


def add_job(Session, **overrides) -> int:
    defaults = dict(
        repo="acme/widget", pr_number=7, action="opened",
        status=schemas.PRJobStatus.queued.value, owner_id=1,
    )
    db = Session()
    try:
        job = models.PRJob(**{**defaults, **overrides})
        db.add(job)
        db.commit()
        return job.id
    finally:
        db.close()


def status_of(Session, job_id: int) -> str:
    db = Session()
    try:
        return db.query(models.PRJob).filter(models.PRJob.id == job_id).one().status
    finally:
        db.close()


class TestStaleJobRecovery:
    def test_an_orphaned_job_is_requeued(self, session_factory):
        """
        The case that made this necessary: the process died mid-analysis. The
        webhook was answered long ago, so without recovery this pull request
        is never analyzed and nothing reports it.
        """
        job_id = add_job(
            session_factory,
            status=schemas.PRJobStatus.running.value,
            started_at=datetime.now(UTC) - timedelta(hours=2),
        )

        assert worker.recover_stale_jobs() == 1
        assert status_of(session_factory, job_id) == schemas.PRJobStatus.queued.value

    def test_a_job_still_being_worked_on_is_left_alone(self, session_factory):
        """
        Reclaiming a live job would run the analysis twice and post its
        comment twice. The pipeline takes 30-60s; the window is 30 minutes.
        """
        job_id = add_job(
            session_factory,
            status=schemas.PRJobStatus.running.value,
            started_at=datetime.now(UTC) - timedelta(seconds=45),
        )

        assert worker.recover_stale_jobs() == 0
        assert status_of(session_factory, job_id) == schemas.PRJobStatus.running.value

    def test_a_job_claimed_before_started_at_existed_is_recoverable(
        self, session_factory
    ):
        """Rows predating the column have a null `started_at`."""
        job_id = add_job(
            session_factory,
            status=schemas.PRJobStatus.running.value,
            started_at=None,
        )

        assert worker.recover_stale_jobs() == 1
        assert status_of(session_factory, job_id) == schemas.PRJobStatus.queued.value

    def test_a_job_that_keeps_crashing_is_failed_not_requeued(self, session_factory):
        """
        Recovery rescues work a crash dropped. A job that reliably kills the
        worker would otherwise be requeued and re-crash forever -- an
        unkillable loop is worse than one dropped job.
        """
        job_id = add_job(
            session_factory,
            status=schemas.PRJobStatus.running.value,
            started_at=datetime.now(UTC) - timedelta(hours=2),
            attempts=worker.MAX_ATTEMPTS,
        )

        assert worker.recover_stale_jobs() == 0
        assert status_of(session_factory, job_id) == schemas.PRJobStatus.failed.value

    def test_a_failed_job_says_why(self, session_factory):
        """A job that vanishes with no explanation is the thing being fixed."""
        job_id = add_job(
            session_factory,
            status=schemas.PRJobStatus.running.value,
            started_at=datetime.now(UTC) - timedelta(hours=2),
            attempts=worker.MAX_ATTEMPTS,
        )
        worker.recover_stale_jobs()

        db = session_factory()
        try:
            job = db.query(models.PRJob).filter(models.PRJob.id == job_id).one()
            assert job.error
            assert job.completed_at is not None
        finally:
            db.close()

    def test_completed_jobs_are_untouched(self, session_factory):
        job_id = add_job(
            session_factory,
            status=schemas.PRJobStatus.completed.value,
            started_at=datetime.now(UTC) - timedelta(days=3),
        )

        assert worker.recover_stale_jobs() == 0
        assert status_of(session_factory, job_id) == schemas.PRJobStatus.completed.value


class TestAtomicClaim:
    def test_claiming_marks_the_job_running_and_counts_the_attempt(
        self, session_factory
    ):
        job_id = add_job(session_factory)

        assert worker._claim_next_job() == job_id

        db = session_factory()
        try:
            job = db.query(models.PRJob).filter(models.PRJob.id == job_id).one()
            assert job.status == schemas.PRJobStatus.running.value
            assert job.attempts == 1
            assert job.started_at is not None
        finally:
            db.close()

    def test_a_job_is_only_claimed_once(self, session_factory):
        """
        Two workers racing produce one winner and one miss. Both proceeding
        would post the PR comment twice, and on a merge job notify QA twice.
        """
        add_job(session_factory)

        first = worker._claim_next_job()
        second = worker._claim_next_job()

        assert first is not None
        assert second is None

    def test_oldest_job_goes_first(self, session_factory):
        older = add_job(
            session_factory, pr_number=1,
            created_at=datetime.now(UTC) - timedelta(minutes=10),
        )
        add_job(
            session_factory, pr_number=2,
            created_at=datetime.now(UTC),
        )

        assert worker._claim_next_job() == older

    def test_an_empty_queue_claims_nothing(self, session_factory):
        assert worker._claim_next_job() is None

    def test_a_recovered_job_is_claimable_again(self, session_factory):
        """Recovery is only useful if the rescued job actually gets run."""
        # Claimed once already by the worker that then died.
        job_id = add_job(
            session_factory,
            status=schemas.PRJobStatus.running.value,
            started_at=datetime.now(UTC) - timedelta(hours=2),
            attempts=1,
        )
        worker.recover_stale_jobs()

        assert worker._claim_next_job() == job_id

        db = session_factory()
        try:
            job = db.query(models.PRJob).filter(models.PRJob.id == job_id).one()
            # The earlier attempt is still counted, so a job cannot be
            # rescued indefinitely.
            assert job.attempts == 2
        finally:
            db.close()
