"""
Migration: the authoring attempt history, and the worktree settings

Creates `authoring_attempts` (via create_all), adds three columns to each
settings table, and relaxes `pr_jobs.pr_number`.

  repo_webhooks.source_path / .prepare_command / .test_command
  pr_agent_defaults.source_path / .prepare_command / .test_command
  pr_jobs.pr_number            NOT NULL -> nullable

`authoring_attempts` is append-only, the same argument as `pr_review_rounds`: a
mutable counter can say the agent tried three times but not why it tried again,
and every failure -- a timeout, an oversized diff, a denylisted path -- has to
leave a row, or it would not consume an attempt and a reliably-failing ticket
would retry forever.

`model` and `context_mode` are stored per attempt rather than read from config
at display time. "Which model wrote this, and how much of our internal
discussion did it see" is asked after the fact, when the config value has
already moved on.

The three settings columns are all nullable, because NULL is how
`resolve_settings` hears "this repo says nothing": a repo with no local
checkout must still fall through to LOCUS_CODE_ROOT and then to a managed
clone, and a repo with no test command must mean "no gate" rather than an empty
one that always passes.

`pr_jobs.pr_number` is relaxed because an authoring job has no pull request
number when it starts -- opening one is its whole job. Queuing with 0 as a
sentinel is the tempting alternative and something downstream reads it as a
real PR number within a release.

SQLite cannot ALTER a column's nullability, so the relaxation is a rebuild:
create the table anew, copy, swap. Guarded so it runs only when the column is
still NOT NULL, which is what keeps the script idempotent.

Run from the backend/ directory:

    uv run python migrations/023_authoring_attempts.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, text  # noqa: E402

from app import models  # noqa: E402,F401  (imported so create_all sees the tables)
from app.core.database import Base, engine  # noqa: E402

COLUMNS = [
    ("repo_webhooks", "source_path", "TEXT"),
    ("repo_webhooks", "prepare_command", "TEXT"),
    ("repo_webhooks", "test_command", "TEXT"),
    ("pr_agent_defaults", "source_path", "TEXT"),
    ("pr_agent_defaults", "prepare_command", "TEXT"),
    ("pr_agent_defaults", "test_command", "TEXT"),
]

PR_JOB_COLUMNS = (
    "id, repo, pr_number, action, head_sha, payload_json, status, result_json, "
    "error, created_at, started_at, completed_at, attempts, owner_id"
)


def _relax_pr_number(inspector) -> None:
    """Make pr_jobs.pr_number nullable, on whichever backend this is."""
    if "pr_jobs" not in set(inspector.get_table_names()):
        print("= pr_jobs.pr_number (table newly created)")
        return

    column = next(
        (c for c in inspector.get_columns("pr_jobs") if c["name"] == "pr_number"), None
    )
    if column is None or column.get("nullable"):
        print("= pr_jobs.pr_number already nullable")
        return

    if engine.dialect.name == "sqlite":
        # SQLite has no ALTER COLUMN. Rebuild through a temp table, which is
        # the documented approach and preserves the rows.
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE pr_jobs RENAME TO pr_jobs_old"))
            models.PRJob.__table__.create(bind=conn)
            conn.execute(text(
                f"INSERT INTO pr_jobs ({PR_JOB_COLUMNS}) "
                f"SELECT {PR_JOB_COLUMNS} FROM pr_jobs_old"
            ))
            conn.execute(text("DROP TABLE pr_jobs_old"))
    else:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE pr_jobs ALTER COLUMN pr_number DROP NOT NULL"))

    print("~ pr_jobs.pr_number is now nullable")


def main() -> None:
    Base.metadata.create_all(bind=engine)

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    for table, column, ddl_type in COLUMNS:
        if table not in existing_tables:
            print(f"= {table}.{column} (table newly created)")
            continue

        columns = {c["name"] for c in inspector.get_columns(table)}
        if column in columns:
            print(f"= {table}.{column} already present")
            continue

        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"))
        print(f"+ {table}.{column}")

    _relax_pr_number(inspector)

    print("= authoring_attempts (created by create_all if absent)")
    print("\nMigration complete.")


if __name__ == "__main__":
    main()
