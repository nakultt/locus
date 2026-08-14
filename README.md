# Locus

Cross-tool context for people with IT jobs.

Slack holds the discussion, Jira holds the requirement, GitHub holds the code — and nothing joins them. Locus does. It connects your workplace tools, runs entirely on **local models**, and stitches the scattered facets of a work item back together.

No cloud LLM. No API keys. Your source diffs and private Slack threads never leave your machine.

---

## What it does

**Chat across your tools.** Natural-language commands that fan out across Jira, GitHub, Linear, Slack, Notion, Gmail, Calendar, and the Google Workspace suite — with a live task plan streamed to the UI as the agent works.

The agent runs on **LangChain 1.x `create_agent`**, which compiles to a LangGraph. Task events are emitted from the graph stream as work happens, and a tool that raises becomes a failed task rather than an aborted run — a request touching five integrations keeps the four that succeeded.

**Adaptive Scheduler.** When a new meeting or deadline lands, works out which existing events must move so the deadline still holds — then shows you the plan before touching anything. The solver is plain Python: a model asked to rearrange a calendar produces plausible-looking schedules with overlaps and missed deadlines.

Events are classified by how movable they are — flexible solo time, soft-fixed internal meetings, hard-fixed anything with external attendees — and conflicts resolve least-disruptive-first. A meeting with external attendees is never moved automatically; the plan reports it as blocked.

**PR Context Agent.** Open a pull request and Locus automatically:

1. Extracts ticket keys from the title, branch, body, and commits
2. Pulls the matching Jira/Linear tickets — status, assignee, summary
3. Searches Slack for prior discussion of the same work
4. Scans the diff for vulnerabilities (Semgrep + Gitleaks, plus an LLM pass)
5. Comments the assembled context on the PR — updating in place, not spamming
6. Posts a summary to your Slack channel

---

## Architecture

```
┌─────────────┐     ┌──────────────────────┐     ┌────────────────────┐
│  React SPA  │────▶│   FastAPI backend    │────▶│  MoE Model Manager │
│   (Vite)    │◀────│                      │◀────│  127.0.0.1:8081/v1 │
└─────────────┘ SSE │  ┌────────────────┐  │     │  (local GPU)       │
                    │  │  LangChain     │  │     └────────────────────┘
┌─────────────┐     │  │  agent + tools │  │
│   GitHub    │────▶│  └────────────────┘  │     ┌────────────────────┐
│  webhooks   │     │  ┌────────────────┐  │────▶│  Jira · Slack ·    │
└─────────────┘     │  │  PR worker     │  │     │  GitHub · Linear · │
                    │  └────────────────┘  │     │  Google Workspace  │
                    └──────────────────────┘     └────────────────────┘
                              │
                       ┌──────────────┐
                       │  PostgreSQL  │  encrypted credentials (Fernet)
                       └──────────────┘
```

### Local-first inference

Locus talks to any OpenAI-compatible endpoint. By default that is [MoE Model Manager](https://github.com/nakultt/MoE) on `http://127.0.0.1:8081/v1`, serving Qwen3.6 35B and Gemma 4 26B on local hardware.

| Mode | Model | Used for |
|---|---|---|
| Fast (default) | `gemma-4-26b-a4b` | Chat, task planning, PR summaries |
| Smart | `qwen3.6-35b-a3b` | Complex multi-step requests |

**MoE holds one GPU model at a time.** Load a text model before using Locus; `GET /api/settings/llm` reports readiness, and chat returns `503` with a remediation hint rather than an opaque connection error.

Because inference is local, **the backend must run on the machine with the GPU.** A remotely hosted backend cannot reach `127.0.0.1:8081`.

---

## Setup

### Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.11–3.13 | Backend |
| Node 18+ | Frontend |
| PostgreSQL | SQLite works for local dev |
| [MoE Model Manager](https://github.com/nakultt/MoE) | Running with a text model loaded |
| `semgrep` | Optional — enables confirmed security findings |
| `gitleaks` | Optional — enables secret detection |

### Backend

Dependencies are managed with [uv](https://docs.astral.sh/uv/).

```bash
cd backend && uv sync --extra security
```

`--extra security` installs Semgrep, which produces the confirmed half of the PR security scan. Without it only the unverified LLM pass runs.

Then copy `backend/.env.example` to `backend/.env` and fill in `SECRET_KEY` and `ENCRYPTION_KEY`:

```bash
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

> **Both keys are required — the app refuses to start without them.** A generated
> `ENCRYPTION_KEY` would change on every restart, silently making every stored credential
> undecryptable, and a default `SECRET_KEY` would let anyone forge a token for any user. Set
> them once and keep them.

Upgrading an existing database:

```bash
for m in migrations/0*.py; do uv run python "$m"; done
```

Each migration is idempotent, so running the whole set is safe.

Run it:

```bash
uv run uvicorn main:app --reload
```

### Frontend

```bash
npm install && npm run dev
```

### Checks

```bash
cd backend && uv run pytest tests/ -q && uv run ruff check .
```
```bash
npm run build
```

---

## Authentication

Every user-scoped route requires `Authorization: Bearer <jwt>`, issued by `/auth/signup` and
`/auth/login`. Identity comes from the token — no endpoint accepts a `user_id`, so one account
cannot read or modify another's data by changing an integer.

Requests to another user's conversation return **404 rather than 403**: a 403 would confirm
the id exists, which is enough to enumerate other people's chats.

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login -H "Content-Type: application/json" -d '{"email":"you@example.com","password":"..."}' | python -c "import json,sys;print(json.load(sys.stdin)['token'])")
```

Service credentials are held in a `ContextVar` per asyncio task, so two users running agents
concurrently cannot see each other's tokens.

---

## Integrations

| Service | Auth | Notes |
|---|---|---|
| GitHub | PAT | Repos, issues, PRs, diffs |
| Jira | API token + email + URL | Issues, JQL, projects, workflows |
| Linear | OAuth | Issues, teams, states |
| Slack | OAuth (bot + user token) | `xoxp-` user token needed for search |
| Notion | Integration token | Pages, search |
| Gmail / Calendar / Docs / Sheets / Slides / Drive / Forms / Meet | Google OAuth | One consent covers all |
| Bugasura | API key | Bug tracking |

### Slack tokens

Slack takes **two** tokens, both entered on the Slack card in Integrations:

| Token | Field | Enables |
|---|---|---|
| `xoxb-…` | Bot Token | Posting messages, listing and reading channels |
| `xoxp-…` | User Token (optional) | `slack_search` — searching message history |

`search.messages` cannot be called with a bot token, and searching is what finds a PR's prior discussion. Without a user token the `slack_search` tool is not registered at all — rather than offered and always failing — and the PR agent logs that it skipped the search.

Required scopes:
- **Bot:** `chat:write`, `channels:read`, `channels:history`, `groups:history`, `users:read`
- **User:** `search:read`

Do not add any `admin.*` scope; those are Enterprise Grid only and will block installation.

---

## PR Context Agent

### Setup

**1. Connect GitHub** in Integrations, with a personal access token carrying `repo` scope. This is what reads PRs and posts comments — without it the pipeline fails immediately. Jira and Slack are optional; each simply contributes less context if absent.

**2. Expose the backend.** GitHub cannot reach `localhost`, so for local development open a tunnel:

```bash
cloudflared tunnel --url http://localhost:8000
```

Put the URL it prints in `backend/.env` as `PUBLIC_BASE_URL` and restart the backend.

**3. Register the repo.** This mints the webhook secret:

```bash
curl -X POST http://localhost:8000/webhooks/repos -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"repo":"owner/name","slack_channel":"#dev-updates"}'
```

The response carries `webhook_url` and `webhook_secret`. **The secret is shown once** — it is stored encrypted and no endpoint reads it back. Re-registering the same repo rotates it and invalidates the old one.

**4. Add the webhook in GitHub** — repo **Settings → Webhooks → Add webhook**:

| Field | Value |
|---|---|
| Payload URL | the `webhook_url` from step 3 |
| Content type | `application/json` |
| Secret | the `webhook_secret` from step 3 |
| Events | **Let me select individual events → Pull requests** only |

**5. Open a PR.** Analysis runs on `opened`, `reopened`, `synchronize`, and `ready_for_review`. Drafts are skipped.

To also track the senior-dev review loop, add the **Pull request reviews** event to the same webhook alongside **Pull requests**. Without it the queue stays empty — GitHub sends review verdicts as a separate event type.

**6. Merge it.** On merge Locus transitions the Jira ticket, closes linked GitHub issues, and emails the test team a brief of what to verify. Configure the target status, QA addresses, and pinned context docs when registering the repo.

### Triggering without a webhook

To test the pipeline, re-run after fixing a credential, or demo against an already-open PR:

```bash
curl -X POST http://localhost:8000/webhooks/analyze/owner/name/42 -H "Authorization: Bearer $TOKEN"
```

This needs neither a tunnel nor a registration — only a connected GitHub token. A registered repo additionally supplies the Slack channel for the summary.

Check results:

```bash
curl http://localhost:8000/webhooks/jobs -H "Authorization: Bearer $TOKEN"
```

A `failed` job carries the reason in its `error` field; that is the first place to look.

### How it works

```
PR opened
    │
    ▼
POST /webhooks/github ──▶ verify HMAC-SHA256 over raw body
    │                     (reject before parsing if invalid)
    ▼
persist PRJob, return 202 immediately   ← GitHub times out at 10s
    │
    ▼
worker picks up job
    │
    ├─▶ extract ticket keys   (title, branch, body, commits)
    ├─▶ fetch Jira tickets
    ├─▶ search Slack threads
    └─▶ scan diff
            ├─ Semgrep + Gitleaks ──▶ CONFIRMED
            └─ LLM review ──────────▶ UNVERIFIED
    │
    ├─▶ upsert PR comment  (edits its own prior comment)
    └─▶ post Slack summary
```

### Post-merge actions

| Action | Behaviour |
|---|---|
| Jira transition | Moves the ticket to the configured status (default `Done`) |
| GitHub issues | Closes issues the PR formally *closes*; a bare `#N` mention is left alone |
| QA email | Emails the test team a model-written brief of what to verify |

**Transitions are forward-only.** A target status that would move a ticket backwards — `Done` → `In Progress` — is refused rather than applied, so a misconfigured status cannot drag a team's board backwards. Unrecognized statuses pass through, since custom workflows are common and refusing everything unknown would make the feature unusable.

### Senior dev review loop

Between "PR opened" and "PR merged" sits the part that takes the time: a senior dev asks for
changes, the author pushes, the senior dev looks again — often several times. Locus tracks
that loop, because GitHub does not: each review arrives as an isolated event, and nothing in
any payload says how long this has been going on.

| State | Meaning |
|---|---|
| `awaiting_review` | Waiting on a reviewer |
| `changes_requested` | Waiting on the author. **Not terminal** — this is where the loop spends most of its time |
| `approved` | Clear to merge |
| `merged` | Loop closed; QA takes over |

The **round number** is what makes a stalled back-and-forth visible. A PR on round five is a
conversation that is not converging, which is exactly what nobody notices without a record.

Rounds advance on one specific transition: a push that follows a changes-requested review. A
push to a PR nobody has reviewed yet is ordinary development, and counting it would turn the
round number into a commit counter. A `commented` review is recorded in the history but moves
nothing — it carries no verdict, and letting drive-by remarks bump the count would make a
converging review look stuck.

Each changes-requested review is summarized into a checklist of what was asked, shown against
the PR in the dashboard. It is advisory; the reviewer's own words are stored verbatim
alongside and are canonical. The summarizer has no tools bound and returns nothing when the
model is unavailable — an empty checklist reads as "see the review", where an invented one
would not.

#### What needs you

The dashboard opens with **Needs you**: everything outstanding across every task, grouped by
work item rather than pull request, ordered by whether the ball is with you and then by how
long it has been sitting.

| Shows | Because |
|---|---|
| Changes requested, with the reviewer's own words | The checklist is for scanning; the quote is what you act on |
| Testing failed, with the tester's words | A merged PR that failed QA is squarely yours |
| Approved but not merged | Either auto-merge is off, or the gate is holding |
| A message that failed to send | An undelivered QA notification matters more than a delivered one |

Grouping by task matters: a ticket spanning three PRs is one thing that has been running for
two weeks, not three young items. Ordering is decided by the server so the UI cannot disagree
with the API about what is most urgent.

Deliberately absent: no mark-as-done (it would duplicate GitHub state and go stale — items
disappear when the underlying state changes), no read/unread, and no new notification channel.
Slack already pings; this is the durable view.

#### Seeing what happened

Expand any PR in the review queue and switch to **Messages & loops** for the full record: both
loops' current state, who is reachable where, and every message — with its actual text.

| Shown | Includes |
|---|---|
| Searched | The Slack query, and whether it matched. A search that found nothing looks identical to one that never ran without this |
| Received | Prior discussion found, linked issue text, review bodies, tester replies — each with the verdict it produced |
| Sent | Review pings, the QA Slack post, the QA email with its subject — verbatim, as the channel saw it |

Messages that failed to send are shown and marked, since an undelivered QA notification
matters more than a delivered one.

Reviewer contacts are optional, one per line: `login, @slack, email@company.com`. A GitHub
login is neither a Slack handle nor an address, so without them the dashboard can say a review
was requested but not who was actually reached.

The log starts empty — runs from before it existed have nothing to recover, because the
messages themselves were never stored.

#### Auto-merge on approval

Optional, **off by default**. When enabled, an approving review merges the PR — and because
Locus merges through GitHub's API, GitHub fires the same `closed`+`merged` webhook a human
merge would, so the post-merge actions (Jira, issues, QA email) run through the ordinary path
with nothing special-cased.

An approval alone is not enough. This is the only thing that writes to your default branch
with no human in the loop, so the gate is checked independently of the review:

| Gate | Why |
|---|---|
| CI green | A reviewer can approve before the checks finish. Merging on pending makes approval race CI |
| No merge conflict | GitHub returning `null` mergeability means *unknown*, which holds rather than assumes |
| No confirmed security finding | Deterministic rule matches, not opinions — merging over one contradicts the confirmed/unverified split |
| No P1 review finding | P1 means "do not merge this" by definition |

Unverified findings and P2/P3 do **not** block. They are advisory, and blocking on a model's
opinion would make the feature unusable — and would hand an unverified finding authority the
confirmed/unverified split exists to deny it.

**A held merge is retried, not abandoned.** GitHub computes mergeability lazily, so the first
read right after an approval usually returns "unknown" — and it emits no event when it
finishes. A sweeper re-checks approved PRs every 60 seconds for up to 24 hours, silently, and
announces only when the merge lands. Without it, the common case is an approved PR that never
merges.

Anything held is reported to Slack with every reason at once, so a fixed CI failure does not
lead to a fresh surprise on the next round. An approved PR that quietly stays open reads as a
broken feature, so the loop always says why.

**Jira is not moved backwards when changes are requested.** That is a real backward step, but
transitions are forward-only so a misconfigured status cannot drag a team's board into an
earlier stage. The review loop notifies and records; the board follows the merge.

Configure the reviewers and the notification channel per repo, or account-wide under Default
settings. The reviewer list is who gets pinged, not who is permitted to review — GitHub does
not restrict that, and a review from anyone else is recorded like any other.

### QA feedback loop

The merge notification is posted to Slack **as a thread**. A tester replying in
that thread triggers a classifier, and Locus reopens what the merge closed:

| Verdict | Action |
|---|---|
| `broken` | Reopens the Jira ticket and linked GitHub issues, recording the tester's words |
| `works` | Marks the thread resolved |
| `unclear` | Pings the PR author in-thread. **Nothing is changed.** |
| `not_feedback` | Ignored ("thanks", "looking now") |

**Ambiguity escalates rather than guesses.** "The retry works but the timeout is
30s now?" is neither pass nor fail — a wrong reopen reverses a merge decision, a
wrong dismissal buries a real bug. The classifier returns `unclear` whenever it
is not confident, including when the model is unavailable.

Both channels feed the same classifier:

| Channel | Mechanism | Correlation |
|---|---|---|
| Slack | Events API webhook, sub-second | `thread_ts` of the notification |
| Email | Gmail polled every 3 minutes | `In-Reply-To` vs the stored `Message-ID` |

**Slack setup:** create an event subscription pointing at
`https://<your-backend>/webhooks/slack`, subscribe to `message.channels`, and set
`SLACK_SIGNING_SECRET` in `backend/.env`. The bot must be in the channel.

**Email setup:** none beyond connecting Gmail — `gmail.readonly` is already in the
OAuth scopes. Gmail is polled rather than pushed because its Pub/Sub watch expires
every 7 days and needs a renewal job regardless, at which point polling is simpler.
Replies are matched by `In-Reply-To` against a Message-ID set when sending;
subject matching would break the moment a client rewrites the subject. Quoted
text is stripped before classification, or the model reads our own "reply if
broken" boilerplate instead of the tester's answer.

Threads stop being watched after 14 days.

The reply text reaches a model whose verdict drives state changes, so the
classifier has no tools bound — it returns a verdict and nothing else.

### Design decisions worth knowing

**Confirmed and unverified findings are never merged.** Semgrep and Gitleaks are deterministic rule matches, reported as confirmed. The LLM pass catches logic-level problems no rule encodes — missing authz, injection, unsafe deserialization — and is reported as unverified. One hallucinated "confirmed vulnerability" on a colleague's PR is enough for a team to stop trusting the bot permanently.

**Semgrep scans reconstructed files, not the diff.** Semgrep parses source into an AST; handed a unified diff it silently finds nothing, because a `.diff` is not valid source in any language. The agent fetches the post-change contents of changed files and scans those, filtered to extensions Semgrep has rules for and capped at 400 KB per file.

**Comments are idempotent.** Every comment carries a hidden `<!-- locus-pr-agent -->` marker. On the next push Locus finds its own prior comment and edits it. Without this, an actively developed PR accumulates one bot comment per push.

**Detected secrets are reported by location only.** Gitleaks findings name the file and line and nothing else. Echoing the secret into a PR comment or Slack message would widen the exposure being reported.

**The security LLM has no tools bound.** Diff text and Slack messages are attacker-influenced — anyone who can open a PR controls that content. The scanner returns findings; it cannot act on what it reads.

**Jobs are persisted, not in-memory.** `BackgroundTasks` would lose queued work on restart with no retry path.

---

## API

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/auth/signup` · `/auth/login` | Authentication |
| `POST` | `/auth/connect` | Store integration credentials |
| `GET` | `/auth/integrations` | List connections |
| `DELETE` | `/auth/disconnect/{service_name}` | Remove a connection |
| `GET` | `/auth/google` · `/auth/linear` | Start OAuth |
| `POST` | `/api/chat` | Natural-language command |
| `POST` | `/api/chat/stream` | Same, with SSE task updates |
| `GET` | `/api/conversations` | Conversation list |
| `GET` | `/api/settings/llm` | Local model readiness |
| `GET` | `/api/schedule/conflicts` | Double-bookings in the next two weeks |
| `POST` | `/api/schedule/plan` | What would move to fit a new event (writes nothing) |
| `POST` | `/api/schedule/apply` | Apply a reviewed plan |
| `GET`/`POST` | `/api/schedule/deadlines` | Deadlines the scheduler protects |
| `DELETE` | `/api/schedule/deadlines/{deadline_id}` | Stop tracking one |
| `POST` | `/api/schedule/plan-deadline/{deadline_id}` | Reserve work time before a due date |
| `POST` | `/api/schedule/constraints` | Pin an event as fixed or flexible |
| `POST` | `/webhooks/github` | GitHub events (HMAC-authenticated) |
| `POST` | `/webhooks/slack` | Slack events — QA replies (HMAC-authenticated) |
| `POST` | `/webhooks/repos` | Register a repo; returns the webhook secret once |
| `GET` | `/webhooks/repos` | List registered repos |
| `DELETE` | `/webhooks/repos/{owner}/{name}` | Unregister |
| `GET` | `/webhooks/reviews` | Pull requests in the review loop; `?include_merged=true` for all |
| `GET` | `/webhooks/reviews/{owner}/{name}/{pr_number}` | One PR's full round history |
| `GET` | `/webhooks/activity/{owner}/{name}/{pr_number}` | Both loops plus every message searched, sent, and received |
| `POST` | `/webhooks/analyze/{owner}/{name}/{pr_number}` | Analyze a PR now, no webhook needed |
| `GET` | `/webhooks/jobs` | Recent analysis jobs and their errors |
| `GET` | `/webhooks/jobs/{job_id}` | One run with findings, context, and tools used |
| `GET` | `/webhooks/summary` | Per-capability pipeline readiness |

### Checking model readiness

```bash
curl http://localhost:8000/api/settings/llm
```

```json
{
  "available": true,
  "message": "Local model is ready.",
  "provider": "moe-local",
  "base_url": "http://127.0.0.1:8081/v1",
  "fast_model": "gemma-4-26b-a4b",
  "smart_model": "qwen3.6-35b-a3b"
}
```

---

## Timezone

Locus defaults to **`Asia/Kolkata`** (IST, UTC+05:30) and stores an IANA timezone per user, captured at signup from the browser. The half-hour offset breaks naive hour arithmetic, so all scheduling goes through a real timezone library rather than integer offsets.

Times are parsed in the user's zone and sent to Google with that zone attached, rather than converted to UTC — which keeps recurring events correct across a DST shift. Working hours default to 09:30–18:30, Monday to Friday.

Natural language is handled by `dateparser`: "next Tuesday 10:30", "Friday morning", "in 90 minutes". When no time can be read the parser returns nothing rather than guessing, so a typo surfaces as an error instead of an event at the wrong hour.

---

## Known limitations

These are tracked in [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) and are worth reading before deploying anywhere real.

- **Repo registration is API-only.** There is no UI for it yet; use `POST /webhooks/repos` as described above.
- **The scheduler reads only the primary calendar.** Secondary and shared calendars are ignored, so a conflict on one of those will not be seen.
- The PR agent has not been run end to end against a live GitHub webhook. Component logic is unit-tested; the Jira and Slack response-shape handling is written against the documented APIs but unverified with real credentials.
- The worker is single-instance; multi-instance needs row locking or a real queue.
- Gitleaks is optional and not bundled. Install with `go install github.com/zricethezav/gitleaks/v8@latest`; without it, committed-secret detection is skipped.
- The Gmail poller runs in-process on a single instance. Multi-instance deployment would double-process replies without a lock.

---

## Project layout

```
backend/
  app/
    routers/            auth · chat · conversations · settings · webhooks · oauth
    services/
      llm.py            local model provider
      agent.py          LangChain orchestrator
      task_planner.py   multi-task decomposition
      linking.py        ticket-key extraction
      github_pr.py      PR metadata, diffs, file contents, idempotent comments
      security_scan.py  Semgrep + Gitleaks + LLM review
      pr_agent.py       PR pipeline
      worker.py         background job runner
      <service>.py      14 integration tool modules
    models.py · schemas.py · crud.py · security.py
  migrations/           numbered, idempotent schema upgrades
  tests/                pytest suite
  pyproject.toml        uv project + ruff/pytest config
  uv.lock               pinned dependency graph
  .env.example
src/
  pages/  ui/  context/  lib/
```
