"""
Migration: documents that start at the ticket

Relaxes two columns to nullable:
  pr_reports.repo
  pr_reports.pr_number

A document is now created when the work item is picked up, before any pull
request exists -- so the requirement and the discussion around it are written
down while someone is still coding, rather than appearing only once a PR opens.
Those two columns record where a document *started*; a ticket-first document
has no pull request to name.

SQLite cannot ALTER a column's nullability, so the table is rebuilt inside one
transaction -- a failure leaves the original untouched. Postgres does it in
place. Existing rows are copied unchanged either way.

Run from the backend/ directory:

    uv run python migrations/020_ticket_first_reports.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, text  # noqa: E402

from app import models  # noqa: E402,F401  (imported so create_all sees the tables)
from app.core.database import Base, engine  # noqa: E402


def _already_nullable(inspector) -> bool:
    columns = {c["name"]: c for c in inspector.get_columns("pr_reports")}
    repo = columns.get("repo")
    pr_number = columns.get("pr_number")
    if repo is None or pr_number is None:
        return False
    return bool(repo.get("nullable")) and bool(pr_number.get("nullable"))


def main() -> None:
    Base.metadata.create_all(bind=engine)

    inspector = inspect(engine)
    if "pr_reports" not in set(inspector.get_table_names()):
        print("= pr_reports (table newly created)")
        print("\nMigration complete.")
        return

    if _already_nullable(inspector):
        print("= pr_reports.repo / pr_number already nullable")
        print("\nMigration complete.")
        return

    if engine.dialect.name == "sqlite":
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE pr_reports_new (
                    id INTEGER NOT NULL PRIMARY KEY,
                    repo VARCHAR(255),
                    pr_number INTEGER,
                    ticket_key VARCHAR(64),
                    document_id VARCHAR(128) NOT NULL,
                    created_at DATETIME,
                    updated_at DATETIME,
                    owner_id INTEGER NOT NULL
                )
            """))
            conn.execute(text("""
                INSERT INTO pr_reports_new
                    (id, repo, pr_number, ticket_key, document_id,
                     created_at, updated_at, owner_id)
                SELECT id, repo, pr_number, ticket_key, document_id,
                       created_at, updated_at, owner_id
                FROM pr_reports
            """))
            conn.execute(text("DROP TABLE pr_reports"))
            conn.execute(text("ALTER TABLE pr_reports_new RENAME TO pr_reports"))
            for column in ("repo", "pr_number", "ticket_key", "owner_id"):
                conn.execute(text(
                    f"CREATE INDEX ix_pr_reports_{column} "
                    f"ON pr_reports ({column})"
                ))
        print("~ pr_reports rebuilt with nullable repo / pr_number")
    else:
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE pr_reports ALTER COLUMN repo DROP NOT NULL"
            ))
            conn.execute(text(
                "ALTER TABLE pr_reports ALTER COLUMN pr_number DROP NOT NULL"
            ))
        print("~ pr_reports.repo / pr_number are now nullable")

    print("\nMigration complete.")


if __name__ == "__main__":
    main()
