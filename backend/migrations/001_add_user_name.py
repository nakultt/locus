"""
Migration: users.name

Adds the display-name column to an early database that predates it.

Uses SQLAlchemy's inspector rather than querying information_schema directly:
that table is Postgres-only, so the original version of this script failed
outright on SQLite, which is the default for local development.

Run from the backend/ directory:

    uv run python migrations/001_add_user_name.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, text  # noqa: E402

from app import models  # noqa: E402,F401  (imported so create_all sees the tables)
from app.database import Base, engine  # noqa: E402


def main() -> None:
    # A fresh database gets the current schema outright.
    Base.metadata.create_all(bind=engine)

    columns = {c["name"] for c in inspect(engine).get_columns("users")}

    if "name" in columns:
        print("= users.name already present")
    else:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE users ADD COLUMN name VARCHAR(255)"))
        print("+ users.name")

    print("\nMigration complete.")


if __name__ == "__main__":
    main()
