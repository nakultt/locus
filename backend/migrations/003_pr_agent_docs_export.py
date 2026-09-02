"""
Migration: Google Docs export for PR analyses

Adds repo_webhooks.export_to_docs.

Run from the backend/ directory:

    uv run python migrations/003_pr_agent_docs_export.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, text  # noqa: E402

from app import models  # noqa: E402,F401  (imported so create_all sees the tables)
from app.core.database import Base, engine  # noqa: E402


def column_exists(table: str, column: str) -> bool:
    inspector = inspect(engine)
    if table not in inspector.get_table_names():
        return False
    return column in {c["name"] for c in inspector.get_columns(table)}


def main() -> None:
    # Create the table first if this is a fresh database.
    Base.metadata.create_all(bind=engine)

    if column_exists("repo_webhooks", "export_to_docs"):
        print("= repo_webhooks.export_to_docs already present")
    else:
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE repo_webhooks ADD COLUMN export_to_docs "
                "INTEGER NOT NULL DEFAULT 0"
            ))
        print("+ repo_webhooks.export_to_docs")

    print("\nMigration complete.")


if __name__ == "__main__":
    main()
