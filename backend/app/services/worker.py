"""
Background Worker
Polls for queued PR analysis jobs and runs them.

A simple in-process poller, appropriate for a single instance. If Locus is ever
run multi-instance, this needs a lock (SELECT ... FOR UPDATE SKIP LOCKED) or a
real queue, otherwise two workers will pick up the same job.
"""

import asyncio
import logging

from app import models, schemas
from app.database import SessionLocal

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 5


async def _claim_next_job() -> int | None:
    """Return the id of the oldest queued job, or None."""
    db = SessionLocal()
    try:
        job = (
            db.query(models.PRJob)
            .filter(models.PRJob.status == schemas.PRJobStatus.queued.value)
            .order_by(models.PRJob.created_at)
            .first()
        )
        return job.id if job else None
    finally:
        db.close()


async def worker_loop() -> None:
    """Run queued PR jobs until cancelled."""
    # Imported here to avoid a circular import at module load.
    from app.routers.webhooks import run_pr_job

    logger.info("PR analysis worker started")

    while True:
        try:
            job_id = await _claim_next_job()
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


async def qa_email_loop() -> None:
    """
    Poll Gmail for QA replies.

    Kept separate from the job worker: that loop spins every few seconds
    looking for queued work, while this one should touch the Gmail API only
    every few minutes.
    """
    from app.services.qa_email_poller import POLL_INTERVAL_SECONDS as EMAIL_INTERVAL
    from app.services.qa_email_poller import poll_once

    logger.info("QA email poller started")

    while True:
        try:
            await asyncio.sleep(EMAIL_INTERVAL)
            processed = await poll_once()
            if processed:
                logger.info("Processed %s QA email reply(ies)", processed)

        except asyncio.CancelledError:
            logger.info("QA email poller stopping")
            raise
        except Exception:
            logger.exception("QA email poll failed")
