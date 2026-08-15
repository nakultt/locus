"""
Migration: close the work item on QA sign-off

Adds one column to each settings table:

  repo_webhooks.close_on_qa_signoff
  pr_agent_defaults.close_on_qa_signoff

Closing at merge asserts the change is done at the one moment the pipeline
itself does not believe it -- the testing team has not looked yet. It is right
whenever QA passes and wrong in both cases that need attention: a rejected
change, and a thread nobody answered. A ticket closed while a bug is still live
drops off the board, which is the one place anyone would look for it.

With this set, the merge leaves the ticket and the linked issues alone and
`qa_feedback` closes them when a tester confirms. The cost is that an
unanswered thread holds the work item open, so `worklist` reports one that has
been silent for three days as something waiting on you.

Defaults to 0: a repo that has not opted in keeps the behaviour it had, and
holding work items open is only safe for a team whose QA loop actually replies.

Run from the backend/ directory:

    uv run python migrations/017_close_on_qa_signoff.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, text  # noqa: E402

from app import models  # noqa: E402,F401  (imported so create_all sees the tables)
from app.database import Base, engine  # noqa: E402

# (table, column, DDL type). NOT NULL with a default, matching the model: the
# resolver treats a present row as a deliberate choice, so the column must
# never read back as NULL on an existing row.
COLUMNS = [
    ("repo_webhooks", "close_on_qa_signoff", "INTEGER NOT NULL DEFAULT 0"),
    ("pr_agent_defaults", "close_on_qa_signoff", "INTEGER NOT NULL DEFAULT 0"),
]


def main() -> None:
    Base.metadata.create_all(bind=engine)

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    for table, column, ddl_type in COLUMNS:
        if table not in existing_tables:
            # create_all just made it with the column already on it.
            print(f"= {table}.{column} (table newly created)")
            continue

        columns = {c["name"] for c in inspector.get_columns(table)}
        if column in columns:
            print(f"= {table}.{column} already present")
            continue

        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"))
        print(f"+ {table}.{column}")

    print("\nMigration complete.")


if __name__ == "__main__":
    main()
