"""
Migration: interruptions

Creates `interruption_events` via `create_all`.

This cannot live in `communication_events`. That table's `repo` and
`pr_number` are NOT NULL and an interruption has neither -- somebody pinged you
in a channel, which belongs to no pull request. Reusing it would mean inventing
a sentinel repo, and the next person to read the timeline takes that sentinel
for a real repository.

The invariant "every message is recorded, not summarized" is unchanged by this:
`comms_log` remains the only writer for anything keyed to a pull request. This
is a second table precisely because that one requires a repo and a PR number.

`importance_source` (reviewer | worklist | classifier) is what makes a wrong
escalation debuggable. Two of the three are deterministic facts; only the third
is a model's judgement, and the UI is expected to render it as the weaker
claim it is.

`reply_body` stores what was actually sent rather than a reconstruction -- the
same reason `merge_actions._qa_email_text` returns its body to the caller.

Run from the backend/ directory:

    uv run python migrations/025_interruptions.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect  # noqa: E402

from app import models  # noqa: E402,F401  (imported so create_all sees the tables)
from app.database import Base, engine  # noqa: E402


def main() -> None:
    before = set(inspect(engine).get_table_names())

    Base.metadata.create_all(bind=engine)

    print(("= " if "interruption_events" in before else "+ ") + "interruption_events")
    print("\nMigration complete.")


if __name__ == "__main__":
    main()
