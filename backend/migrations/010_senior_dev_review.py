"""
Migration: senior-dev review loop

Adds two tables:
  pr_reviews        -- current review state for one pull request
  pr_review_rounds  -- append-only history of each leg of the loop

And four nullable columns, on both settings sources:
  repo_webhooks.reviewers            pr_agent_defaults.reviewers
  repo_webhooks.review_slack_channel pr_agent_defaults.review_slack_channel

Nullable with no default, deliberately: "not set" is what lets a per-repo blank
fall through to the account defaults instead of overriding them with emptiness.
See app/services/agent_settings.py.

Run from the backend/ directory:

    uv run python migrations/010_senior_dev_review.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, text  # noqa: E402

from app import models  # noqa: E402,F401  (imported so create_all sees the tables)
from app.database import Base, engine  # noqa: E402

TABLES = ("pr_reviews", "pr_review_rounds")

# (table, column, DDL type) -- all nullable, no default.
COLUMNS = [
    ("repo_webhooks", "reviewers", "TEXT"),
    ("repo_webhooks", "review_slack_channel", "VARCHAR(255)"),
    ("pr_agent_defaults", "reviewers", "TEXT"),
    ("pr_agent_defaults", "review_slack_channel", "VARCHAR(255)"),
    # Carries a review's verdict and body from the webhook to the worker.
    ("pr_jobs", "payload_json", "TEXT"),
]


def main() -> None:
    before = set(inspect(engine).get_table_names())
    Base.metadata.create_all(bind=engine)

    for table in TABLES:
        print(f"= {table} already present" if table in before else f"+ {table}")

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
