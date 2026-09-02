"""
Migration: account-wide context documents

Adds one nullable column:

  pr_agent_defaults.context_doc_ids   -- newline-separated Google Doc ids

Context docs were previously repo-only, which meant a repo nobody registered
was reviewed against no written standard at all. The account-level docs are
the ones that apply everywhere -- an API style guide, a security policy --
while a repo's own describe that codebase.

The two accumulate rather than override, unlike every other setting here: a
repo that pins its own spec should still be reviewed against the org's
standards, so letting the repo value win would silently drop them. See
app/services/agent_settings.py.

Nullable with no default, so "not set" stays distinguishable from "set to
nothing".

Run from the backend/ directory:

    uv run python migrations/013_global_context_docs.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, text  # noqa: E402

from app import models  # noqa: E402,F401  (imported so create_all sees the tables)
from app.core.database import Base, engine  # noqa: E402

# (table, column, DDL type) -- nullable, no default.
COLUMNS = [
    ("pr_agent_defaults", "context_doc_ids", "TEXT"),
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
