"""
Migration: sync the GitHub Projects card with the pipeline stage

Adds two columns to each settings table:

  repo_webhooks.project_board_sync      / .project_column_map
  pr_agent_defaults.project_board_sync  / .project_column_map

Closing an issue moves its card only when the project happens to have GitHub's
stock "item closed -> Done" workflow enabled, and that workflow can express
exactly one transition. Everything the pipeline actually does between picking a
ticket up and QA signing off -- the branch, the review round trip, the testing
thread -- is invisible on the board, so a ticket whose work is nearly finished
sits in `Todo` until somebody drags it.

`project_board_sync` defaults to 1, unlike `auto_merge_on_approval`. That one is
off because it writes to a default branch with no human in the loop; this writes
a status field on a card, is refused when it would move the card backwards, and
the behaviour it replaces is a board that silently disagrees with the pipeline.

`project_column_map` is NULL by default, meaning the default map in
`app/services/project_board.py`: everything from the branch through testing maps
to "In progress", and only a QA sign-off reaches "Done" -- merged is not done.
A repo whose board has different columns writes its own, one "stage: column"
per line, and a stage left out of a non-empty map moves no card.

Note this needs the GitHub `project` / `read:project` OAuth scope, which `repo`
does not imply. A token without it reports the board as skipped rather than
failing the merge; users connected before this shipped must reconnect GitHub.

Run from the backend/ directory:

    uv run python migrations/021_project_board_sync.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, text  # noqa: E402

from app import models  # noqa: E402,F401  (imported so create_all sees the tables)
from app.core.database import Base, engine  # noqa: E402

# (table, column, DDL type). The boolean is NOT NULL with a default matching the
# model: the resolver treats a present row as a deliberate choice, so it must
# never read back as NULL on an existing row. The map is nullable, because NULL
# is meaningfully "use the default map".
COLUMNS = [
    ("repo_webhooks", "project_board_sync", "INTEGER NOT NULL DEFAULT 1"),
    ("repo_webhooks", "project_column_map", "TEXT"),
    ("pr_agent_defaults", "project_board_sync", "INTEGER NOT NULL DEFAULT 1"),
    ("pr_agent_defaults", "project_column_map", "TEXT"),
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

    print("\nMigration complete.")


if __name__ == "__main__":
    main()
