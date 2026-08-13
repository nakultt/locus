"""
Migration: account-wide PR agent defaults

Adds one table:
  pr_agent_defaults  -- fallbacks for repos that do not set their own

Every setting here also exists per repo; the repo wins when it says anything.
This exists so a repo that was never registered still exports its report and
emails the test team instead of silently doing neither.

Run from the backend/ directory:

    uv run python migrations/009_pr_agent_defaults.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect  # noqa: E402

from app import models  # noqa: E402,F401  (imported so create_all sees the table)
from app.database import Base, engine  # noqa: E402

TABLES = ("pr_agent_defaults",)


def main() -> None:
    before = set(inspect(engine).get_table_names())
    Base.metadata.create_all(bind=engine)

    for table in TABLES:
        print(f"= {table} already present" if table in before else f"+ {table}")

    print("\nMigration complete.")


if __name__ == "__main__":
    main()
