"""
Migration: reviewers for the pull requests the agent opens

Adds one nullable column, `pr_agent_defaults.autonomous_pr_reviewers`.

Autonomous mode opened its pull requests with nobody requested, so the review
loop's first ping was a Slack message and GitHub's own review queue -- the
place a reviewer actually looks -- never showed the work at all.

Deliberately a separate column from `reviewers`, which names who is expected to
review a repo and is used to *address* the review-loop notifications. Turning
that list into a GitHub review request would start notifying people who only
ever consented to being mentioned in a channel, and a review request is a
notification the recipient cannot undo.

NULL means request nobody, which is exactly what the mode did before this, so
nothing is backfilled and an existing install is unaffected by running it.

Idempotent, like every script here: a column already present is left alone.

Run from the backend/ directory:

    uv run python migrations/029_autonomous_pr_reviewers.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, text  # noqa: E402

from app import models  # noqa: E402,F401  (imported so create_all sees the tables)
from app.core.database import Base, engine  # noqa: E402

TABLE = "pr_agent_defaults"
COLUMNS = {"autonomous_pr_reviewers": "TEXT"}


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
