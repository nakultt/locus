"""
Migration: one report document per pull request

Adds one table:

  pr_reports  -- the Google Doc id holding a pull request's written record

The export used to POST to /v1/documents on every run, which creates a new file
each time. A pull request pushed to five times ended up with five documents,
each frozen at the moment it was written, and -- worse -- every link already
sent to a reviewer or the testing team pointed at a stale one. The link is the
whole reason the document is worth writing, so it has to stay current.

With this row the document is rewritten in place: same id, same URL, contents
replaced. Review events and QA replies refresh it too, which is where most of
the story actually happens -- the verdict, the round trip, the tester's answer.

Existing pull requests have no row and get one the next time their analysis
runs; the document they get then becomes the durable one.

Run from the backend/ directory:

    uv run python migrations/018_pr_reports.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect  # noqa: E402

from app import models  # noqa: E402,F401  (imported so create_all sees the tables)
from app.database import Base, engine  # noqa: E402

TABLES = ["pr_reports"]


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
            print(f"! {table} was not created")

    print("\nMigration complete.")


if __name__ == "__main__":
    main()
