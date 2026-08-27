"""
Migration: the calendar agent

Creates two tables, both via `create_all`:

  time_agent_settings   -- one row per user; the agent's dials
  schedule_proposals    -- reshuffles waiting for a human to confirm

Per user rather than per repo, because a calendar belongs to a person.

Four settings default to off, each for its own reason. `enabled`, because a
feature that starts touching a calendar unasked is the worst first impression
available. `auto_apply`, because a moved meeting is visible to everyone
invited. Both auto-replies, because they post to real people -- the same
category as auto-merge, and they earn the same treatment.

`working_hours_start` / `_end` are "HH:MM" read in `User.timezone` through a
real timezone library. The default zone is UTC+05:30 and the half-hour offset
breaks naive hour arithmetic, which is why nothing here is an integer offset.

`slack_member_id` holds `U04AB…`, not a handle. A Slack mention arrives in
message text as `<@U04AB…>` while `reviewer_contacts` stores handles --
different namespaces that never compare equal, so mention matching silently
never fires without this.

`schedule_proposals` exists because with `auto_apply` off a proposal has to
survive until somebody looks at it. `POST /schedule/apply` already existed as
the human-confirm step, which is exactly the propose-only shape this needs.

Run from the backend/ directory:

    uv run python migrations/024_calendar_agent.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect  # noqa: E402

from app import models  # noqa: E402,F401  (imported so create_all sees the tables)
from app.database import Base, engine  # noqa: E402

TABLES = ("time_agent_settings", "schedule_proposals")


def main() -> None:
    before = set(inspect(engine).get_table_names())

    Base.metadata.create_all(bind=engine)

    for table in TABLES:
        print(("= " if table in before else "+ ") + table)

    print("\nMigration complete.")


if __name__ == "__main__":
    main()
