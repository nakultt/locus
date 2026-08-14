"""
Background Worker
Polls for queued PR analysis jobs and runs them.

The claim is atomic: a conditional UPDATE moves `queued` -> `running` and only
the worker whose UPDATE reported a row proceeds. Two workers racing for the
same job therefore produce one winner and one miss rather than two analyses of
the same pull request -- which would post the PR comment twice and, on a merge
job, notify QA twice.

Jobs left `running` by a crashed or restarted process are reclaimed on startup
and by a periodic sweep. Without that they are abandoned in place: the webhook
that queued the job has already been answered, so nothing will ever re-queue
it, and the pull request is silently never analyzed.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_

from app import models, schemas
from app.database import SessionLocal

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 5

# How long a job may sit in `running` before it is presumed orphaned. The
# pipeline takes 30-60s and the LLM timeout is 600s, so this has to clear the
# slowest legitimate run by a wide margin -- reclaiming a job that is still
# being worked on would double-post its comment.
STALE_JOB_MINUTES = 30

# How often to look for orphans. Startup catches the restart case; this
# catches a worker that died without the process going down with it.
RECOVERY_INTERVAL_SECONDS = 300

# A job that has been picked up this many times without completing is left
# alone. Recovery exists to rescue work a crash dropped; a job that reliably
# kills the worker would otherwise be reclaimed and re-crash forever, and a
# poison job that takes the loop down with it is worse than one dropped job.
MAX_ATTEMPTS = 3


def recover_stale_jobs(stale_minutes: int = STALE_JOB_MINUTES) -> int:
    """
    Return orphaned `running` jobs to the queue.

    A job is orphaned when the process that claimed it died before writing a
    terminal status. Nothing else notices: the GitHub webhook was answered
    when the job was queued, so there is no retry behind it.

    Jobs past `MAX_ATTEMPTS` are failed rather than requeued, so a job that
    crashes the worker cannot be rescued into an infinite loop.

    Returns:
        How many jobs were requeued.
    """
    db = SessionLocal()
    try:
        cutoff = datetime.now(UTC) - timedelta(minutes=stale_minutes)

        # `started_at` is null on jobs claimed before this column existed;
        # fall back to created_at so they are still recoverable.
        stale = (
            db.query(models.PRJob)
            .filter(
                models.PRJob.status == schemas.PRJobStatus.running.value,
                or_(
                    models.PRJob.started_at < cutoff,
                    models.PRJob.started_at.is_(None),
                ),
            )
            .all()
        )

        requeued = 0
        for job in stale:
            if (job.attempts or 0) >= MAX_ATTEMPTS:
                job.status = schemas.PRJobStatus.failed.value
                job.error = (
                    f"Abandoned after {job.attempts} attempts; the worker did "
                    f"not finish this job. See the logs for the run that died."
                )
                job.completed_at = datetime.now(UTC)
                logger.warning(
                    "PR job %s failed permanently after %s attempts",
                    job.id, job.attempts,
                )
                continue

            job.status = schemas.PRJobStatus.queued.value
            requeued += 1
            logger.info(
                "Requeued orphaned PR job %s (attempt %s)", job.id, job.attempts
            )

        db.commit()
        return requeued
    finally:
        db.close()


def _claim_next_job() -> int | None:
    """
    Claim the oldest queued job, atomically.

    The UPDATE carries the `queued` check in its WHERE clause, so the database
    decides the winner. Reading the id and then updating in a second statement
    would let two workers read the same row and both proceed.
    """
    db = SessionLocal()
    try:
        job = (
            db.query(models.PRJob)
            .filter(models.PRJob.status == schemas.PRJobStatus.queued.value)
            .order_by(models.PRJob.created_at)
            .first()
        )
        if job is None:
            return None

        claimed = (
            db.query(models.PRJob)
            .filter(
                models.PRJob.id == job.id,
                # Only one worker can see this row as queued.
                models.PRJob.status == schemas.PRJobStatus.queued.value,
            )
            .update(
                {
                    "status": schemas.PRJobStatus.running.value,
                    "started_at": datetime.now(UTC),
                    "attempts": (job.attempts or 0) + 1,
                },
                synchronize_session=False,
            )
        )
        db.commit()

        # Zero means another worker claimed it between the read and the
        # update. Not an error -- the next poll picks up whatever is left.
        return job.id if claimed else None
    finally:
        db.close()


async def worker_loop() -> None:
    """Run queued PR jobs until cancelled."""
    # Imported here to avoid a circular import at module load.
    from app.routers.webhooks import run_pr_job

    logger.info("PR analysis worker started")

    # Anything left running by the process that died is ours to rescue.
    try:
        recovered = recover_stale_jobs()
        if recovered:
            logger.info("Requeued %s orphaned PR job(s) on startup", recovered)
    except Exception:
        logger.exception("Stale job recovery failed on startup")

    last_recovery = datetime.now(UTC)

    while True:
        try:
            now = datetime.now(UTC)
            if (now - last_recovery).total_seconds() >= RECOVERY_INTERVAL_SECONDS:
                last_recovery = now
                recover_stale_jobs()

            job_id = await asyncio.to_thread(_claim_next_job)
            if job_id is None:
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
                continue

            logger.info("Running PR job %s", job_id)
            await run_pr_job(job_id)

        except asyncio.CancelledError:
            logger.info("PR analysis worker stopping")
            raise
        except Exception:
            # Never let one bad job kill the loop.
            logger.exception("Worker iteration failed")
            await asyncio.sleep(POLL_INTERVAL_SECONDS)


async def merge_gate_loop() -> None:
    """
    Retry auto-merge for approved PRs the gate was not ready to pass.

    Separate from the job worker because it is not driven by queued work: it
    exists precisely for the case where no event will arrive. GitHub emits
    nothing when mergeability finishes computing, so without this an approved
    PR whose first gate read returned `mergeable: null` -- the common case,
    since the approval webhook fires within a second of the click -- would sit
    open forever.
    """
    from app.services.automerge import SWEEP_INTERVAL_SECONDS, sweep_once
    from app.services.locks import MERGE_SWEEP_LOCK, advisory_lock

    logger.info("Auto-merge sweeper started")

    while True:
        try:
            await asyncio.sleep(SWEEP_INTERVAL_SECONDS)

            # One sweeper at a time across every instance. The sweep scans for
            # approved PRs rather than claiming them, so two instances would
            # both match the same rows -- merging once but announcing twice.
            with advisory_lock(MERGE_SWEEP_LOCK) as held:
                if not held:
                    continue
                merged = await sweep_once()

            if merged:
                logger.info("Auto-merge sweep merged %s pull request(s)", merged)

        except asyncio.CancelledError:
            logger.info("Auto-merge sweeper stopping")
            raise
        except Exception:
            logger.exception("Auto-merge sweep failed")


async def qa_email_loop() -> None:
    """
    Poll Gmail for QA replies.

    Kept separate from the job worker: that loop spins every few seconds
    looking for queued work, while this one should touch the Gmail API only
    every few minutes.
    """
    from app.services.locks import QA_POLL_LOCK, advisory_lock
    from app.services.qa_email_poller import POLL_INTERVAL_SECONDS as EMAIL_INTERVAL
    from app.services.qa_email_poller import poll_once

    logger.info("QA email poller started")

    while True:
        try:
            await asyncio.sleep(EMAIL_INTERVAL)

            # One poller at a time. Two instances reading the same mailbox
            # would both see an unread QA reply and both act on it -- posting
            # the QA thread twice and transitioning the ticket twice.
            with advisory_lock(QA_POLL_LOCK) as held:
                if not held:
                    continue
                processed = await poll_once()

            if processed:
                logger.info("Processed %s QA email reply(ies)", processed)

        except asyncio.CancelledError:
            logger.info("QA email poller stopping")
            raise
        except Exception:
            logger.exception("QA email poll failed")
