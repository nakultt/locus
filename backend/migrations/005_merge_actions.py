"""
Migration: post-merge actions

Adds repo_webhooks columns for QA notification and merge behaviour:
  qa_emails              -- test team addresses, newline-separated
  jira_done_status       -- status to move tickets to on merge
  close_issues_on_merge  -- whether to close linked GitHub issues

Run from the backend/ directory:

    uv run python migrations/005_merge_actions.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, text  # noqa: E402

from app import models  # noqa: E402,F401  (imported so create_all sees the tables)
from app.database import Base, engine  # noqa: E402

COLUMNS = [
    ("qa_emails", "TEXT"),
    ("jira_done_status", "VARCHAR(64) NOT NULL DEFAULT 'Done'"),
    ("close_issues_on_merge", "INTEGER NOT NULL DEFAULT 1"),
]


def existing_columns(table: str) -> set[str]:
    inspector = inspect(engine)
    if table not in inspector.get_table_names():
        return set()
    return {c["name"] for c in inspector.get_columns(table)}


def main() -> None:
    Base.metadata.create_all(bind=engine)

    present = existing_columns("repo_webhooks")
    with engine.begin() as conn:
        for name, ddl in COLUMNS:
            if name in present:
                print(f"= repo_webhooks.{name} already present")
                continue
            conn.execute(text(f"ALTER TABLE repo_webhooks ADD COLUMN {name} {ddl}"))
            print(f"+ repo_webhooks.{name}")

    print("\nMigration complete.")


if __name__ == "__main__":
    main()
