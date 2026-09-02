"""
Migration: communication log and reviewer contacts

Adds one table:
  communication_events  -- every message searched, sent, or received per PR

And reviewer contact columns on both settings sources:
  repo_webhooks.reviewer_contacts
  pr_agent_defaults.reviewer_contacts

The log is append-only and starts empty. Runs that happened before this
migration have no record and will show an empty timeline; there is nothing to
backfill from, since the messages themselves were never stored.

Run from the backend/ directory:

    uv run python migrations/011_communication_log.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, text  # noqa: E402

from app import models  # noqa: E402,F401  (imported so create_all sees the tables)
from app.core.database import Base, engine  # noqa: E402

TABLES = ("communication_events",)

COLUMNS = [
    ("repo_webhooks", "reviewer_contacts", "TEXT"),
    ("pr_agent_defaults", "reviewer_contacts", "TEXT"),
]


def main() -> None:
    before = set(inspect(engine).get_table_names())
    Base.metadata.create_all(bind=engine)

    for table in TABLES:
        print(f"= {table} already present" if table in before else f"+ {table}")

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

    print("\nMigration complete.")


if __name__ == "__main__":
    main()
