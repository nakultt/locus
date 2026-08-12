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
