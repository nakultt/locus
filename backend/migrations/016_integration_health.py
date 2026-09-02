"""
Migration: integration health

Adds one table:

  integration_health  -- last success, last failure, and failure streak per
                         (user, service)

The background loops swallow their own errors on purpose: a dead Jira must not
stop the analysis, and a Gmail outage must not stop the review loop. The cost
is that a persistently broken integration is invisible. A Gmail token that
expired on Monday is still failing on Friday, and the only symptom is that QA
replies stopped arriving -- which reads as nobody replying.

One row per (user, service), rewritten in place. The question is "is this
working now"; a full attempt history would grow without bound for a poller that
runs every few minutes.

Run from the backend/ directory:

    uv run python migrations/016_integration_health.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect  # noqa: E402

from app import models  # noqa: E402,F401  (imported so create_all sees the tables)
from app.core.database import Base, engine  # noqa: E402

TABLES = ["integration_health"]


def main() -> None:
    before = set(inspect(engine).get_table_names())

    # create_all only creates what is missing, so this is safe to re-run.
    Base.metadata.create_all(bind=engine)

    after = set(inspect(engine).get_table_names())

    for table in TABLES:
        if table in before:
            print(f"= {table} already present")
        elif table in after:
            print(f"+ {table}")
        else:
            print(f"! {table} was not created -- check the model import")

    print("\nMigration complete.")


if __name__ == "__main__":
    main()
