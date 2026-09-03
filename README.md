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

See [docs/WORKFLOW.md](docs/WORKFLOW.md) for the full lifecycle as diagrams:
context gathering, the senior-dev loop, the merge gate, the testing loop, and
what caches versus what is re-derived every round.

```
┌─────────────┐     ┌──────────────────────┐     ┌────────────────────┐
│   Next.js   │────▶│   FastAPI backend    │────▶│  MoE Model Manager │
│  App Router │◀────│                      │◀────│  127.0.0.1:8081/v1 │
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

#### One exception, stated plainly

"Runs entirely on local models" is false the moment autonomous mode is used, so here is the
accurate version:

> **Every model that reads your code without being asked runs locally. The one that writes code
> runs when you hand it a ticket, on a model you choose.**

The security scanner, the code reviewer, the QA classifier and the review-asks summarizer all run
on `MOE_BASE_URL` over loopback, on every push, unprompted. That is the default and it is unchanged.

If you would rather use a hosted model, choose the provider under **Settings → System → Model
backend** and paste that provider's key there. Locus then sends *those same automatic passes* —
every diff, Slack thread and ticket they read — to that provider, so the sentence above stops
being true for your install; the panel names the active provider for exactly that reason.
`anthropic` needs `uv sync --extra hosted`; OpenAI and Gemini speak the OpenAI wire format and
need nothing extra.

Everything about the backend is configuration rather than code: the **endpoint is editable for
every provider**, not only the local one, so a self-hosted vLLM or Ollama server, a LiteLLM or
OpenRouter gateway, or an Azure deployment is a URL you type rather than a fork. Model ids and
the request timeout are the same. Blank fields inherit the deployment default, and the field's
placeholder shows what that is.

Keys are stored per account, Fernet-encrypted with `ENCRYPTION_KEY` like every other credential
in the database. **No endpoint returns a key** — the API reports only whether one is set, which
is why the key field in the form is left blank on load and is sent only when you type in it: a
form that always submitted its empty box would erase the key every time you changed a model id,
invisibly, until the next analysis failed with a 401.

`backend/.env` still holds `LLM_PROVIDER`, `MOE_BASE_URL` and the `*_API_KEY` variables, and they
remain the **deployment-wide default** for accounts that have not configured their own. That is
what keeps a single-machine install working with nothing set in the UI.

The authoring agent is different. A local 35B model writing production code against a real ticket
is the weakest link in the whole mode, so **OpenCode runs on its own configured model**, which is
remote. That model — along with the driver, the invocation template, the context mode, the diff
bounds, the commit identity, the source and workspace roots and the calendar agent's dials — is
set per account under **Settings → Automation → Agent runtime**. Each field may be left blank,
and blank inherits: the deployment's environment variable first, then the built-in default, with
the placeholder showing what that currently resolves to. That is a deliberate trade — better diffs in exchange for the brief leaving the machine,
on tickets a human explicitly handed over. The mode toggle names it, every `AuthoringAttempt` row
records which model ran, and Setting the context mode to `ticket_only` drops the Slack transcript
and issue bodies for teams that cannot send internal discussion to a third party — an account
setting, falling back to `LOCUS_AUTHORING_CONTEXT`.

**Check the model provider's data-retention terms before pointing this at a private repository.**
Free tiers commonly reserve the right to train on inputs, and the inputs here are proprietary
source and internal Slack threads. This is a procurement question, not an engineering one, and it
is the one risk in this feature that cannot be walked back after the fact.

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
uv run main.py
```

### Frontend

```bash
cd frontend && bun install && bun run dev
```

Or both halves together, from the repo root:

```bash
bun install && bun run dev
```

### Checks

```bash
cd backend  && uv run pytest tests/ -q && uv run ruff check .
cd frontend && bun run build   # type-checks and lints as part of the build
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

To dismiss a false positive with `@locus ignore <finding title>`, add the **Issue comments** event as well. GitHub delivers pull request comments under that event, so without it the commands are never received. The comment body is parsed by a fixed regex, not a model, and the widest thing a command can do is hide a finding on the pull request it was posted on.

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

### Two modes: who writes the code

Every setting resolves through `app/services/pipeline/agent_settings.py`, which is the sole arbiter of what
a run does. The authoring mode resolves in three layers — **work item → repo → account defaults** —
most specific wins, and `assisted` is the fallback everywhere.

Autonomy resolves per work item deliberately. A dependency bump and a change to the credential path
are not the same risk, and as one account-wide switch the most dangerous ticket in the backlog sets
policy for every ticket — so teams leave it off and the mode is never exercised. Each card on
`/tasks` carries its own toggle.

**Assisted** — you write the code and push a branch. **Autonomous** — you click *Write it* on a
ticket and the driver opens the pull request. From the `opened` webhook onward the two are
identical: the analysis, the review round trip, the QA thread, the board card and the report
document do not know which arm ran.

#### The bound

`autonomous_max_rounds` defaults to `2`: the first attempt plus two reworks, then it comes back to
a person. Retries fire on a changes-requested review and on a QA rejection.

**Every failure spends an attempt** — a timeout, an oversized diff, a denylisted path, a failed
test gate, a driver that crashed. Without that a reliably-failing ticket retries forever and the
bound protects nothing. When the bound runs out the work item is handed back: the mode reverts to
assisted, the reason is recorded and announced once in the review channel, and the branch, the
review thread and the report are left exactly as they are.

`MAX_OPEN_AUTONOMOUS_PRS` (default 3, per repo) caps how many agent-authored pull requests may be
open at once. Reviewer attention is the scarce resource this mode spends; more pull requests than
anyone can genuinely read is the failure, not the absence of a human.

#### Where the code lives, and where the agent works

Two different questions, and conflating them is how the agent ends up editing Locus itself.

- **The source** is where your repositories already sit on disk. Configured, because re-cloning per
  attempt throws away warm dependencies and spends the timeout on network.
- **The workspace** is a `git worktree` cut from that repo. Always isolated. Your branch, your
  uncommitted changes and your stashes are never touched — a shared checkout can only have one
  branch out at a time, and an agent running `git checkout` where you are working destroys your
  afternoon and looks like a successful run.

Resolution for `owner/name`, first hit wins: the repo's `source_path`, then
`<LOCUS_CODE_ROOT>/<name>`, then `<LOCUS_CODE_ROOT>/<owner>/<name>`, then a fresh clone into the
workspace root.

Three checks before a resolved path is used, each refusing with a named error:

1. **It is a git repository.** Otherwise it is a configuration error, reported as one.
2. **Its `origin` matches the repo being worked on.** A folder name is a guess, and `acme/api` and
   `beta/api` collapse to one directory under a flat root. Pointing the agent at the wrong codebase
   produces a confident, entirely wrong pull request.
3. **It is not Locus's own tree, and does not contain it.** ⚠️ **This is the likely
   misconfiguration, not a hypothetical.** If Locus lives at `E:\Github\locus` and you set
   `LOCUS_CODE_ROOT=E:\Github`, then authoring the `locus` repo resolves to Locus's own directory —
   the one holding `backend/.env` and `ENCRYPTION_KEY`, the value that must never change or every
   stored credential becomes permanently undecryptable. Checked in both directions.

#### What the agent may not touch

Enforced on the diff **after** the run, never by trusting the prompt:

| Path | Why |
|---|---|
| `.github/workflows/**` | a model that read attacker-influenced text must not edit what CI runs |
| `**/.env*`, `**/*.pem`, `**/*.key` | secrets |
| `backend/app/security.py`, `credential_context.py` | the credential path |

A touched denylist path **aborts the attempt and records it**. It does not open a pull request with
those files reverted: a run that tried is worth surfacing, and editing the agent's diff means the
reviewer reads something the agent did not produce. `migrations/**` is deliberately not listed —
schema changes are legitimate work, and review and CI catch a bad one.

#### The test gate

With `test_command` set, it runs in the worktree after the agent finishes.

- **Passes** → open the pull request.
- **Fails, attempts remain** → consume the attempt, open nothing, retry with the failure appended.
- **Fails on the last attempt** → **open it anyway**, with the failure stated at the top of the
  body. Opening nothing after three tries leaves the human with silence, which reads as the feature
  being broken; a failing PR they can see is strictly better as long as it is labelled — and the
  merge gate requires green CI, so it cannot land.

A fresh worktree has no `node_modules` and no `.venv`, so set `prepare_command` (`uv sync`,
`npm ci`) or the gate cannot run. Its failure fails the attempt before any model is invoked, which
is the cheapest possible place to discover the environment is wrong.

#### Environment

| Variable | Default | What it does |
|---|---|---|
| `LOCUS_AUTHORING_DRIVER` | `none` | `opencode` to enable. `none` returns an error rather than an empty success. |
| `LOCUS_OPENCODE_CMD` | `opencode run --prompt-file {prompt} --cwd {workspace}` | A **template**, because OpenCode's CLI moves. Pin it against your installed version. |
| `LOCUS_OPENCODE_MODEL` | unset | Pins a model for reproducibility. Unset means OpenCode's own configured model. |
| `LOCUS_AUTHORING_CONTEXT` | `full` | `ticket_only` drops the Slack transcript and issue bodies from the brief. Recorded per attempt. |
| `LOCUS_CODE_ROOT` | unset | A folder holding many repos, e.g. `E:\Github`. |
| `LOCUS_WORKSPACE_ROOT` | `<temp>/locus-workspaces` | Where worktrees are cut. |
| `LOCUS_WORKSPACE_TTL_DAYS` | `3` | Failed runs keep their worktree this long — a failed run whose tree is gone is close to undebuggable. |
| `LOCUS_ALLOW_IN_PLACE` | off | Work directly in the source checkout. See the warning below. |
| `LOCUS_AUTHORING_TIMEOUT_SECONDS` | `1200` | Wall clock; kills the subprocess and records a timed-out attempt. |
| `LOCUS_MAX_CHANGED_FILES` | `25` | A 4,000-line agent-authored diff is not reviewable. |
| `LOCUS_MAX_CHANGED_LINES` | `600` | Same. Exceeding either consumes an attempt and is not retried smaller. |
| `LOCUS_MAX_OPEN_AUTONOMOUS_PRS` | `3` | Per repo. The rubber-stamping mitigation. |
| `LOCUS_AGENT_EMAIL` | `locus-agent@users.noreply.github.com` | How a previous attempt's commits are told apart from a human's. |

⚠️ **`LOCUS_ALLOW_IN_PLACE=1` is off by default and costs real safety.** The agent shares a working
tree with a human, `git checkout` becomes destructive, concurrent attempts on one repo become
impossible, and the self-edit check is the only thing between the agent and whatever else lives in
that directory. It exists for trees that genuinely cannot be worktree'd — submodule-heavy repos,
build systems with absolute paths baked in — not as a convenience.

#### GitHub token scoping

The authoring token needs **`contents:write`** and **`pull_requests:write`**, and explicitly
**not `workflow`**. Without the `workflow` scope GitHub itself refuses a push that touches
`.github/workflows/**`, which is a second layer under the denylist rather than a replacement for
it: the denylist reports the attempt, where GitHub would only reject the push.

---

### The calendar agent

`calendar_agent_loop` sweeps enabled users' calendars every 30 minutes and stores proposals.
Everything is off by default, per user, under `/api/schedule/agent`:

| Setting | Default | Why off |
|---|---|---|
| `enabled` | off | A feature that starts touching a calendar unasked is the worst first impression available. |
| `auto_apply` | off | A moved meeting is visible to everyone invited. |
| `auto_reply_invites` | off | Posts to real people. |
| `auto_reply_busy` | off | Same — the same category as auto-merge, and it earns the same treatment. |

With `auto_apply` off, a proposal waits at `GET /api/schedule/proposals` and
`POST /api/schedule/proposals/{id}/apply` executes **the stored plan**, not a recomputed one:
recomputing at apply time would silently run a different plan from the one that was approved.

**The busy reply.** When somebody `@`-mentions you in Slack while your calendar says you are
booked, Locus answers with a state and a time and nothing else — no title, no attendee, no
location, and it names its timezone. At most **once per thread per day**: a repeating
auto-responder gets the bot muted, and a muted bot takes your review pings and QA threads with it.
An unreadable calendar reads *free*, never busy, because a broken token and a real meeting produce
identical silence and defaulting to busy makes you unreachable.

Importance is decided deterministically first — the sender is a reviewer mid-round, or the message
names a work item the worklist reports blocked on you — and only otherwise by a classifier with no
tools bound. On an important interruption Locus offers candidate times as *options*; writing to
somebody else's calendar from an automated reply is a write nobody approved.

**Slack scopes** for the busy reply: `chat:write` to answer, `channels:history` (and
`groups:history` for private channels) to receive the message, plus the existing `message.channels`
event subscription. The member id is resolved once via `auth.test` when you save the settings — a
mention arrives in message text as `<@U04AB…>` while contacts are stored as handles, and the two
namespaces never compare equal, so mention matching silently never fires without it.

---

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
| `GET`/`PUT` | `/api/schedule/agent` | Calendar agent settings, one row per user |
| `GET` | `/api/schedule/proposals` | Reshuffles waiting on you |
| `POST` | `/api/schedule/proposals/{id}/apply` | Carry out the stored plan |
| `DELETE` | `/api/schedule/proposals/{id}` | Dismiss one (marked, not deleted) |
| `GET` | `/api/schedule/availability` | Whether you can be reached, and until when |
| `GET` | `/api/schedule/interruptions` | Who reached you while you were busy |
| `POST` | `/webhooks/github` | GitHub events (HMAC-authenticated) |
| `POST` | `/webhooks/slack` | Slack events — QA replies (HMAC-authenticated) |
| `POST` | `/webhooks/repos` | Register a repo; returns the webhook secret once |
| `GET` | `/webhooks/repos` | List registered repos |
| `GET` | `/webhooks/presets` | Named starting points for the authoring dials |
| `DELETE` | `/webhooks/repos/{owner}/{name}` | Unregister |
| `GET` | `/webhooks/reviews` | Pull requests in the review loop; `?include_merged=true` for all |
| `GET` | `/webhooks/reviews/{owner}/{name}/{pr_number}` | One PR's full round history |
| `GET` | `/webhooks/activity/{owner}/{name}/{pr_number}` | Both loops plus every message searched, sent, and received |
| `POST` | `/webhooks/analyze/{owner}/{name}/{pr_number}` | Analyze a PR now, no webhook needed |
| `GET` | `/webhooks/jobs` | Recent analysis jobs and their errors |
| `GET` | `/webhooks/jobs/{job_id}` | One run with findings, context, and tools used |
| `GET` | `/webhooks/summary` | Per-capability pipeline readiness |
| `GET` | `/tasks` | Every task assigned to you, with its pipeline position |
| `GET` | `/tasks/detail` | One task's full pipeline and every message behind it |
| `POST` | `/tasks/analyze` | Re-run the analysis for a task's pull request |
| `GET`/`PUT` | `/tasks/mode` | The authoring mode for one work item, and where it resolved from |
| `GET` | `/tasks/attempts` | Every authoring attempt, including the ones that opened nothing |
| `POST` | `/tasks/author` | Hand this work item to the authoring agent |

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

Worth reading before deploying anywhere real.

- **The scheduler reads only the primary calendar.** Secondary and shared calendars are ignored, so a conflict on one of those will not be seen.
- The PR agent has not been run end to end against a live GitHub webhook. Component logic is unit-tested; the Jira and Slack response-shape handling is written against the documented APIs but unverified with real credentials.
- Gitleaks is optional and not bundled. Install with `go install github.com/zricethezav/gitleaks/v8@latest`; without it, committed-secret detection is skipped.
- **Multi-instance deployment is guarded but not proven.** The job claim is an atomic conditional UPDATE, and all three sweeps — auto-merge, the Gmail poller and the calendar agent — take Postgres advisory locks (`app/core/locks.py`), so duplicate outward messages are prevented by construction rather than by there being one process. It has not been run multi-instance in anger.
- **Autonomous mode has not been measured on real tickets.** Whether it is any good depends entirely on how well OpenCode does with the brief, and that is the product risk; the phases around it are plumbing. Measure it before promising the mode to anyone.
- **OpenCode's CLI will move.** `LOCUS_OPENCODE_CMD` is a template for that reason. Pin the exact invocation against your installed version and record which version it was pinned against.

---

## Roadmap

**[docs/AGENTS_PLAN.md](docs/AGENTS_PLAN.md) is the single plan for this project**, and all nine
of its phases are now built. It remains the record of *why* each rule is the way it is — read it
before changing any of them, and read the *Inherited decisions* section first, which records what
was deliberately not built and why, so those choices are not silently re-made.

What it delivered: three agents and two modes.

- **Assisted** — you write the code, Locus runs the pipeline around you.
- **Autonomous** — you hand Locus a ticket and an OpenCode-driven agent opens the pull request.
  The `opened` webhook is the join: the analysis, the review round trip, the QA thread and the
  board moves are identical either way, and nothing downstream learns which arm authored the
  change. That is what makes the second mode a setting rather than a fork.
- **The calendar agent** — sweeps for conflicts and proposes reschedules, and answers on your
  behalf when somebody reaches you while you are booked.

The remaining work is not more features: it is exercising all of this against live third-party
services, which nothing here has done.

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
