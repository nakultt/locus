"""
Migration: local-first LLM + PR Context Agent

- Drops users.encrypted_gemini_key (Locus no longer stores model API keys)
- Adds users.timezone, defaulting to Asia/Kolkata
- Creates pr_jobs and repo_webhooks

Run once against an existing database, from the backend/ directory:

    uv run python migrations/003_local_first_and_pr_agent.py
"""

import sys
from pathlib import Path

# Allow running this file directly from backend/migrations/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, text  # noqa: E402

from app import models  # noqa: E402,F401  (imported so create_all sees the tables)
from app.database import Base, engine  # noqa: E402


def column_exists(table: str, column: str) -> bool:
    inspector = inspect(engine)
    if table not in inspector.get_table_names():
        return False
    return column in {c["name"] for c in inspector.get_columns(table)}


def main() -> None:
    is_sqlite = engine.url.get_backend_name() == "sqlite"

    with engine.begin() as conn:
        # Add timezone
        if not column_exists("users", "timezone"):
            conn.execute(text(
                "ALTER TABLE users ADD COLUMN timezone VARCHAR(64) "
                "NOT NULL DEFAULT 'Asia/Kolkata'"
            ))
            print("+ users.timezone")
        else:
            print("= users.timezone already present")

        # Drop the Gemini key column
        if column_exists("users", "encrypted_gemini_key"):
            if is_sqlite:
                # SQLite gained DROP COLUMN in 3.35; older versions will raise.
                try:
                    conn.execute(text("ALTER TABLE users DROP COLUMN encrypted_gemini_key"))
                    print("- users.encrypted_gemini_key")
                except Exception as e:
                    print(f"! Could not drop encrypted_gemini_key ({e}); leaving in place")
            else:
                conn.execute(text("ALTER TABLE users DROP COLUMN encrypted_gemini_key"))
                print("- users.encrypted_gemini_key")
        else:
            print("= users.encrypted_gemini_key already absent")

    # Create pr_jobs / repo_webhooks
    Base.metadata.create_all(bind=engine)
    print("+ pr_jobs, repo_webhooks (created if missing)")
    print("\nMigration complete.")


if __name__ == "__main__":
    main()
