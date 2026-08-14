"""
Migration: recoverable PR jobs

Adds two columns:

  pr_jobs.started_at   -- when the worker claimed the job
  pr_jobs.attempts     -- how many times it has been claimed

A job that was `running` when the process died used to stay that way forever.
Nothing noticed: the GitHub webhook was answered when the job was queued, so
there is no retry behind it and the pull request was simply never analyzed --
silently, which is the part that made it hard to spot.

Recovery needs both columns. `started_at` distinguishes a job running for five
seconds from one orphaned an hour ago; without it every in-flight job looks
reclaimable and reclaiming one still being worked on double-posts its comment.
`attempts` stops the rescue becoming a loop -- a job that reliably kills the
worker would otherwise be requeued and re-crash forever.

`attempts` is NOT NULL DEFAULT 0 so existing rows count as never attempted.
`started_at` is nullable, and the recovery sweep treats null as recoverable,
which is correct for jobs claimed before this column existed.

Run from the backend/ directory:

    uv run python migrations/014_job_recovery.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, text  # noqa: E402

from app import models  # noqa: E402,F401  (imported so create_all sees the tables)
from app.database import Base, engine  # noqa: E402

# (table, column, DDL type)
COLUMNS = [
    ("pr_jobs", "started_at", "TIMESTAMP WITH TIME ZONE"),
    ("pr_jobs", "attempts", "INTEGER NOT NULL DEFAULT 0"),
]


def main() -> None:
    Base.metadata.create_all(bind=engine)

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    dialect = engine.dialect.name

    for table, column, ddl_type in COLUMNS:
        if table not in existing_tables:
            # create_all just made it with the column already on it.
            print(f"= {table}.{column} (table newly created)")
            continue

        columns = {c["name"] for c in inspector.get_columns(table)}
        if column in columns:
            print(f"= {table}.{column} already present")
            continue

        # SQLite has no TIMESTAMP WITH TIME ZONE; it stores datetimes as text
        # and ignores the qualifier anyway.
        column_type = ddl_type
        if dialect == "sqlite" and "TIMESTAMP" in ddl_type:
            column_type = "TIMESTAMP"

        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}"))
        print(f"+ {table}.{column}")

    print("\nMigration complete.")


if __name__ == "__main__":
    main()
