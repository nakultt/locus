# Migrations

Run in numeric order, from the `backend/` directory:

```bash
uv run python migrations/002_local_first_and_pr_agent.py
```

Each script is idempotent — re-running it reports what already exists and changes nothing.

| Script | Adds |
|---|---|
| `001_add_conversations.py` | `conversations`, `messages` |
| `002_local_first_and_pr_agent.py` | `users.timezone`, `pr_jobs`, `repo_webhooks`; drops `users.encrypted_gemini_key` |

A migration that added `users.encrypted_gemini_key` was removed when Locus moved to
local-only inference. Fresh databases never create the column; existing ones have it dropped
by `002`.

New installs don't need these at all — `Base.metadata.create_all()` runs at startup and
creates the current schema. Migrations exist to move an *existing* database forward.
