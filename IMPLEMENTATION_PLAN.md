# Locus Implementation Plan

> **Status.** Phase 0, Feature A and Feature B are implemented; 166 tests pass. Two items in
> the original plan were deliberately **not** built -- proactive scheduler triggers (3.5) and
> the Phase 4 scheduler infrastructure. Both are listed under "Deferred" with the reasoning.
> Nothing has run against live third-party services -- see "Not yet verified".

Two flagship features, plus the foundation they both require.

- **Feature A — PR Context Agent**: on PR open, gather related Slack/Jira context, scan the
  diff for vulnerabilities, comment on the PR, post a summary to Slack.
- **Feature B — Adaptive Scheduler**: when a new event or deadline lands, re-arrange the
  existing calendar to protect deadlines.

Both are *proactive* — they run without anyone typing into the chat box. That is the
architectural break from what exists today, and it drives the ordering below.

---

## Phase 0 — Foundation (blocking)

Nothing below Phase 0 can ship without these. They are not optional cleanup; each one
directly blocks a flagship feature.

### 0.1 Enforce authentication - DONE

`verify_token()` in `app/security.py:63` is defined and never called. Every endpoint trusts a
client-supplied `user_id`.

- Add `get_current_user` dependency (HTTPBearer → `verify_token` → load user).
- Apply to every route in `auth.py`, `chat.py`, `conversations.py`, `settings.py`.
- Remove `user_id` from `ChatRequest`, `ConversationCreate`, `GeminiKeySet` so it cannot be spoofed.
- Scope conversation lookups by `owner_id`.
- Replace the `SECRET_KEY` fallback in `security.py:35` with a startup failure.

**Blocks:** everything. Both features store cross-tool workplace data (private Slack
discussions, internal ticket contents, source diffs) keyed by user. Today any caller can read
another user's data by changing an integer.

### 0.2 Kill the credential globals - DONE

All 14 services use a module-level `_x_config` dict mutated by `get_*_tools()`. Tool objects
are module singletons, so concurrent requests overwrite each other's tokens.

- ✅ `slack.py` converted to closures; `_slack_config` deleted.
- Remaining 13: `github.py`, `calendar.py`, `jira.py` next (the PR agent bypasses these by
  calling APIs directly, but the chat agent does not).
- Delete every `_x_config` global.

**Blocks:** all background work. A scheduled job and a live request would stomp each other's
credentials constantly. Feature A and B are both background jobs.

### 0.3 Fix the planner API key ✅ DONE

`task_planner.py` read a server-level `GOOGLE_API_KEY` while everything else used the user's
key, so when that env var was unset the LLM planner silently never ran and every request fell
back to `_fallback_parse_tasks` — the keyword matcher.

Resolved by the local-first swap: `parse_tasks_from_message` now calls the shared
`app/services/llm.get_llm()` like every other call site. There is no per-user key left to
thread, so the failure mode is gone rather than fixed.

### 0.4 Calendar correctness - DONE

`_parse_datetime` (`calendar.py:119`) understands only "2pm", "3pm", "10am" — everything else
silently becomes 9am. It builds naive server-local times and labels them `"timeZone": "UTC"`,
so every event is wrong by the user's UTC offset.

- Replace with `dateparser` (handles "next Tuesday at 4", "in 2 hours").
- Add `timezone` column to `User`, populated at signup from
  `Intl.DateTimeFormat().resolvedOptions().timeZone`.
- Send real IANA timezones to the Google API.

**Blocks:** Feature B entirely. Rescheduling on top of a parser that can't read "4pm" produces
confidently wrong calendars.

---

## Phase 1 — Missing read tools

Both features are read-heavy; the codebase is almost entirely write-shaped.

### 1.1 Slack read (user token now available)

| Tool | API | Token |
|---|---|---|
| `slack_read_channel` | `conversations.history` | bot |
| `slack_read_thread` | `conversations.replies` | bot |
| `slack_search` | `search.messages` | **user** (`xoxp-`) |

- Change `get_slack_tools(bot_token)` → `(bot_token, user_token)`.
- Store both in the credentials dict: `{"bot_token", "user_token", "team_id"}`.
- Add a cached user-ID → name resolver (`users.list` once per workspace). Raw `<@U024BE7LH>`
  makes every summary unreadable, and per-message `users.info` will exhaust rate limits.

### 1.2 GitHub diff access

No tool can currently read code — a blocker for the vulnerability scan.

- `github_get_pr_diff` — `GET /repos/{o}/{r}/pulls/{n}` with `Accept: application/vnd.github.v3.diff`
- `github_get_pr_files` — per-file patches, additions/deletions
- `github_list_pr_comments` — needed for idempotency (see 2.5)

### 1.3 Calendar read

- `calendar_list_events(start, end)` — the agent currently cannot see a calendar at all
- `calendar_find_free_slots(duration, range, working_hours)`
- `calendar_move_event(event_id, new_start)` — distinct from `update_event`; preserves attendees

---

## Phase 2 — Feature A: PR Context Agent

### 2.1 Webhook infrastructure

No webhook handling exists anywhere. New router `app/routers/webhooks.py`.

- `POST /webhooks/github` — verify `X-Hub-Signature-256` (HMAC-SHA256) **before** parsing.
  Unauthenticated by design; the signature *is* the auth.
- Store `webhook_secret` per user/repo.
- Return 200 immediately, process async — GitHub times out at 10s and our pipeline takes
  30–60s.
- Persist to a `pr_jobs` table; a worker picks it up. Do not rely on FastAPI `BackgroundTasks`
  (lost on restart, no retry).

### 2.2 Ticket-key extraction

The linking primitive everything depends on. Cheap and high-accuracy.

- Regex `[A-Z]{2,10}-\d+` over PR title, branch name, body, commit messages.
- Validate against Jira/Linear so `UTF-8` or `HTTP-2` don't become false tickets.

### 2.3 Context gathering

Given a ticket key:
- Jira: `jira_search_issues` → status, assignee, priority, description
- Slack: `slack_search` for the key, then `slack_read_thread` on each hit
- GitHub: prior PRs referencing the same key

### 2.4 Vulnerability scan

**Two-layer, deliberately.** An LLM alone is not a security scanner — it misses reliably and
hallucinates findings.

- **Layer 1 — deterministic**: Semgrep (`p/security-audit`, `p/secrets`) on changed files.
  Real rules, no false confidence. Gitleaks for credentials.
- **Layer 2 — LLM review**: logic flaws Semgrep can't see — authz gaps, injection via
  untrusted input, unsafe deserialization. Feed it the diff plus Semgrep output so it explains
  rather than re-detects.
- Report Semgrep findings as confirmed; label LLM findings as unverified. Never merge the two
  into one list — a wrong "CONFIRMED VULNERABILITY" on someone's PR destroys trust in the tool
  immediately.

### 2.5 Write-back

- `github_add_pr_comment` (already exists at `github.py:486`)
- **Idempotency is mandatory**: PR events fire on every push. Tag the comment with a marker
  (`<!-- locus-bot -->`), search existing comments, update instead of appending. Without this
  the bot spams 30 comments on an active PR.
- Slack summary via existing `slack_send_message`.

### 2.6 Guardrails

- Never post secrets found by Gitleaks into a PR comment or Slack — say "credential detected in
  `file:line`", nothing more. Posting the secret widens the exposure.
- Diff content reaches the local model. Inference is on-machine, so nothing leaves the host.
- **Prompt injection is a live risk**: PR descriptions and Slack messages are attacker-influenced
  and flow into a prompt whose agent holds write access to Jira, GitHub, and Gmail. Treat all
  fetched content as data, never instruction. Keep the scanner on a *separate* LLM call with no
  tools bound — it should return findings, not take actions.

---

## Phase 3 — Feature B: Adaptive Scheduler

IT SHOULD BE A SEPERATE PAGE IN UI SHOWING A IN APP CALENDER AND NEATLY SHOWING WHAT CALENDER EVENTS NEEDS TO BE CHANGED OR MOVED OR REPLACED OR REMOVED OR ADDED , LIKE THAT USING COLORS

### 3.1 Deadline model

Rescheduling requires knowing what is immovable. New `deadlines` table, sourced from Jira due
dates, Linear targets, sprint ends, and manual entry.

### 3.2 Constraint model

Not every event can move. Per-event classification:

| Class | Movable | Examples |
|---|---|---|
| Hard-fixed | No | External customers, interviews, all-hands |
| Soft-fixed | With notice | Team meetings, 1:1s |
| Flexible | Yes | Focus blocks, self-scheduled work |

Infer from attendee count, organizer, recurrence; allow user override. Store as
`event_constraints` keyed by Google event ID.

### 3.3 Rescheduling engine

**Write this as plain Python, not an LLM call.** Constraint satisfaction is exactly what LLMs
are worst at — it will produce plausible schedules with overlapping events and missed deadlines.

- Deterministic solver: sort by deadline proximity, respect constraint class, honour working
  hours and timezone, never double-book.
- The LLM's job is *explaining* the proposal in prose, not computing it.

### 3.4 Proposal → approval → execute

**Never auto-move meetings with other attendees.** A silent reschedule sends invite updates to
five people. That is the single fastest way to make the product unusable in a real workplace.

- Generate the plan → present as a diff (before/after) → user approves → execute.
- Auto-execute allowed only for solo events, and only if the user opts in.
- Draft the "shifting this, sorry" note for attendees.

### 3.5 Trigger points

- New calendar event created (poll, or Google Calendar push notifications)
- New Jira/Linear ticket with a near-term due date
- Manual: "re-plan my week"

---

## Phase 4 — Scheduler infrastructure

Needed for Feature B triggers and every digest feature.

- APScheduler in-process to start; Celery + Redis when it outgrows one instance.
- Background jobs load and decrypt per-user credentials directly — **only works after 0.2**.
- Morning brief as the first scheduled feature: uses every integration already built.

---

## Ordering

```
0.1 auth ─┐
0.2 globals ─┼─→ 1.1 slack read ─┐
0.3 planner ─┘                   ├─→ 2.x  PR Context Agent
             1.2 github diff ────┘
0.4 calendar ──→ 1.3 calendar read ──→ 3.x  Adaptive Scheduler
                                   └──→ 4.x  Scheduler infra
```

Feature A and Feature B are independent after Phase 1 and can proceed in parallel.

**Suggested first slice:** 0.1 → 0.2 (slack/github only) → 1.1 → 1.2 → 2.1 → 2.2 → 2.3 → 2.5.
That is Feature A minus the vulnerability scan — end-to-end value, and it proves the webhook
and context pipeline before adding the security layer.

---

## Risks

| Risk | Mitigation |
|---|---|
| LLM security scan produces false positives | Semgrep is the source of truth; LLM findings labelled unverified |
| Bot spams PR comments | Marker-based idempotency (2.5) |
| Auto-reschedule annoys attendees | Proposal → approval gate (3.4) |
| Prompt injection via PR/Slack text | Scanner LLM has no tools bound; content is data |
| Rate limits (Slack Tier 3 ~50/min) | Cache user list; batch thread fetches |
| Large diffs blow the context window | Capped at 60k chars in `github_pr.MAX_DIFF_CHARS` |
| Source code leaving the machine | Resolved: inference is local-only |

---

## Shipped

**Local-first LLM.** Gemini removed entirely. `app/services/llm.py` targets any
OpenAI-compatible endpoint (default: MoE Model Manager on `127.0.0.1:8081/v1`).
`GET /api/settings/llm` reports readiness; chat returns 503 with a remediation hint instead of
an opaque connection error. Dropped `users.encrypted_gemini_key`, the three `gemini-key`
endpoints, and the dead `process_without_llm` keyword fallback.

**Feature A — PR Context Agent.**

| Component | File |
|---|---|
| Ticket-key extraction | `app/services/linking.py` |
| PR metadata, diffs, idempotent comments | `app/services/github_pr.py` |
| Semgrep + Gitleaks + LLM review | `app/services/security_scan.py` |
| Pipeline and rendering | `app/services/pr_agent.py` |
| HMAC-verified webhook | `app/routers/webhooks.py` |
| Background job runner | `app/services/worker.py` |
| `PRJob`, `RepoWebhook`, `User.timezone` | `app/models.py` |
| Schema migration | `migrate_local_first.py` |

Also added `User.timezone`, defaulting to `Asia/Kolkata` (§0.4 groundwork; the date parser
itself is still outstanding).

**Slack read tools.** `slack.py` rewritten as closures with `slack_read_channel`,
`slack_read_thread`, and `slack_search` added. `slack_search` is registered only when a user
token is present, so the agent is never offered a tool that always fails. The connect form
takes both tokens; `credentials.bot_token` is mirrored from `api_key` at submit.

**Tooling and layout.** uv project (`pyproject.toml` + `uv.lock`), ruff and pytest config,
37-test suite, `.env.example`, `.gitattributes`, numbered `migrations/`, removed a stale
untracked `frontend/` Next.js build tree and a duplicate requirements file.

**Dependency upgrade to latest.** LangChain 0.3 → 1.3.15, langchain-core → 1.5.4,
langchain-openai → 1.4.3, LangGraph 0.3 → 1.2.11, bcrypt 4.0.1 → 5.0.0. Dropped
`langchain-community` (unused) and `passlib` (unmaintained since 2020; it raises on
bcrypt ≥ 5, which is what pinned bcrypt to 4.0.1).

This brought the LangGraph migration with it rather than as a separate project. LangChain 1.0
removed `AgentExecutor` and `create_tool_calling_agent`; `create_agent` returns a compiled
LangGraph, so the agent now:

- takes and returns messages instead of `{"input"}` → `{"output", "intermediate_steps"}`
- emits task events from the graph stream **as work happens**, replacing the old approach of
  replaying `intermediate_steps` after the run finished — the UI's progress feed was a replay
- reads failure from `ToolMessage.status` instead of `"error" not in observation[:50]`, which
  missed any error message longer than 50 characters
- survives a tool raising, via a `ToolErrorMiddleware` that converts the exception into an
  error `ToolMessage`. Previously one bad integration aborted the whole run and discarded the
  work already completed.

`security.py` now calls bcrypt directly. The stored `$2b$12$` format is unchanged so existing
passwords still verify, and inputs over bcrypt's 72-byte limit are SHA-256 pre-hashed rather
than truncated — truncation would make two long passwords sharing a prefix interchangeable.

### Bugs found and fixed during verification

| Bug | Impact |
|---|---|
| **Semgrep scanned the raw `.diff`** | Found **0** issues on code containing shell and SQL injection. Semgrep parses an AST; a diff is not valid source. Now reconstructs changed files and scans those — verified detecting a real finding with correct path and line. |
| `shutil.which` missed venv binaries | Semgrep installed but reported unavailable when the server runs without an activated venv — the normal case under a process manager. Now checks the interpreter's own directory first. |
| Mid-file imports in `agent.py` | Import-order fragility; moved to the top. |
| Raw exception text returned to clients | `chat.py` echoed upstream API errors. Now logged server-side, generic message returned. |
| `tsconfig.app.json` used removed `baseUrl` | Blocked **all** frontend typechecking under TS 5.9. |
| Pydantic v1 `class Config` | 5 deprecation warnings; breaks on Pydantic v3. |

### Verified

- 37 pytest tests: ticket extraction (incl. false positives), HMAC across 7 attack cases,
  finding separation, secret redaction, severity ordering, and the LangChain 1.x message
  contract (tool-call extraction, error status, full streaming lifecycle)
- Login round-trip under bcrypt 5; 200-character passwords hash and stay distinguishable
- App boots; 21 routes registered; background worker starts
- Live webhook flow: signed → 202 queued; tampered/wrong-secret/unsigned → 401; draft and
  non-PR actions ignored; exactly one job created
- Slack dual-token round-trip through encryption; tool count 6 with user token, 5 without
- Semgrep detects a real finding with correct repo-relative path and line
- `ruff check` clean; frontend typechecks and builds

### Not yet verified

No run against a live GitHub webhook, a loaded MoE server, or real Jira/Slack workspaces. The
Jira and Slack response-shape handling is written against the documented APIs and is the most
likely place for a field-name mismatch on first real use.

### Next

1. **§0.1 auth** — required before any untrusted user touches this
2. **§0.2 credential globals** — 13 services remain
3. Repo-registration endpoint — webhook secrets are inserted by hand today, so the PR agent
   cannot be set up through the UI
4. Frontend view for PR job history


---

## Phase 0 and Feature B: what was built

### 0.1 Authentication

`app/dependencies.py` holds a single `get_current_user`. Every user-scoped route derives its
user from the verified JWT, and `user_id` was removed from `IntegrationCreate`, `ChatRequest`,
`ConversationCreate`, and `RepoRegister` so it cannot be supplied at all. Routes carrying it in
the path lost it too: `/auth/integrations/{id}` became `/auth/integrations`, and the same for
conversations, jobs, repos, and the agent summary.

Conversation lookups return **404 rather than 403** for another user's id. A 403 confirms the
row exists, which is enough to enumerate other people's chats.

Verified: unauthenticated requests get 401; one user cannot read, rename, or delete another's
conversations; integrations list per-user; and a profile update touches only the caller. The
last of those was the account-takeover hole -- `PUT /auth/user/{id}` previously let anyone set
any password.

### 0.2 Credential isolation

All 13 remaining services kept credentials in a module-level dict that the `@tool` functions
read at call time. Tool objects are module singletons, so two users running agents at once
overwrote each other's tokens.

`app/services/credential_context.py` provides a `CredentialProxy` backed by a `ContextVar`.
Each service's module-level name is rebound to one, so `_github_config.get("token")` now
resolves against the calling task's value. All 54 tool bodies work unchanged.

A ContextVar rather than closures because it fixes every service uniformly without rewriting
54 functions, and it covers the background worker, which runs outside any request.

Verified with two concurrent tasks interleaving at the exact point that used to corrupt
tokens. The same test against the old pattern shows Alice receiving Bob's token.

### 0.4 Calendar correctness

`app/services/datetimes.py` replaces the parser that understood "2pm", "3pm", and "10am" and
silently returned 9am for anything else. It handles "next Tuesday 10:30", "Friday morning",
"in 90 minutes", and ISO strings, and returns `None` when no time is named -- forcing the
caller to decide rather than inventing one.

Two phrasings needed normalising: dateparser fails outright on a "next" prefix, and does not
map "morning"/"afternoon" to hours.

Timezone now flows from `User.timezone` through the agent into the calendar service, and
events are sent with an IANA zone attached instead of a hardcoded `"UTC"` label on
server-local times. On a UTC host every IST event was previously 5h30m off, silently.

### Feature B: Adaptive Scheduler

| Piece | File |
|---|---|
| Calendar read/move tools | `app/services/calendar.py` |
| Constraint solver | `app/services/scheduler.py` |
| Plan / apply / conflicts API | `app/routers/schedule.py` |
| Dashboard | `src/pages/scheduler.tsx` |

The solver is plain Python. Constraint satisfaction is what language models are worst at:
asked to rearrange a calendar they produce plausible-looking schedules with overlaps and
missed deadlines, and the error is hard to spot precisely because the output reads well.

Events are classified by how movable they are -- flexible solo time, soft-fixed internal
meetings, hard-fixed anything with external attendees -- and conflicts are resolved
least-disruptive-first. Hard-fixed events are never moved; when one blocks the way the
proposal says so rather than dropping the conflict.

Planning and applying are separate endpoints. `POST /api/schedule/plan` writes nothing, and
the response flags whether approval is needed because other attendees are involved.

Two invariants are tested directly: proposed moves never overlap each other, and a plan that
would move an external meeting reports it as blocked instead.

### Also completed in this pass

**Required secrets.** `SECRET_KEY` and `ENCRYPTION_KEY` now raise at import instead of falling
back. The generated encryption key changed on every restart, silently making stored
credentials undecryptable; the default JWT secret was a literal committed to a public repo, so
anyone could mint a token for any user -- which would have walked straight past the auth work
in 0.1. Tests supply throwaway values via `tests/conftest.py`.

**Deadlines and constraints (3.1, 3.2).** `deadlines` records due dates the scheduler will not
push work past, and `event_constraints` overrides its guess at how movable an event is. The
attendee-count heuristic is wrong often enough to need one: a solo block can be immovable and
a large meeting trivially movable. Endpoints under `/api/schedule/`.

**Migration 001 was broken.** It queried `information_schema`, which is Postgres-only, so it
failed outright on SQLite -- the default for local development. Rewritten against SQLAlchemy's
inspector and renamed to match what it actually does (`001_add_user_name.py`; it never touched
conversations). All 8 migrations now run clean on both an existing and a fresh database.

### Deferred, with reasons

**3.5 Scheduler triggers.** The scheduler runs on request: plan, review, apply. Firing it
automatically when a Jira ticket appears means proposing calendar changes nobody asked for,
and the proposal has to reach the user somewhere -- Slack DM or email -- which is a
notification system rather than a scheduling one. Worth building once the on-request flow has
been used enough to know which triggers are actually wanted.

**Phase 4 scheduler infrastructure.** The plan called for APScheduler or Celery. Two
in-process asyncio loops already cover the current need (PR jobs, Gmail polling), and adding a
third dependency for a feature with no proactive triggers yet would be premature. The real
forcing function is multi-instance deployment, which needs row locking regardless.

### Not yet verified

No part of this has run against live Google Calendar, Jira, Slack, or GitHub. Response shapes
are written against the documented APIs. The solver, the date parser, and the auth and
credential-isolation work are exercised directly and do not depend on those services, but
every call that reads or writes to them is unproven.
