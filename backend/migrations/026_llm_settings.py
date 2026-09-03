"""
Migration: per-user model backend settings

Creates `llm_settings` via `create_all`.

Which provider Locus runs on, what endpoint it talks to and which key it uses
were environment configuration. That is right for one machine and wrong for a
product: two tenants of one deployment cannot share a `.env`, and changing a
model id meant restarting the backend. This table holds it per user, with the
key Fernet-encrypted like every other credential in the schema.

Every column is nullable and blank means "inherit the environment", so an
existing install that never opens the settings page is unaffected by running
this -- the row simply does not exist, and `llm.py` falls through to the same
variables it read before.

Nothing is backfilled. Copying `OPENAI_API_KEY` out of the environment into
every user's row would take one operator's key and hand it to every account on
the deployment, and the key would then survive being removed from the
environment.

Run from the backend/ directory:

    uv run python migrations/026_llm_settings.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect  # noqa: E402

from app import models  # noqa: E402,F401  (imported so create_all sees the tables)
from app.core.database import Base, engine  # noqa: E402


def main() -> None:
    before = set(inspect(engine).get_table_names())

    Base.metadata.create_all(bind=engine)

    print(("= " if "llm_settings" in before else "+ ") + "llm_settings")
    print("\nMigration complete.")


if __name__ == "__main__":
    main()
