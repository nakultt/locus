# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Branch convention

**`main` is the trunk.** Branch from it and target it with pull requests.

`feature/from-py` exists and has historically carried the work, but the two branches are now
identical. Treat `main` as authoritative.

## Commands

Backend (from `backend/`, dependencies managed with [uv](https://docs.astral.sh/uv/)):

```bash
uv sync --extra security          # --extra security installs Semgrep
uv run uvicorn main:app --reload
uv run pytest tests/ -q
uv run pytest tests/test_linking.py -q          # single file
uv run pytest tests/test_linking.py::test_name  # single test
uv run ruff check .
```

Frontend (from the repo root):

```bash
npm install
npm run dev
npm run build   # tsc -b && vite build
npm run lint
```

There is no frontend test runner. `npm run build` is the check — it type-checks via `tsc -b`
before bundling.

`SECRET_KEY` and `ENCRYPTION_KEY` in `backend/.env` are mandatory; the app refuses to start
without them. `ENCRYPTION_KEY` must never change once set — rotating it makes every stored
credential permanently undecryptable.

## Architecture

React SPA (Vite) → FastAPI backend → local OpenAI-compatible model server. PostgreSQL holds
users, conversations, PR jobs, and Fernet-encrypted integration credentials. See README.md
for the full diagram, API table, and per-integration setup.

**Inference is local and loopback-bound.** `app/services/llm.py` targets `MOE_BASE_URL`
(default `http://127.0.0.1:8081/v1`). The backend must run on the machine with the GPU — a
remotely hosted backend cannot reach that address. The server holds one model at a time, so
chat returns `503` with a remediation hint when none is loaded rather than an opaque
connection error. Generation is slow; the default timeout is 600s because agent loops chain
several calls.

**The agent is LangChain 1.x `create_agent`**, which compiles to a LangGraph — `AgentExecutor`
was removed in 1.0. Task events are emitted from the graph stream, and a tool that raises
becomes a failed task rather than an aborted run, so a request touching five integrations
keeps the four that succeeded. `tests/test_agent_migration.py` pins this message contract.

**Two background loops** start in `main.py`'s lifespan: `worker_loop` (PR analysis jobs) and
`qa_email_loop` (Gmail polling for QA replies). Jobs are persisted rather than held in
`BackgroundTasks`, which would lose queued work on restart. Both are single-instance —
multi-instance deployment needs row locking.

### Invariants worth knowing before you change things

These are deliberate and each has a failure mode behind it. Preserve them.

**Credentials live in ContextVars, never module globals.** Tool objects are module
singletons, so a module-level credential dict let concurrent users overwrite each other's
tokens — one user's agent could post to another user's Slack. `app/services/credential_context.py`
rebinds each service's module-level name to a `CredentialProxy` over a `ContextVar`. Tool
bodies still call `_github_config.get("token")` unchanged. When adding an integration, follow
the existing `get_<service>_tools()` factory pattern rather than reading credentials at import
time.

**Confirmed and unverified security findings are never merged.** Semgrep and Gitleaks are
deterministic rule matches, reported as confirmed; the LLM pass is reported as unverified. One
hallucinated "confirmed vulnerability" on a colleague's PR is enough for a team to stop
trusting the bot. `tests/test_pr_rendering.py` guards this.

**The security scan and the code review are separate passes.** The security scan answers "is
this exploitable"; on most PRs the answer is no, and reporting only that reads as approval.
`run_code_review()` in `security_scan.py` answers "is this correct, and does it do what the
team asked" — it receives the Slack threads and tickets as requirement context, so a diff that
ignores an agreed requirement is flagged instead of passing silently. Unparseable model output
degrades to an error string rather than an empty pass, so a broken review never reads as a
clean one.

`ReviewPriority` (`p1`–`p3`) is deliberately not `SecuritySeverity`. A `p1` means "do not merge
this" — a judgement about this change — not a CVSS-style rating. Don't collapse the two.

**Models that read attacker-influenced text have no tools bound.** Diff text, Slack messages,
and QA replies are controlled by anyone who can open a PR or post in a channel. The security
scanner, the code reviewer, and the QA classifier return findings or a verdict and nothing
else — they cannot act on what they read.

**Semgrep scans reconstructed files, not the diff.** Handed a unified diff it silently finds
nothing, because a `.diff` is not valid source in any language. The agent fetches post-change
file contents and scans those.

**Detected secrets are reported by location only** — file and line, never the value. Echoing
it into a PR comment would widen the exposure being reported.

**PR comments are idempotent** via a hidden `<!-- locus-pr-agent -->` marker; the agent edits
its own prior comment instead of appending one per push.

**Cross-user access returns 404, not 403.** A 403 confirms the id exists, which is enough to
enumerate other people's conversations. Identity always comes from the JWT — no endpoint
accepts a `user_id` parameter.

**PR agent settings resolve in exactly one place.** Every setting exists both on the repo
registration and on the account-wide defaults. `app/services/agent_settings.py` is the sole
arbiter of which wins — a repo value that is set wins, blank or unset falls back — so the
worker, the API, and the UI preview cannot disagree about what a run will do. Read effective
settings through it rather than reaching into either source directly. Defaults are stored one
row per user behind `GET`/`PUT /webhooks/defaults`; a merge run must read the *saved*
registration, not form state, which `tests/test_merge_uses_registration.py` pins after a bug
where ticked-but-unsubmitted settings were silently skipped.

**Third-party APIs return explicit `null`, so `.get(key, default)` does not save you.** The key
is present; its value is `None`, so the default never fires and the next subscript raises
`'NoneType' object is not subscriptable`. GitHub and Linear both do this on optional objects.
Guard the value, not the key's presence. `tests/test_github_null_fields.py` pins the cases
that already crashed.

**Slack's `url_verification` challenge must answer before the signature check.** Slack will
not save an Event Subscription until the endpoint echoes the challenge, and it sends that
challenge before the app is necessarily configured. Gating it behind `SLACK_SIGNING_SECRET`
makes the subscription unsavable, which blocks every signed event that would have followed.
Every other Slack event stays signature-gated.

**GitHub webhooks arrive in two content types.** The hook's "Content type" setting picks
between raw JSON and a form post carrying the JSON in a `payload` field. `_parse_webhook_body`
in `routers/webhooks.py` handles both — the form variant used to 400 as malformed JSON. HMAC
is verified over the raw body before parsing either way.

**Jira transitions are forward-only.** A target status that would move a ticket backwards is
refused, so a misconfigured status cannot drag a team's board backwards. Unrecognized statuses
pass through, since custom workflows are common.

**Scheduling goes through a real timezone library, never integer offsets.** The default zone
is `Asia/Kolkata` (UTC+05:30) and the half-hour offset breaks naive hour arithmetic. Times are
sent to Google with the zone attached rather than converted to UTC, which keeps recurring
events correct across a DST shift. Natural language is parsed by `dateparser`, which returns
nothing rather than guessing when no time can be read.

**The scheduler's solver is plain Python, not a model.** A model asked to rearrange a calendar
produces plausible-looking schedules with overlaps and missed deadlines. Events are classified
by movability, conflicts resolve least-disruptive-first, and anything with external attendees
is reported as blocked rather than moved.

## Database schema changes

New installs need no migrations — `Base.metadata.create_all()` at startup creates the current
schema. `backend/migrations/` exists to move *existing* databases forward. Scripts are numbered
and idempotent, so running the whole set is safe:

```bash
for m in migrations/0*.py; do uv run python "$m"; done
```

Note that `migrations/README.md`'s table is stale — it lists two scripts under old names while
nine exist on disk. Trust the directory.

## Conventions

Ruff lints with `E,F,I,UP,B` at line-length 100. The integration service modules carry
per-file ignores for bare excepts (`E722`) — a blanket "never let a third-party SDK crash the
agent" guard that predates the config. Don't add new bare excepts in other modules to match;
the existing ones are grandfathered, not a pattern to follow.

`vite` is aliased to `rolldown-vite` through `package.json` `overrides`. Frontend UI follows
shadcn conventions (`components.json`) over Radix primitives with Tailwind v4.

CORS allows any localhost port by regex, because Vite picks the next free port when its
default is taken and a fixed list breaks silently when that happens. Production origins stay
explicit.

`.gitattributes` declares `*.svg text`, so SVGs must be committed with LF. A CRLF-stored blob
gets rewritten on every checkout and shows as modified in a fresh clone.

## Known gaps

- The scheduler reads only the primary calendar; conflicts on secondary or shared calendars
  are invisible to it.
- Tests do not cover live calls to GitHub, Jira, or Slack. Response-shape handling for those
  is written against the documented APIs.
- The worker and the Gmail poller are both single-instance; multi-instance deployment would
  double-process without row locking.
- Gitleaks is optional and not bundled, so committed-secret detection is skipped when it is
  absent.

**README.md's "Known limitations" is stale on one point:** it says repo registration is
API-only with no UI. `src/pages/pr-agent.tsx` now calls `registerRepo`/`unregisterRepo`, so
that gap is closed. Verify against the code before repeating a limitation from either
document.
