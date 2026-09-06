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
from app.core.database import SessionLocal

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 5

# How long a job may sit in `running` before it is presumed orphaned. The
# pipeline takes 30-60s and the LLM timeout is 600s, so this has to clear the
# slowest legitimate run by a wide margin -- reclaiming a job that is still
# being worked on would double-post its comment.
STALE_JOB_MINUTES = 30

# Added to the run's own wall clock before an authoring attempt still marked
# `running` is treated as interrupted. A margin rather than an exact match,
# because firing early would mark a live run as failed and let the next event
# start a second one against the same branch -- the duplicate-pull-request
# failure, arriving from a new direction.
STALE_ATTEMPT_MARGIN_MINUTES = 10

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



def recover_stale_attempts(stale_minutes: int | None = None) -> int:
    """
    Fail authoring attempts left `running` by a process that died.

    `begin_attempt` writes the `running` row *before* the driver is invoked,
    which is what lets the board say "the agent is writing this" during the ten
    minutes a run takes. The cost is that a process killed mid-run -- a restart,
    a crash, someone stopping it -- leaves that row `running` for good. Nothing
    else notices: unlike a PR job there is no queue behind it, and the attempt
    was already spent.

    Two things go wrong when it is not cleaned up, and the second is worse. The
    card reads "Agent working" indefinitely, so a person waits on a run that
    ended hours ago. And a stale `running` row is indistinguishable from a live
    one, which is exactly the "looks like it is working" failure this codebase
    keeps finding -- here with the twist that the honest state, a spent attempt
    with no pull request, is the one being hidden.

    Failed rather than requeued, unlike `recover_stale_jobs`. A pull request is
    something a person is asked to read, and re-running an attempt nobody
    watched could open one from a half-finished worktree; the bound has already
    been spent either way, so the correct repair is to record what happened and
    let the ordinary triggers decide whether to try again.

    The cutoff is the account's own timeout plus a margin, because a legitimate
    run is bounded by exactly that wall clock -- anything past it either
    finished and failed to say so, or was killed. Falling back to the
    deployment default when no account is bound keeps this working for a
    process that has never resolved a user's runtime.
    """
    from app.services.authoring import agent_runtime
    from app.services.authoring.opencode_driver import TIMEOUT_SECONDS

    if stale_minutes is None:
        # A generous margin over the wall clock a run is allowed. A recovery
        # that fires early would mark a *live* run as failed and let the next
        # event start a second one against the same branch.
        stale_minutes = int(
            agent_runtime.timeout_seconds(TIMEOUT_SECONDS) / 60
        ) + STALE_ATTEMPT_MARGIN_MINUTES

    cutoff = datetime.now(UTC) - timedelta(minutes=stale_minutes)
    db = SessionLocal()
    recovered = 0

    try:
        stale = (
            db.query(models.AuthoringAttempt)
            .filter(
                models.AuthoringAttempt.state == "running",
                models.AuthoringAttempt.created_at < cutoff,
            )
            .all()
        )
        for attempt in stale:
            attempt.state = "finished"
            attempt.opened = 0
            # Said plainly, because "why did this attempt fail" is answered
            # from this field in the UI and "no error" on a spent attempt reads
            # as a run that produced nothing on purpose.
            attempt.error = (
                f"Interrupted: the run was still marked running after "
                f"{stale_minutes} minutes, so the process handling it did not "
                "finish. The attempt was spent."
            )
            recovered += 1

        if recovered:
            db.commit()
            logger.info("Recovered %s interrupted authoring attempt(s)", recovered)
    except Exception:
        db.rollback()
        logger.exception("Could not recover interrupted authoring attempts")
        recovered = 0
    finally:
        db.close()

    return recovered


async def worker_loop() -> None:
    """Run queued PR jobs until cancelled."""
    # Imported here to avoid a circular import at module load.
    from app.routers.webhooks import run_pr_job

    logger.info("PR analysis worker started")

    # Anything left running by the process that died is ours to rescue.
    try:
        recovered = recover_stale_jobs()
        recover_stale_attempts()
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
                recover_stale_attempts()

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
    from app.core.locks import MERGE_SWEEP_LOCK, advisory_lock
    from app.services.pipeline.automerge import SWEEP_INTERVAL_SECONDS, sweep_once

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
    from app.core.locks import QA_POLL_LOCK, advisory_lock
    from app.services.pipeline.qa_email_poller import POLL_INTERVAL_SECONDS as EMAIL_INTERVAL
    from app.services.pipeline.qa_email_poller import poll_once

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


async def calendar_agent_loop() -> None:
    """
    Sweep enabled users' calendars for conflicts and store proposals.

    The fourth loop. Its interval is in minutes rather than seconds: the
    ceiling on how fast a calendar changes is far below the ceiling on how fast
    Google rate-limits, and every iteration costs a Calendar call per enabled
    user.

    Propose-only unless the user turned `auto_apply` on. A moved meeting is
    visible to everyone invited, which is why the default is a plan waiting in
    the UI and `POST /schedule/apply` executing it unchanged.
    """
    from app.core.locks import CALENDAR_LOCK, advisory_lock
    from app.services.scheduling.calendar_agent import TICK_MINUTES, sweep_once

    logger.info("Calendar agent started")

    while True:
        try:
            # The loop's tick, not a user's interval. `sweep_once` skips
            # any user whose own interval has not elapsed, so a per-account
            # setting is honoured without one loop per user.
            await asyncio.sleep(TICK_MINUTES * 60)

            # One sweeper at a time. Two instances would find the same
            # double-booking and propose the same reshuffle twice, and a
            # proposal is something a person is asked to act on.
            with advisory_lock(CALENDAR_LOCK) as held:
                if not held:
                    continue
                proposed = await sweep_once()

            if proposed:
                logger.info("Calendar agent proposed %s change(s)", proposed)

        except asyncio.CancelledError:
            logger.info("Calendar agent stopping")
            raise
        except Exception:
            logger.exception("Calendar sweep failed")


async def assignment_loop() -> None:
    """
    Start the authoring agent on newly assigned work items.

    The fifth loop, and the only authoring trigger that is a sweep rather than
    an event. A reviewer requesting changes and a tester reporting a failure
    both arrive as webhooks; a ticket landing on somebody fires nothing Locus
    receives, so there is nothing to subscribe to -- the same argument that
    makes `automerge.sweep_once` a timer.

    Does nothing unless an account turned `auto_start_on_assignment` on. The
    sweep returns immediately when no account has, so a deployment that never
    enables it pays one query every tick.
    """
    from app.core.locks import ASSIGNMENT_LOCK, advisory_lock
    from app.services.authoring.assignment_watch import TICK_MINUTES, sweep_once

    logger.info("Assignment watcher started")

    while True:
        try:
            await asyncio.sleep(TICK_MINUTES * 60)

            # One sweeper at a time. This one ends in a pull request with a
            # reviewer's name on it, so two instances would open two for the
            # same ticket -- the duplicate-PR failure the rework fix exists to
            # prevent, arriving from a different direction.
            with advisory_lock(ASSIGNMENT_LOCK) as held:
                if not held:
                    continue
                started = await sweep_once()

            if started:
                logger.info(
                    "Assignment watcher started %s work item(s)", started
                )

        except asyncio.CancelledError:
            logger.info("Assignment watcher stopping")
            raise
        except Exception:
            logger.exception("Assignment sweep failed")
