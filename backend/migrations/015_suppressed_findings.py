"""
Migration: dismissed findings

Adds one table:

  suppressed_findings  -- findings someone marked as not worth reporting

Without it a false positive is permanent. The scan re-runs on every push, the
finding comes back, and the only way to silence it is to stop reading the
comment -- which silences the true positives too. That is the loss of trust the
confirmed/unverified split exists to prevent, reached from the other side.

Rows are keyed by normalised file path and title rather than line number: an
edit above a finding shifts it, and a line-keyed suppression would lapse
silently the next time anyone touched the file.

`pr_number` is nullable, and null means the suppression applies to every pull
request in the repo.

Run from the backend/ directory:

    uv run python migrations/015_suppressed_findings.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect  # noqa: E402

from app import models  # noqa: E402,F401  (imported so create_all sees the tables)
from app.database import Base, engine  # noqa: E402

TABLES = ["suppressed_findings"]


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
            print(f"! {table} was not created -- check the model import")

    print("\nMigration complete.")


if __name__ == "__main__":
    main()
