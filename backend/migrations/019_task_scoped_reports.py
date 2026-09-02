"""
Migration: report documents keyed by work item

Adds one nullable column:
  pr_reports.ticket_key  -- the work item the document belongs to

Deliberately not backfilled. The key could be derived from each row's pull
request, but a row written before this existed is still found by the
pull-request fallback in `report_sync.find_report`, and that lookup claims it
for the ticket the next time the work is analyzed. Backfilling here would do
the same job less safely: this script has no access to the branch and title
that `work_item.resolve_key` reads, so it would have to guess from data that
may since have changed.

The practical effect is that existing documents keep their links and become
their task's document on the next run, rather than being replaced by a new one.

Run from the backend/ directory:

    uv run python migrations/019_task_scoped_reports.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, text  # noqa: E402

from app import models  # noqa: E402,F401  (imported so create_all sees the tables)
from app.core.database import Base, engine  # noqa: E402


def main() -> None:
    Base.metadata.create_all(bind=engine)

    inspector = inspect(engine)
    if "pr_reports" not in set(inspector.get_table_names()):
        print("= pr_reports (table newly created)")
        print("\nMigration complete.")
        return

    columns = {c["name"] for c in inspector.get_columns("pr_reports")}
    if "ticket_key" in columns:
        print("= pr_reports.ticket_key already present")
    else:
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE pr_reports ADD COLUMN ticket_key VARCHAR(64)"
            ))
        print("+ pr_reports.ticket_key")

    print("\nMigration complete.")


if __name__ == "__main__":
    main()
