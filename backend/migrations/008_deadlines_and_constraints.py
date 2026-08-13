"""
Migration: scheduler deadlines and event constraints

Adds two tables:
  deadlines          -- due dates the scheduler must not push work past
  event_constraints  -- per-event overrides of how movable an event is

Run from the backend/ directory:

    uv run python migrations/008_deadlines_and_constraints.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect  # noqa: E402

from app import models  # noqa: E402,F401  (imported so create_all sees the tables)
from app.database import Base, engine  # noqa: E402

TABLES = ("deadlines", "event_constraints")


def main() -> None:
    before = set(inspect(engine).get_table_names())
    Base.metadata.create_all(bind=engine)

    for table in TABLES:
        print(f"= {table} already present" if table in before else f"+ {table}")

    print("\nMigration complete.")


if __name__ == "__main__":
    main()
