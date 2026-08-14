# Migrations

New installs don't need these at all — `Base.metadata.create_all()` runs at startup and
creates the current schema. Migrations exist to move an *existing* database forward.

Each script is idempotent, so running the whole set is safe. From the `backend/` directory:

```bash
for m in migrations/0*.py; do uv run python "$m"; done
```

Or one at a time, in numeric order:

```bash
uv run python migrations/014_job_recovery.py
```

| Script | Adds |
|---|---|
| `001_add_user_name.py` | `users.name` |
| `002_local_first_and_pr_agent.py` | `users.timezone`, `pr_jobs`, `repo_webhooks`; drops `users.encrypted_gemini_key` |
| `003_pr_agent_docs_export.py` | `repo_webhooks.export_to_docs` |
| `004_pinned_context_docs.py` | `repo_webhooks.context_doc_ids` |
| `005_merge_actions.py` | `repo_webhooks`: `qa_emails`, `jira_done_status`, `close_issues_on_merge` |
| `006_qa_threads.py` | `qa_threads` |
| `007_user_timezone.py` | `users.timezone` (backfilled), for databases `002` predates |
| `008_deadlines_and_constraints.py` | `deadlines`, `event_constraints` |
| `009_pr_agent_defaults.py` | `pr_agent_defaults` |
| `010_senior_dev_review.py` | `pr_reviews`, `pr_review_rounds` |
| `011_communication_log.py` | `communication_events`, plus reviewer contact columns on both settings sources |
| `012_task_context.py` | `communication_events.ticket_key`, `pr_reviews.ticket_keys` |
| `013_global_context_docs.py` | `pr_agent_defaults.context_doc_ids` |
| `014_job_recovery.py` | `pr_jobs.started_at`, `pr_jobs.attempts` |

A migration that added `users.encrypted_gemini_key` was removed when Locus moved to
local-only inference. Fresh databases never create the column; existing ones have it dropped
by `002`.

**Keep this table in sync when adding a script.** It was stale for a long stretch — listing
two entries under names that did not match the files on disk — which is worse than having no
table at all, because it reads as authoritative. The directory is the source of truth.
