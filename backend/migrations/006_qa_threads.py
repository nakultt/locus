"""
Migration: QA feedback threads

Adds the qa_threads table. A Slack reply carries only a channel and thread
timestamp, so the work items to reopen must be recorded when the QA
notification is posted -- there is no way to recover them from the reply.

Run from the backend/ directory:

    uv run python migrations/006_qa_threads.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect  # noqa: E402

from app import models  # noqa: E402,F401  (imported so create_all sees the tables)
from app.database import Base, engine  # noqa: E402


def main() -> None:
    existed = "qa_threads" in inspect(engine).get_table_names()
    Base.metadata.create_all(bind=engine)

    print("= qa_threads already present" if existed else "+ qa_threads")
    print("\nMigration complete.")


if __name__ == "__main__":
    main()
