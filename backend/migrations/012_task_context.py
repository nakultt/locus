"""
Migration: task-level context

Adds two nullable columns:
  communication_events.ticket_key  -- the work item a message belongs to
  pr_reviews.ticket_keys           -- the work items a pull request belongs to

Both nullable and both unbackfilled. A ticket key can only be recovered by
re-running the analysis, and rows written before this migration simply have
none; they keep working, they just do not group by task until their PR is
analyzed again.

Run from the backend/ directory:

    uv run python migrations/012_task_context.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, text  # noqa: E402

from app import models  # noqa: E402,F401  (imported so create_all sees the tables)
from app.core.database import Base, engine  # noqa: E402

COLUMNS = [
    ("communication_events", "ticket_key", "VARCHAR(64)"),
    ("pr_reviews", "ticket_keys", "TEXT"),
]


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

    print("\nMigration complete.")


if __name__ == "__main__":
    main()
