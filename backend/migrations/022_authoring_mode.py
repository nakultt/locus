"""
Migration: the authoring dial

Adds the authoring mode to both settings tables, and creates
`work_item_settings` -- the third and most specific source `resolve_settings`
reads.

  repo_webhooks.authoring_mode            / .autonomous_max_rounds / .preset_label
  pr_agent_defaults.authoring_mode        / .autonomous_max_rounds / .preset_label
  work_item_settings                      (new table, made by create_all)

The repo columns are nullable and the defaults columns are not, and the
asymmetry is the point: NULL is how the resolver hears "this repo says
nothing" and falls through. A defaults row that exists is a deliberate choice,
so it must never read back as NULL.

`autonomous_max_rounds` defaults to 2 -- the first attempt plus two reworks.
Three swings, then a person. `authoring_mode` defaults to 'assisted', because a
mode that writes code and opens pull requests on its own has to be turned on
rather than inherited by anyone who upgrades.

`preset_label` is display only. `resolve_settings` remains the sole arbiter of
what a run does; a preset expanded at read time would add a second resolution
layer above it and reintroduce exactly the drift it exists to prevent.

Run from the backend/ directory:

    uv run python migrations/022_authoring_mode.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, text  # noqa: E402

from app import models  # noqa: E402,F401  (imported so create_all sees the tables)
from app.database import Base, engine  # noqa: E402

COLUMNS = [
    ("repo_webhooks", "authoring_mode", "TEXT"),
    ("repo_webhooks", "autonomous_max_rounds", "INTEGER"),
    ("repo_webhooks", "preset_label", "TEXT"),
    ("pr_agent_defaults", "authoring_mode", "TEXT NOT NULL DEFAULT 'assisted'"),
    ("pr_agent_defaults", "autonomous_max_rounds", "INTEGER NOT NULL DEFAULT 2"),
    ("pr_agent_defaults", "preset_label", "TEXT"),
]


def main() -> None:
    Base.metadata.create_all(bind=engine)

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    for table, column, ddl_type in COLUMNS:
        if table not in existing_tables:
            # create_all just made it with the column already on it.
            print(f"= {table}.{column} (table newly created)")
            continue

        columns = {c["name"] for c in inspector.get_columns(table)}
        if column in columns:
            print(f"= {table}.{column} already present")
            continue

        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"))
        print(f"+ {table}.{column}")

    print("= work_item_settings (created by create_all if absent)")
    print("\nMigration complete.")


if __name__ == "__main__":
    main()
