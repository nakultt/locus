"""
Migration: an authoring attempt has a state

Adds `state` and `finished_at` to `authoring_attempts`.

The row used to be written only once the driver returned, which cost two
things. The board could not say the agent was working: a card read `assigned`
for the ten minutes a run takes, indistinguishable from one nobody had
started. And a process that died mid-run left no row at all, so the attempt
was never consumed -- "every failure consumes an attempt" held for every
failure the driver reported and not for the one that killed it.

`begin_attempt` now writes the row as `running` before the driver is invoked
and `record_attempt` updates it in place, so one run stays one row. Two rows
would double-count against the bound, which is the thing the history exists to
make real.

**`state` backfills to `finished`, not `running`.** Every existing row
describes a run that has already ended -- it could not have been written
otherwise -- and defaulting them to `running` would show every past attempt as
permanently in progress. `finished_at` is deliberately left NULL on those rows
rather than copied from `created_at`: the two mean different things now
(`created_at` is when the run started), and inventing a finish time would be a
claim the data does not support.

Idempotent, like every script here: columns already present are left alone.

Run from the backend/ directory:

    uv run python migrations/028_authoring_attempt_state.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, text  # noqa: E402

from app import models  # noqa: E402,F401  (imported so create_all sees the tables)
from app.core.database import Base, engine  # noqa: E402

TABLE = "authoring_attempts"

COLUMNS = {
    # NOT NULL with a default, so existing rows land on `finished` in the same
    # statement rather than needing a separate backfill that could be
    # interrupted halfway.
    "state": "VARCHAR(16) NOT NULL DEFAULT 'finished'",
    "finished_at": "TIMESTAMP WITH TIME ZONE",
}

# SQLite has no TIMESTAMP WITH TIME ZONE and stores everything as text anyway.
SQLITE_TYPES = {
    "state": "VARCHAR(16) NOT NULL DEFAULT 'finished'",
    "finished_at": "DATETIME",
}


def main() -> None:
    # A fresh database has no table to alter; create_all makes it complete.
    Base.metadata.create_all(bind=engine)

    inspector = inspect(engine)
    if TABLE not in inspector.get_table_names():
        print(f"+ {TABLE} (created)")
        print("\nMigration complete.")
        return

    is_sqlite = engine.dialect.name == "sqlite"
    types = SQLITE_TYPES if is_sqlite else COLUMNS

    existing = {c["name"] for c in inspector.get_columns(TABLE)}

    with engine.begin() as conn:
        for name, ddl_type in types.items():
            if name in existing:
                print(f"= {TABLE}.{name}")
                continue
            conn.execute(text(f"ALTER TABLE {TABLE} ADD COLUMN {name} {ddl_type}"))
            print(f"+ {TABLE}.{name}")

        # Any row that predates this column describes a finished run. Written
        # explicitly as well as by the DEFAULT, because a column added to an
        # existing table does not always backfill on every engine/version.
        updated = conn.execute(
            text(f"UPDATE {TABLE} SET state = 'finished' WHERE state IS NULL")
        ).rowcount
        if updated:
            print(f"~ {TABLE}.state backfilled to 'finished' on {updated} row(s)")

    print("\nMigration complete.")


if __name__ == "__main__":
    main()
