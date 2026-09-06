"""
Migration: what starts the authoring agent

Adds three columns to `pr_agent_defaults`: `auto_start_on_assignment`,
`auto_start_on_review` and `auto_start_on_qa`.

`authoring_mode` already answers "may the agent write this work item". These
answer the separate question of who has to press the button. With all three on
and the mode autonomous, the run from an assigned ticket to a signed-off merge
needs no human except the reviewer and the tester.

**The defaults are not uniform, and that is the point.** The review and QA
triggers already fired automatically before they were settings -- the
changes-requested path in `routers/webhooks.py` and the rejection path in
`pipeline/qa_feedback.py` have both called the driver since autonomous mode
shipped. Defaulting them to 0 would silently switch off a pipeline that works
today, on an upgrade nobody thought was behavioural, and the symptom would be a
rework that simply never arrives. So they default to 1 and this migration
backfills existing rows to 1.

Assignment is new capability and defaults to 0. Its blast radius is the reason:
a morning's assigned tickets can open a pull request each, which is the same
shape of mistake as a dashboard refresh notifying a team twice, one level up.
Once enabled the throughput cap (`max_open_autonomous_prs`) is what bounds it.

Backfilling is safe precisely because the two on-by-default columns describe
behaviour the rows already had. A row written before this migration ran under
exactly those semantics, so 1 is what it was already doing -- not a new choice
being made on the account's behalf.

Idempotent, like every script here: a column already present is left alone, and
the backfill only touches NULLs left by the ALTER.

Run from the backend/ directory:

    uv run python migrations/030_auto_start_triggers.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, text  # noqa: E402

from app import models  # noqa: E402,F401  (imported so create_all sees the tables)
from app.core.database import Base, engine  # noqa: E402

TABLE = "pr_agent_defaults"

# name -> (ddl type, value existing rows should carry)
COLUMNS = {
    "auto_start_on_assignment": ("INTEGER", 0),
    "auto_start_on_review": ("INTEGER", 1),
    "auto_start_on_qa": ("INTEGER", 1),
}


def main() -> None:
    # A fresh database has no table to alter; create_all makes it complete.
    Base.metadata.create_all(bind=engine)

    inspector = inspect(engine)
    if TABLE not in inspector.get_table_names():
        print(f"+ {TABLE} (created)")
        print("\nMigration complete.")
        return

    existing = {c["name"] for c in inspector.get_columns(TABLE)}

    with engine.begin() as conn:
        for name, (ddl_type, backfill) in COLUMNS.items():
            if name in existing:
                print(f"= {TABLE}.{name}")
                continue
            conn.execute(
                text(f"ALTER TABLE {TABLE} ADD COLUMN {name} {ddl_type}")
            )
            # Separate from the ALTER so it also repairs a half-run migration:
            # the column exists but its rows are NULL, which a NOT NULL model
            # would read back as a value nobody chose.
            conn.execute(
                text(f"UPDATE {TABLE} SET {name} = :v WHERE {name} IS NULL"),
                {"v": backfill},
            )
            print(f"+ {TABLE}.{name} (existing rows -> {backfill})")

        # Repair pass for rows an earlier partial run left NULL.
        for name, (_ddl, backfill) in COLUMNS.items():
            if name not in existing:
                continue
            repaired = conn.execute(
                text(f"UPDATE {TABLE} SET {name} = :v WHERE {name} IS NULL"),
                {"v": backfill},
            ).rowcount
            if repaired:
                print(f"~ {TABLE}.{name} ({repaired} NULL row(s) -> {backfill})")

    print("\nMigration complete.")


if __name__ == "__main__":
    main()
