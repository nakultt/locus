"""
Migration: pinned Google Docs context

Adds repo_webhooks.context_doc_ids -- newline-separated Google Doc ids whose
text is fed to the reviewer LLM on every analysis of that repo.

Run from the backend/ directory:

    uv run python migrations/004_pinned_context_docs.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, text  # noqa: E402

from app import models  # noqa: E402,F401  (imported so create_all sees the tables)
from app.core.database import Base, engine  # noqa: E402


def column_exists(table: str, column: str) -> bool:
    inspector = inspect(engine)
    if table not in inspector.get_table_names():
        return False
    return column in {c["name"] for c in inspector.get_columns(table)}


def main() -> None:
    Base.metadata.create_all(bind=engine)

    if column_exists("repo_webhooks", "context_doc_ids"):
        print("= repo_webhooks.context_doc_ids already present")
    else:
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE repo_webhooks ADD COLUMN context_doc_ids TEXT"
            ))
        print("+ repo_webhooks.context_doc_ids")

    print("\nMigration complete.")


if __name__ == "__main__":
    main()
