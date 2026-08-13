"""
Migration: per-user timezone

Ensures users.timezone exists and backfills existing rows to Asia/Kolkata.

The column was added to the model earlier but never migrated, so a database
created before that point has no column and every calendar operation fails on
the missing attribute.

Run from the backend/ directory:

    uv run python migrations/007_user_timezone.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, text  # noqa: E402

from app import models  # noqa: E402,F401  (imported so create_all sees the tables)
from app.database import Base, engine  # noqa: E402


def main() -> None:
    Base.metadata.create_all(bind=engine)

    inspector = inspect(engine)
    columns = {c["name"] for c in inspector.get_columns("users")}

    if "timezone" in columns:
        print("= users.timezone already present")
    else:
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE users ADD COLUMN timezone VARCHAR(64) "
                "NOT NULL DEFAULT 'Asia/Kolkata'"
            ))
        print("+ users.timezone")

    # Backfill anything left null by an earlier partial migration.
    with engine.begin() as conn:
        result = conn.execute(text(
            "UPDATE users SET timezone = 'Asia/Kolkata' "
            "WHERE timezone IS NULL OR timezone = ''"
        ))
        if result.rowcount:
            print(f"~ backfilled {result.rowcount} user(s)")

    print("\nMigration complete.")


if __name__ == "__main__":
    main()
