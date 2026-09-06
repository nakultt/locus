"""
Advisory locks for the background loops.

The PR job worker claims its work with a conditional UPDATE, so two workers
racing for a job produce one winner. The other two loops have nothing to claim:
`automerge.sweep_once` and `qa_email_poller.poll_once` scan for work that
matches a condition, and every instance running them would match the same rows
at the same time.

That matters more than duplicated effort, because both loops end in a message
to a person. Two instances sweeping means an approved PR is merged once and
announced twice; two instances polling Gmail means one QA reply is processed
twice, which posts the QA thread twice and can transition the ticket twice. A
duplicate outward message is the failure people notice and stop trusting.

Postgres advisory locks are the right tool: they are held on a connection, not
a row, and they vanish if the process dies -- so a crashed instance releases
its lock without needing a timeout or a heartbeat table.

On SQLite the lock is a no-op that always succeeds. SQLite is the single-file
development database; there is no second instance to exclude, and failing
closed there would stop the loops running at all locally.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import text

from app.core.database import SessionLocal, engine

logger = logging.getLogger(__name__)

# Postgres advisory locks are keyed by a bigint. These are arbitrary but must
# stay stable -- changing one lets an old instance and a new one both run.
MERGE_SWEEP_LOCK = 8_417_001
QA_POLL_LOCK = 8_417_002
# The calendar agent sweeps for conflicts rather than claiming them, so two
# instances would find the same double-booking and propose the same reshuffle
# twice -- and a proposal is something a person is asked to act on.
CALENDAR_LOCK = 8_417_003
# The assignment sweep matches assigned work items rather than claiming them,
# and ends in a pull request with a reviewer's name on it. Two instances would
# open two for the same ticket -- the duplicate-PR failure the rework fix
# exists to prevent, arriving from a different direction.
ASSIGNMENT_LOCK = 8_417_004


def _supports_advisory_locks() -> bool:
    """Whether the configured database has advisory locks at all."""
    return engine.dialect.name == "postgresql"


@contextmanager
def advisory_lock(key: int) -> Iterator[bool]:
    """
    Try to take a named lock for the duration of the block.

    Yields True when the lock was acquired and the caller should do the work,
    False when another instance already holds it and this one should skip.

    The lock is held on a dedicated connection and released in `finally`, so a
    raised exception inside the block does not strand it. A process that dies
    outright releases it too, because Postgres drops advisory locks when the
    connection goes.

    On a database without advisory locks this always yields True. That is
    correct for SQLite, which is single-instance by construction.
    """
    if not _supports_advisory_locks():
        yield True
        return

    db = SessionLocal()
    acquired = False
    try:
        acquired = bool(
            db.execute(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": key}
            ).scalar()
        )
        yield acquired
    except Exception:
        # A lock we could not take is not a reason to fail the caller's work
        # loop; it is a reason to skip this tick. But an error *inside* the
        # block belongs to the caller, so it is re-raised after release.
        raise
    finally:
        if acquired:
            try:
                db.execute(
                    text("SELECT pg_advisory_unlock(:key)"), {"key": key}
                )
                db.commit()
            except Exception:
                # The connection is about to close, which releases it anyway.
                logger.warning("Could not release advisory lock %s", key)
        db.close()
