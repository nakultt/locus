"""
Migration: per-driver model and reasoning level

Adds one nullable column, `pr_agent_defaults.authoring_driver_options`, holding
JSON of the form:

    {"codex": {"model": "gpt-5.6-luna", "effort": "high"},
     "claude": {"model": "opus", "effort": "high"},
     "opencode": {"model": "opencode/muse-spark-1.3", "effort": "max"}}

One column rather than two per driver. The set of drivers is code, not schema,
and a migration per driver added is one nobody remembers to write.

**Nothing is backfilled, and the existing `authoring_model` is not migrated
into it.** That column is a single pin written for whichever driver was
selected at the time, and it is already read only for that driver -- a model
name is one provider's catalogue entry, and copying `opencode/muse-spark-1.3`
into a `claude` slot would produce a pin naming a model that does not exist
there. It keeps working as the legacy fallback for its own driver; anything
per-driver is a choice someone makes in the form.

Reasoning is stored as the plain level ("high"), never as the flag. The three
CLIs spell it three different ways -- `--variant`, `--effort`, and a
`-c model_reasoning_effort=` config override -- so storing the spelling would
make the stored value unusable the moment the driver changes, which is the
same mistake `_own_settings` exists to catch for the command template.

Idempotent, like every script here: a column already present is left alone.

Run from the backend/ directory:

    uv run python migrations/031_driver_options.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, text  # noqa: E402

from app import models  # noqa: E402,F401  (imported so create_all sees the tables)
from app.core.database import Base, engine  # noqa: E402

TABLE = "pr_agent_defaults"
COLUMNS = {"authoring_driver_options": "TEXT"}


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
        for name, ddl_type in COLUMNS.items():
            if name in existing:
                print(f"= {TABLE}.{name}")
                continue
            conn.execute(text(f"ALTER TABLE {TABLE} ADD COLUMN {name} {ddl_type}"))
            print(f"+ {TABLE}.{name}")

    print("\nMigration complete.")


if __name__ == "__main__":
    main()
