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
QA replies, and review bodies are controlled by anyone who can open a PR, post in a channel,
or review. The security scanner, the code reviewer, the QA classifier, and the review-asks
summarizer return findings or a verdict and nothing else — they cannot act on what they read.
The asks summarizer degrades to an empty list when the model is unavailable: an empty
checklist reads as "see the review itself", where a fabricated one would not.

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

**Context documents accumulate; every other setting overrides.** The account-level docs are the
standards that apply everywhere — a style guide, a security policy — while a repo's own describe
that codebase. `resolve_settings` therefore concatenates the two (global first, deduped) rather
than letting the repo value win: a repo that pins its own spec should still be reviewed against
the org's standards, and overriding would silently drop them. This is the single exception to the
"repo wins" rule below, and `tests/test_agent_defaults.py` pins it.

**The written report is linked where someone is being asked to read the change.** A Google Doc
nobody links to is work nobody reads: the QA brief and the review ping are deliberately short,
and the analysis behind them is where the findings and requirement context live. `doc_url` is
threaded into the QA email, the QA Slack thread, the review request and each resubmission — but
deliberately *not* into the approval or changes-requested messages, which report a verdict the
reviewer has already reached. A review event runs no analysis of its own, so it links the last
completed run's report via `_latest_doc_url`. `tests/test_report_delivery.py` pins both halves.

**PR agent settings resolve in exactly one place.** Every setting exists both on the repo
registration and on the account-wide defaults. `app/services/agent_settings.py` is the sole
arbiter of which wins — a repo value that is set wins, blank or unset falls back — so the
worker, the API, and the UI preview cannot disagree about what a run will do. Read effective
settings through it rather than reaching into either source directly. Defaults are stored one
row per user behind `GET`/`PUT /webhooks/defaults`; a merge run must read the *saved*
registration, not form state, which `tests/test_merge_uses_registration.py` pins after a bug
where ticked-but-unsubmitted settings were silently skipped.

**Every message is recorded, not summarized.** `communication_events` stores what was searched
for, what came back, and what was actually sent, per PR, across both loops.
`app/services/comms_log.py` is the only writer. Two rules there: logging never fails the work
it describes (every helper swallows its own errors — a message that was genuinely sent must
not be reported as failed because the record could not be written), and search *queries* are
stored even when nothing matched, because a search that found nothing is otherwise
indistinguishable from one that never ran.

Bodies that get sent are built once and returned to the caller rather than reconstructed for
the log — `merge_actions._qa_email_text` and `post_qa_thread`'s third return value exist for
that reason. A reconstruction drifts from what the channel actually saw, which makes the
record worse than useless.

**Context caches by work item; findings never cache.** `context_brief.build()` renders the
accumulated context on demand rather than storing it — a file has no transactions, and three
loops already write per-PR state concurrently. The split it exists to protect: Slack
discussion, issue bodies and tickets are reused across review rounds (keyed by
`ticket_key`, so the second PR on a ticket inherits the first one's history), while the diff,
the security findings and the code review are re-derived every round. Reusing a stored
analysis across a round would resubmit round two carrying round one's findings against round
two's code — a vulnerability introduced while fixing something else would pass unreported.
`build()` takes the current run's analysis as an argument for exactly that reason; it never
reads a stored one.

**The Slack cache has no expiry; it has a watermark.** There is deliberately no freshness
window on the cached discussion — a requirement debated two days ago is still the requirement,
and a window would hide anything said inside it until the window lapsed. `comms_log.cached_search()`
returns `(searched_at, matches)`: the matches are always reused, and `searched_at` is passed to
`search_slack_threads(since=…)`, which asks Slack only for what was posted after it and merges
the result. One Tier-2 call per run, and nothing said between runs is missed. Slack's `after:`
operator is date-granular and excludes its own day, so it is set a day early and the exact
cutoff is applied per match against `ts` — a match whose `ts` will not parse is kept, because a
duplicate is recoverable in a way a silently dropped message is not. A watermark of `None`
means the work item was never searched and the run does a full search; an incremental search
from an unknown point would skip whatever fell before it.

**The activity timeline shows inherited context, marked.** `comms_log.timeline()` takes an
optional `ticket_key` and folds in the Slack discussion cached under that work item by sibling
PRs, flagged `inherited`. The analysis hands that discussion to the reviewer every round, so a
timeline restricted to rows stamped with this PR's number would omit context the run
demonstrably used — and showing it unmarked would read as discussion about this PR. Both the
cache read and the timeline dedupe by permalink: the same message is recorded under each PR on
the ticket, and repeating it reads as several people saying it.

**The task board is keyed by work item, and the key already exists.** `/tasks` answers "what is
assigned to me and how far has it got", which is the pipeline Locus actually automates — a ticket
lands on someone, and everything from there to the testing team signing off runs without them
except the coding. A ticket with no pull request yet is real work and is invisible to every
PR-shaped view, which is why the board exists. The join needs nothing new: `PRReview.ticket_keys`
and `CommunicationEvent.ticket_key` have stored keys since the review loop was built, and
`worklist._task_key` already groups on that space with a `repo#N` fallback, so an assigned Jira
ticket finds its PRs, its Slack discussion and its QA thread by a key recorded when the analysis
ran. `task_board.build()` reuses `worklist.build()` for attention rather than recomputing it —
the two must not be able to disagree about what is blocked on you — and reuses
`comms_log.ticket_timeline()` for the message log, which is deliberately wider than one PR's.

**The task stage is derived, never stored.** A stored stage would need writing from three loops
that already run concurrently, and would go stale exactly when someone is watching. It is cheap
to recompute from the review state, the QA thread and the job status. Two rules in
`task_board._build_stages` are deliberate: every stage is rendered including the unreached ones,
so the card shows what happens next and not only what happened; and `changes_requested` is
omitted entirely when it never occurred, because a greyed-out step implies a round trip that did
not happen.

**Assigned-work identity comes from the token, not from configuration.** GitHub's
`filter=assigned` and Jira's `currentUser()` both resolve against whoever the stored credential
belongs to, so there is no login or account id to configure and nothing that can drift from the
connected integration. `assigned.py` queries each source independently and each swallows its own
failure: a dead Jira must cost only the Jira half, because a board that blanks reads as "nothing
assigned", which is the one wrong answer. A source that did not answer is reported in
`unavailable` rather than rendered as an empty queue. Note the credential asymmetry that is easy
to get backwards — the Jira API token is in `api_key` while `url` and `email` are under
`credentials`.

**The board offers exactly one write.** `POST /tasks/analyze` re-runs the analysis; everything
else the pipeline does reaches other people — a Slack post, a QA email, a merge — and stays
driven by webhooks and the background loops. A dashboard refresh must never be able to notify a
team twice.

**The worklist is grouped by task and ordered by staleness.** `worklist.build()` answers
"what is waiting on me", which the per-PR views cannot. Grouped by `ticket_key` because one
ticket spans several PRs and a PR-level list shows a two-week round trip as three young items.
Ordered server-side — blocked-on-you first, then oldest, then round count — so the API and the
UI cannot disagree about urgency. Severity deliberately does not rank: this is a list of
conversations, and a task stuck on round five is the signal worth surfacing.

**The review loop accumulates state GitHub does not keep.** GitHub reports each review as an
isolated event; nothing in any payload says "this PR is on its third round". `PRReview` holds
the current state and round number, `PRReviewRound` is the append-only history, and
`app/services/review_flow.py` is the only thing that writes either. Three rules there are
deliberate:

- **Only a push that follows a changes-requested review opens a new round.** A push to a PR
  nobody has reviewed is ordinary development; counting it would turn the round number into a
  commit counter and make every PR look stalled.
- **A `commented` review is recorded but moves nothing.** It carries no verdict, and letting
  drive-by remarks bump the round count would make a converging review look stuck.
- **A review request never un-approves.** Asking for a second opinion is normal, and silently
  dropping the approval would make a merge-ready PR look blocked.

**Auto-merge is off by default and gated on more than the approval.** It is the only path
that writes to a repo's default branch with no human in the loop. An approval means "the
change is right" — not that CI passed, which the reviewer may not have checked and which may
not have finished when they clicked. `review_flow.evaluate_merge_gate` independently requires
green CI, no merge conflict, no confirmed security finding, and no `p1` review finding.
Unverified findings and `p2`/`p3` deliberately do not block: blocking on a model's opinion
would both make the feature unusable and hand an unverified finding the authority the
confirmed/unverified split exists to deny it. Every refusal is reported to Slack with the
reason — an approved PR that silently stays open reads as a broken feature.

**The merge gate must be retried, not evaluated once.** GitHub computes mergeability lazily:
the first read after any change returns `mergeable: null`, and the approval webhook fires
within a second of the click. A gate evaluated only on that event holds on unknown — correctly
— and then nothing ever re-evaluates, so the approved PR sits open forever. GitHub emits no
event when mergeability resolves, so there is nothing to subscribe to. `automerge.sweep_once`
runs on a timer for exactly this; `attempt_merge` is written to be side-effect-free when it
declines so it is safe to call repeatedly. A held retry stays silent — the reason was reported
when the approval landed, and repeating it every minute trains people to ignore the channel.

**Auto-merge does not special-case the post-merge path.** Locus merges through GitHub's API,
GitHub fires `closed` + `merged=true` exactly as it does for a human merge, and the ordinary
merge job runs. Do not add a direct call to `run_merge_actions` from the review path; it would
double-fire against the webhook.

**The review loop does not move Jira backwards.** A changes-requested review is a genuine
backward step, but `merge_actions.is_forward_transition` refuses backward transitions so a
misconfigured status cannot drag a team's board into an earlier stage. Rather than carve an
exception into that guard, the review loop notifies and records, and leaves the board alone.
The board follows the merge, not the round trip.

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
ten exist on disk. Trust the directory.

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
