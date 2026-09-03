"""
Migration: per-account agent runtime settings

Adds sixteen nullable columns to `pr_agent_defaults`.

The driver, the model, the invocation template, how much of the brief leaves
the machine, the diff bounds, the commit identity, the source and workspace
roots and the calendar agent's two dials were environment variables. That made
each of them one operator's answer for every tenant on the deployment --
including `LOCUS_AUTHORING_CONTEXT`, which decides whether a team's internal
Slack discussion may be sent to a third party. That is a tenant's policy.

Every column is nullable and NULL means "inherit": the environment variable
first, then the constant in the code. Nothing is backfilled, so an existing
install keeps behaving exactly as it does today -- the rows stay NULL and
`agent_runtime` falls through to the same variables it read before.

`allow_in_place` is an Integer rather than a Boolean for the same reason: it
has three states and NULL is one of them. Stored as a Boolean, "inherit" and
"explicitly off" would be indistinguishable, and an account could never turn
off a deployment default that was on.

Idempotent, like every script here: columns already present are left alone.

Run from the backend/ directory:

    uv run python migrations/027_agent_runtime.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, text  # noqa: E402

from app import models  # noqa: E402,F401  (imported so create_all sees the tables)
from app.core.database import Base, engine  # noqa: E402

TABLE = "pr_agent_defaults"

COLUMNS = {
    "authoring_driver": "VARCHAR(32)",
    "authoring_model": "TEXT",
    "authoring_command": "TEXT",
    "authoring_context": "VARCHAR(16)",
    "authoring_timeout_seconds": "INTEGER",
    "max_changed_files": "INTEGER",
    "max_changed_lines": "INTEGER",
    "max_open_autonomous_prs": "INTEGER",
    "agent_commit_name": "VARCHAR(120)",
    "agent_commit_email": "VARCHAR(255)",
    "code_root": "TEXT",
    "workspace_root": "TEXT",
    "allow_in_place": "INTEGER",
    "workspace_ttl_days": "INTEGER",
    "calendar_sweep_minutes": "INTEGER",
    "calendar_lookahead_days": "INTEGER",
}


def main() -> None:
    # A fresh database has no table to alter; create_all makes it complete.
    Base.metadata.create_all(bind=engine)

    inspector = inspect(engine)
    if TABLE not in inspector.get_table_names():
        print(f"+ {TABLE} (created)")
        print("\nMigration complete.")
        return

    existing = {c["name"] for c in inspector.get_columns(TABLE)}

    with engine.begin() as conn:
        for name, ddl_type in COLUMNS.items():
            if name in existing:
                print(f"= {TABLE}.{name}")
                continue
            conn.execute(text(f"ALTER TABLE {TABLE} ADD COLUMN {name} {ddl_type}"))
            print(f"+ {TABLE}.{name}")

    print("\nMigration complete.")


if __name__ == "__main__":
    main()
