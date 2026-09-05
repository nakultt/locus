# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## The plan

**`docs/AGENTS_PLAN.md` is the only plan for this project.** Anything unbuilt is specced there.
It replaced `IMPLEMENTATION_PLAN.md` and `docs/MODES_PLAN.md`, which were deleted — if either is
referenced anywhere, that reference is stale.

All nine phases are now built: the authoring dial, presets, the driver contract, the OpenCode
driver, the bound and handoff, the calendar agent, availability and interruption, the board
surface, and this documentation. The plan is now a record of *why*, not a list of what is missing.

The plan's headline caveat — that nothing here had run against live third-party services — is
**no longer true, and was worth retiring carefully.** Autonomous mode has since been run end to
end twice against real GitHub, Slack, Gmail and Google Docs: a ticket assigned, code written by
the agent, a changes-requested round it reworked itself, an auto-merge, and a QA sign-off that
closed the work item. What that exercise proved is mostly that the *warning* was right even
though the claim is now stale — eleven defects surfaced, every one of them in a path the tests
could not reach, and every one failing in a way that looked like success. They are documented as
invariants below. The parts still unproven are named under "Known gaps".

The half worth keeping is the last sentence: **measure autonomous mode on real tickets before
promising it to anyone.** The plumbing works. The *review* is the weak half — across two runs on
code that was independently verified correct, five `p1` findings were raised and all five were
false positives, while both genuine correctness bugs were found by executing the acceptance
criteria rather than by reading the diff. This is why review findings never block the merge gate
at any priority (see below): that decision is load-bearing, not a nicety.

## Branch convention

**`main` is the trunk.** Branch from it and target it with pull requests.

`feature/from-py` exists and has historically carried the work, but the two branches are now
identical. Treat `main` as authoritative.

## Layout

Two stacks, one per directory, and nothing belonging to either at the root:

```
backend/    FastAPI, dependencies managed with uv
frontend/   Next.js (App Router), dependencies managed with Bun
scripts/    Bun scripts that span both halves
```

The root `package.json` declares `frontend` as a Bun workspace, so the lockfile
(`bun.lock`) and `bunfig.toml` live at the root and `bun install` is run from there. A second
lockfile inside `frontend/` would drift from it.

## Commands

Everything at once, from the repo root — the two halves are useless apart, and starting only
one produces a UI that loads and then reports every request as a network error:

```bash
bun install     # once, from the root; installs the frontend workspace
bun run dev     # scripts/dev.ts: uv run main.py + next dev; either dying takes both down
```

Backend (from `backend/`, dependencies managed with [uv](https://docs.astral.sh/uv/)):

```bash
uv sync --extra security          # --extra security installs Semgrep
uv run main.py                    # the whole backend: HTTP surface + the four loops
uv run pytest tests/ -q
uv run pytest tests/test_linking.py -q          # single file
uv run pytest tests/test_linking.py::test_name  # single test
uv run ruff check .
```

Frontend (from `frontend/`, dependencies managed with [Bun](https://bun.sh)):

```bash
bun run dev        # bun --bun next dev --turbopack
bun run build      # next build — type-checks and lints before bundling
bun run lint
bun run typecheck  # tsc --noEmit, without a build
```

There is no frontend test runner. `bun run build` is the check — Next type-checks and lints
as part of it, so a type error or a lint error fails the build rather than reaching a page.
`bun test` is configured (rooted at `frontend/src`) for when tests are added.

`SECRET_KEY` and `ENCRYPTION_KEY` in `backend/.env` are mandatory; the app refuses to start
without them. `ENCRYPTION_KEY` must never change once set — rotating it makes every stored
credential permanently undecryptable.

## Architecture

Next.js App Router (client-rendered) → FastAPI backend → local OpenAI-compatible model
server. PostgreSQL holds
users, conversations, PR jobs, and Fernet-encrypted integration credentials. See README.md
for the full diagram, API table, and per-integration setup.

### Where things live

`backend/app/` is grouped by what a module is for. It was 60 flat modules under `services/`,
which is where you look for something you cannot name:

```
main.py                 launcher: `uv run main.py` starts the whole backend
app/main.py             the FastAPI app — uvicorn target is app.main:app
app/core/               infrastructure: database, security, dependencies, locks,
                        datetimes, credential_context, frontend_links
app/models.py           SQLAlchemy models
app/schemas.py          Pydantic schemas
app/crud.py
app/routers/            HTTP surface
app/services/
    integrations/       third-party API clients (GitHub, Jira, Slack, Google, Linear…)
    pipeline/           analysis → review round trip → QA → reporting
    authoring/          autonomous code writing (driver, worktree checks, bounds)
    scheduling/         the calendar agent
    chat/               the chat agent, its planner and the LLM client
    worker.py           the four background loops — starts everything above it
    integration_health.py   written by all of them
```

`worker.py` and `integration_health.py` stay at the top of `services/` deliberately: one
starts every group below it and the other is written by all of them, so filing either under a
group would misrepresent what depends on what.

Note `app/services/authoring/authoring.py` — the package and one of its modules share a name.
`from app.services.authoring import authoring` is the module; `from
app.services.authoring.authoring import AuthoringRequest` is a symbol inside it. Both are
valid and they mean different things.

`frontend/src/` is grouped the same way — by feature, not by kind:

```
src/app/                App Router. Route files only; each one renders a view.
                        (app)/ is a route group — it wraps the signed-in routes
                        in the auth guard and shell without appearing in any URL.
src/components/ui/      shared primitives
src/components/layout/  the application shell
src/features/<name>/    everything belonging to one feature
src/lib/                api client, datetime, utils
```

### What the move to Next changed

Three things did not survive a like-for-like port, and each fails silently if reverted:

**The theme is resolved by an inline script in `<head>`, not an effect.** It ran as a
top-level statement in `main.tsx`, before React mounted. A `useEffect` runs after hydration —
long enough to paint light and snap to dark on every load. `suppressHydrationWarning` on
`<html>` is required because that script edits the element the server rendered.

**`AuthContext` reads storage on mount, behind `isHydrated`, not in a `useState`
initializer.** Next runs the initializer on the server, where there is no storage, so the
first client render disagreed with the server's markup and the guard bounced signed-in users
to `/login`. The same flag holds the persist effect back — without it that effect fires with
the pre-hydration `null` and erases the session being restored.

**`globals.css` names its source tree with `@source`.** The Vite plugin took its root from the
project directory; the PostCSS plugin does not. Without it every utility is pruned and the app
renders unstyled.

**Inference defaults to local and loopback-bound, and every part of that is a setting.**
`app/services/chat/llm.py` resolves the provider, endpoint, model ids, timeout and key in two
steps: the config bound for the current user, then the environment. Its default is still
`MOE_BASE_URL` (`http://127.0.0.1:8081/v1`), and with a local backend the process must run on
the machine with the GPU — a remotely hosted backend cannot reach that address. The server
holds one model at a time, so chat returns `503` with a remediation hint when none is loaded
rather than an opaque connection error. Generation is slow; the default timeout is 600s because
agent loops chain several calls.

**Nothing about the model backend is hard-coded, including the local endpoint.**
`app/services/chat/llm_config.py` holds one user's resolved backend in a **ContextVar**, for the
same reason credentials live in one: `get_llm()` is called from thirteen places and none of them
takes a user, so a module-level "current settings" would let two tenants' background jobs
overwrite each other's provider — one tenant's diffs sent to another's hosted API on their key.
`get_integration_configs` binds it, because that is the one place every path reaching a model
already builds its per-user state; binding anywhere else means a caller can be missed, and a
missed caller silently runs on the deployment default, which looks exactly like the setting not
having saved. Four rules. A blank field inherits rather than overriding with nothing, so
changing the endpoint does not also pin the model ids. A stored key applies only to the provider
it was entered for — switching the selector without clearing the field must not hand an OpenAI
key to Anthropic, which returns a 401 that reads as an outage. An unrecognized provider resolves
to local, the same direction the environment already failed in: towards the backend that sends
nothing off the machine. And no endpoint returns a key, which is why
`schemas.LLMConfigUpdate.api_key` is optional rather than required — the browser cannot read the
key back, so a form that always submitted its empty field would erase it on every unrelated save.
`backend/.env` remains the deployment-wide default for accounts that set nothing.
`tests/test_llm_providers.py` pins all of it.

**The agent is LangChain 1.x `create_agent`**, which compiles to a LangGraph — `AgentExecutor`
was removed in 1.0. Task events are emitted from the graph stream, and a tool that raises
becomes a failed task rather than an aborted run, so a request touching five integrations
keeps the four that succeeded. `tests/test_agent_migration.py` pins this message contract.

**Four background loops** start in `app/main.py`'s lifespan: `worker_loop` (PR analysis jobs),
`qa_email_loop` (Gmail polling for QA replies), `merge_gate_loop` (re-evaluating held merges) and
`calendar_agent_loop` (sweeping enabled calendars for conflicts). Jobs are persisted rather than
held in `BackgroundTasks`, which would lose queued work on restart. Each sweep takes a Postgres
advisory lock (`app/core/locks.py`), because a sweep matches rows rather than claiming them and
every one of these loops ends in a message to a person.

### Invariants worth knowing before you change things

These are deliberate and each has a failure mode behind it. Preserve them.

**Credentials live in ContextVars, never module globals.** Tool objects are module
singletons, so a module-level credential dict let concurrent users overwrite each other's
tokens — one user's agent could post to another user's Slack. `app/core/credential_context.py`
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

**A suggested fix is offered where it can be applied, and never over a secret.**
A finding says where to look; the change to make is the expensive part, so
`security_scan.suggest_fixes` writes the replacement code. Three rules hold it
together. The fix is model-written even on a Semgrep finding — the scanner
confirms the *problem*, nothing confirms the *fix*, so it does not inherit that
confirmation. The applicable copy goes out as an inline review comment, because
GitHub renders ```suggestion as an Apply button only there and as an inert code
block in the issue-style summary; rendering that fence in the summary would look
applicable and not be. And Gitleaks findings are excluded outright whatever their
severity: writing a replacement line means handing the model the source holding
the live secret and rendering its answer into a comment, which is the exposure
the location-only rule exists to prevent — a committed secret is fixed by
rotating it, not by editing a line. Anchors are checked against
`get_diff_line_positions` first, since GitHub rejects an out-of-diff anchor with
a 422 and a range running past the diff would overwrite code the PR never
touched. Nits get no suggestion: the Apply button invites a click at any
priority. `tests/test_suggested_fixes.py` pins all of it.

**A job is claimed atomically, and an orphaned one is rescued.** The claim is a conditional
UPDATE moving `queued` -> `running`; only the worker whose UPDATE reported a row proceeds, so
two workers racing produce one winner rather than two analyses posting the same comment twice.
A job left `running` by a process that died used to be abandoned in place — the webhook that
queued it was answered long ago, so nothing re-queues it and the pull request is silently never
analyzed. `worker.recover_stale_jobs` requeues them on startup and on a timer, bounded by
`attempts`: recovery rescues work a crash dropped, and a job that reliably kills the worker is
failed with a reason rather than rescued into an unkillable loop. `STALE_JOB_MINUTES` must stay
well clear of the slowest legitimate run, because reclaiming a live job double-posts its comment.

**The findings diff is keyed by file and title, never line.** `finding_diff` answers "did they
fix what I flagged last round" by comparing against the previous *completed* run on the same
pull request. An edit anywhere above a finding shifts its line, so a line-keyed diff would
report every surviving finding as resolved and immediately reintroduced — worse than reporting
nothing. Resolved is worded "no longer reported" rather than "fixed": deleting the file resolves
a finding too, and the tool knows what it stopped seeing, not what anyone did about it. Nothing
renders on a first run or when nothing moved, because a "0 resolved, 0 new" line on every push
trains people to skip the section that matters.

**A dismissed finding stays dismissed, and the dismissal is disclosed.** Without suppression a
false positive is permanent — it returns on every push, and the only way to silence it is to stop
reading the comment, which silences the true positives too. `@locus ignore <title>` records one.
Three rules: the command text is untrusted, so parsing is a regex over a fixed vocabulary with no
model involved and the widest reachable effect is hiding a finding on the pull request the comment
was posted on; Locus ignores comments carrying its own markers, because the comment it posts ends
with an `@locus ignore` hint and acting on that would make the bot instruct itself; and the count
of withheld findings is printed in the comment, because a scanner that quietly stops mentioning
things is worse than one that never mentioned them — the silence reads as a clean run. An
ambiguous target matches nothing rather than guessing, since silencing the wrong finding is
invisible.

**A swallowed integration failure is recorded.** The loops swallow their own errors so one dead
integration cannot stop the others, which leaves a persistently broken one invisible — a Gmail
token that expired on Monday shows up only as QA replies no longer arriving, which reads as
nobody replying. `integration_health` stores last success, last failure and the streak per
(user, service). Recording never fails the work it describes, the same rule `comms_log` follows.
A service is called unhealthy only after `UNHEALTHY_AFTER` consecutive failures, because one
failed poll is ordinary; and a service never attempted is absent from the list rather than
reported healthy, which would be a claim nothing supports.

**Models that read attacker-influenced text have no tools bound — with exactly one named
exception.** Autonomous authoring is that exception, and nothing else may claim it. The OpenCode
driver gets a shell in a checkout, which is the largest capability in the system, and it is held by
compensating constraints rather than by having no tools: it runs only on a ticket a human
explicitly handed over, only in a `git worktree` isolated from Locus's own tree and from the
developer's checkout, only against a source path that passed the self-edit, git-repository and
origin checks, and its diff is refused after the run if it touches CI workflows, secrets or the
credential path. `authoring.should_retry` bounds how many times it may try, and every failure
spends an attempt.

**The analysis models have no tools bound.** Diff text, Slack messages,
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

**One report document per pull request, rewritten in place.** The export used to POST to
`/v1/documents` on every run, which creates a new file each time — a PR pushed to five times
ended up with five documents, each frozen where it was written, and every link already sent to
a reviewer or the testing team pointing at a stale one. The link is the entire reason the
document is worth writing, so `PRReport` stores the document id and the export deletes the
body and re-inserts rather than creating. `report_sync.refresh` is called from the review path
and the QA reply path too: those events run no analysis — the diff has not changed — but they
carry the verdict, the round trip and the tester's answer, which is most of the story. It
reuses the last completed run's analysis, since that is still the truth about the code, and
re-reads only the history around it. Three rules: the first document is created by an analysis
and never by a refresh, because a review event has no code to describe and rendering from no
analysis would replace a real document with an empty one; a refresh that fails returns the
stored URL rather than raising, since the notification it decorates is worth sending either
way; and a document someone deleted (404) is replaced rather than failing the export.
`tests/test_report_sync.py` pins it.

**The Google Doc is the whole record; the PR comment is the summary.** They are different
documents for different readers. The comment is read in a diff view by someone deciding whether
to approve, so it is short. The report is read by the senior dev and the testing team, who are
asked to trust a verdict produced by a pipeline they did not watch — reasonable only if they
can read what it actually did. `app/services/full_report.render` therefore carries the
requirement, the Slack discussion, both analysis passes, the findings diff, every review round
with the reviewer's own words, every message sent and received in both loops, and every
pipeline step including the skipped and failed ones. Three rules: searches that matched nothing
are included, because a search that found nothing and one that never ran produce identical
silence everywhere else and only one means the context is missing; a failed send is labelled
`DELIVERY FAILED`, since a message nobody received looks exactly like one nobody answered; and
nothing in the document is model-written, so it cannot be wrong the way a summary can. Output
is plain text — Docs stores text rather than parsing Markdown, so `##` would render literally.
The timeline is read at export time, which is before this run's own outward messages exist;
that is why the review request and the QA brief carry the link rather than the document
carrying them. `tests/test_full_report.py` pins it.

**Google access tokens are refreshed, never read raw.** A Google access token lives an hour;
the refresh token beside it lives until revoked. Every loop here runs indefinitely, so reading
`credentials["access_token"]` directly worked for exactly one hour after the user connected the
integration and returned 401 forever after — and that failure is indistinguishable from the
integration being broken, which is how the Docs export came to report "no document returned"
and QA emails silently stopped going out. `app/services/google_auth.valid_access_token` is the
one async refresh path; the per-tool modules keep their own synchronous copies bound to their
module singletons, and nothing outside a tool body should grow a fourth. Two rules: the
refreshed token is written back to the database, since a refresh that lives only in memory is
spent on one call and the next loop iteration starts expired again; and the refresh token is
carried forward explicitly, because Google does not return it on a refresh and dropping it
turns an hourly refresh into a one-time one. `get_integration_configs` attaches
`GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` to every Google service config — they are
environment configuration rather than per-user data, and without them there is nothing to
refresh with. A failed export raises with the status and body rather than returning None: the
silent None is what made this take a day to find. `tests/test_google_auth.py` pins it.

**A work item can close on QA sign-off instead of at merge.** "Merged" and "done" are different
claims, and the pipeline exists because a human still confirms the second. Closing at merge is
right whenever QA passes and wrong in both cases that need attention — a rejected change, and a
thread nobody answered — and a ticket closed while a bug is live drops off the board, which is
the one place anyone would look for it. With `close_on_qa_signoff` set, `run_merge_actions`
neither transitions the ticket nor closes linked issues, and `qa_feedback.handle_qa_reply` does
both on a `works` verdict. Four rules hold it together. The close only fires when the merge
actually deferred it, since re-closing an item someone deliberately reopened would undo their
decision. It runs identically for a Slack reply and a Gmail one — the channel a tester chose
must not change the outcome. The merge is left with nothing to say about the ticket rather than
moved to an intermediate status, because most boards have no such stage. And the cost of
holding an item open is that silence keeps it open forever, so `worklist` reports a thread
unanswered for `QA_SILENT_DAYS` as blocked on you — without that the change trades a ticket
that closed too early for one that never closes, which is no better for being quieter. A thread
already answered "broken" is reported as a rejection and not also as silence. Off by default:
holding work open is only safe for a team whose QA loop replies. `tests/test_qa_feedback.py`,
`tests/test_merge_actions.py` and `tests/test_worklist.py` pin it.

**The Projects card follows the pipeline, and only ever forward.** GitHub's own project
workflows have exactly one useful trigger — an item closing — so a ticket sat in `Todo`
through the branch, the review round trip and the QA thread, and then jumped to `Done`. The
half the board could never show is the half this pipeline automates.
`app/services/integrations/project_board.py` writes the card. A board's columns are not columns: they are
the options of a single-select field named `Status`, so the project, the field and its options
are all discovered from the issue at call time rather than configured — renaming a column
cannot break a stored id, because none is stored. Note `options` takes no `first:` argument
and GitHub rejects the query outright if given one; the first version shipped that way and
every card reported "no Status field" until it was found against a real board, which is why
`tests/test_project_board.py` pins the query shape as a string. The moves fire from four
places: the analysis path on a PR opening (`in_progress`), the review path on a verdict, the
merge, and the QA reply. Five rules. A card only advances, ordered by the board's own columns,
because the derived stage legitimately regresses — a push after approval revokes it — and a
card a human dragged forward must survive a refresh; the sole exception is a QA rejection,
which passes `allow_backwards` because the tester has said the change does not work and the
ticket is reopening with it. `merged` maps to the in-progress column, never a done one: the
same "merged and done are different claims" that `close_on_qa_signoff` exists for, one surface
along. A stage absent from a configured map moves nothing, which is what makes a partial map
safe, and a configured map replaces the default outright rather than merging — a team that
dropped a stage meant to drop it. The analysis move is skipped on the merge job, which shares
that code path and does its own move afterwards, since otherwise one event would move the card
to `in_progress` and then forward again. And a failure is swallowed and reported in the return
value, never raised: a completed merge must not read as failed because a board could not be
updated. On by default, unlike auto-merge — this writes a status field on a card, not to a
branch. It needs the `project` OAuth scope, which `repo` does not imply; a token without it
reports a skipped board rather than an error, because the likely cause is a user who has not
reconnected.

**What the reviewer asked for reaches the testing team.** The QA brief is built from the diff,
the ticket and the security findings — none of which contain the requirement a human stated in
plain words. A reviewer asking for "add the word orange too" is the most concrete statement of
what the change had to do, and QA is exactly who verifies it, so `review_flow.asks_for_qa`
threads the changes-requested bodies into `draft_qa_brief`. Two rules: the asks are read from
the append-only `PRReviewRound` rather than `review.pending_asks`, because `record_merged`
clears that field on its way past and does so immediately before the QA loop opens — and every
round is carried rather than only the last, since a request satisfied in round two is still
something QA should check. The fallback brief lists them verbatim: with no model to fold them
into prose, stating them plainly is the whole point. `tests/test_review_flow.py` and
`tests/test_merge_actions.py` pin it.

**The written report is linked where someone is being asked to read the change.** A Google Doc
nobody links to is work nobody reads: the QA brief and the review ping are deliberately short,
and the analysis behind them is where the findings and requirement context live. `doc_url` is
threaded into the QA email, the QA Slack thread, the review request and each resubmission — but
deliberately *not* into the approval or changes-requested messages, which report a verdict the
reviewer has already reached. A review event runs no analysis of its own, so it links the last
completed run's report via `_latest_doc_url`. `tests/test_report_delivery.py` pins both halves.

**PR agent settings resolve in exactly one place.** Every setting exists both on the repo
registration and on the account-wide defaults. `app/services/pipeline/agent_settings.py` is the sole
arbiter of which wins — a repo value that is set wins, blank or unset falls back — so the
worker, the API, and the UI preview cannot disagree about what a run will do. Read effective
settings through it rather than reaching into either source directly. Defaults are stored one
row per user behind `GET`/`PUT /webhooks/defaults`; a merge run must read the *saved*
registration, not form state, which `tests/test_merge_uses_registration.py` pins after a bug
where ticked-but-unsubmitted settings were silently skipped.

**Every message is recorded, not summarized.** `comms_log` stays the only writer for anything
keyed to a pull request. `InterruptionEvent` is a second table rather than an exception to that:
`communication_events.repo` and `.pr_number` are `NOT NULL` and an interruption has neither —
somebody pinged you in a channel, which belongs to no pull request — so reusing it would mean
inventing a sentinel repo that the next reader takes for real. `communication_events` stores what was searched
for, what came back, and what was actually sent, per PR, across both loops.
`app/services/pipeline/comms_log.py` is the only writer. Two rules there: logging never fails the work
it describes (every helper swallows its own errors — a message that was genuinely sent must
not be reported as failed because the record could not be written), and search *queries* are
stored even when nothing matched, because a search that found nothing is otherwise
indistinguishable from one that never ran.

Bodies that get sent are built once and returned to the caller rather than reconstructed for
the log — `merge_actions._qa_email_text` and `post_qa_thread`'s third return value exist for
that reason. A reconstruction drifts from what the channel actually saw, which makes the
record worse than useless.

**The report document belongs to the work item, not the pull request.** `PRReport` is keyed by
`ticket_key` when the work has one, so a task spanning the feature, the fix after QA rejected
it, and the follow-up keeps one document rather than three. This is the same argument that
made it a document per PR rather than per push, one level up. `report_sync.find_report` is the
only lookup: it resolves by ticket first and falls back to `(repo, pr_number)`, because rows
written before this existed carry no ticket and finding them only by ticket would hand each
one a second document — leaving the link already sent pointing at the older, frozen one. With
`adopt=True` that fallback claims the row for the ticket, so the first PR's document becomes
the task's rather than being orphaned. Read-only callers leave `adopt` off so a lookup never
mutates.

**The document starts at the ticket, and carries the ticket's description.** Belonging to the
work item means it can exist before any pull request does, which is the whole window in which
someone is deciding what to build and the window in which a written requirement is most useful
— `pr_reports.repo` and `pr_number` are therefore nullable, recording where a document
*started* rather than what it is about. `report_sync.ensure_for_ticket` creates it and is
idempotent, so opening a task twice returns one link. Four rules: it is called from
`GET /tasks/detail` and never from the board listing, because a board refresh would create a
document for every assigned item at once — the same shape of mistake as a refresh notifying a
team twice; the body is `_ticket_brief`, deliberately not `full_report.render`, since that
describes an analysis that has not happened and would render as mostly empty headings; a ticket
with no description says so in words rather than leaving the section blank, because an empty
section reads as a failed fetch where the absence is a fact about the ticket; and a failure to
create returns None so the task renders without a link rather than the board failing.
`assigned.jira_text` flattens Jira's ADF description — Jira Cloud returns nested nodes, not a
string. `tests/test_report_sync.py` pins it.

**The document carries every attempt, because it is rewritten in place.** One file per work item
plus a render scoped to one pull request is a silent delete: when the retry after a QA rejection
exported, it overwrote the shared document with only its own history, taking the first attempt's
review rounds, its QA brief and the tester's rejection with it — and the link everyone already
had kept working, now pointing at a document that had forgotten why the work came back. So the
report reads the work item, not the pull request. `comms_log.work_item_history` returns every
event under the ticket across every PR, and is deliberately wider than `timeline`, which inherits
only Slack discussion because that is what the analysis genuinely reused and marking anything else
as inherited would imply it was found on this PR. `full_report.render` takes `prior_reviews` from
`work_item.sibling_reviews` and renders an "earlier attempts" section *before* the current
history, since "this merged once and came back" is what makes the current round make sense.
Inherited rows name the pull request they came from rather than being marked generically — on a
retry that is the point of showing them.

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

**An issue's links are read from the issue, not only from the pull request.**
`github_pr.get_linked_issues` reads `closingIssuesReferences` during an analysis, which
sees only what a PR's *body* declares it closes. That misses the two cases a task board is
asked about: a pull request attached through GitHub's Development panel, which writes a real
edge but no closing keyword, and a branch created from that panel before any pull request
exists — the state a ticket sits in for as long as someone is writing the code, and which
used to render as `assigned`, i.e. as though nobody had started. `issue_links.fetch` queries
`closedByPullRequestsReferences` and `linkedBranches` from the issue side, one aliased
GraphQL request for the whole board. The two fields are complementary: `linkedBranches`
returns only affirmatively linked branches and never PRs, so neither subsumes the other.
Repository names are escaped into the query rather than passed as variables, since one
variable set per alias reads worse than an escaped literal — but escaping is then mandatory.
An older GitHub rejecting `closedByPullRequestsReferences` retries without it rather than
costing the board, and a total failure returns empty: the links are context, and a board that
blanks because one call failed is the one wrong answer. `tests/test_issue_links.py` pins it.

**A linked branch ranks below every pull-request stage.** The branch stays linked after its PR
opens, so a rule that let it win would walk a reviewed card backwards to `branch_created` on
every refresh. `branch_created` is also conditional like `changes_requested`: it is observable
only for GitHub issues, and rendering it greyed-out on every Jira ticket would show most tasks
permanently skipping a step that was never available to them.

**A discovered link is recorded, and only ever added.** `task_board._persist_links` writes the
issue key onto the review rows GitHub names, so the pull request becomes findable as a sibling
of the work item and the board stops depending on the links call having succeeded. This is
recording what GitHub's graph reports, not inferring a work item — the distinction `work_item`
draws. It appends rather than replaces, because a PR routinely belongs to several work items
and overwriting would drop the Jira key an analysis read off the branch.

**The task stage is derived, never stored.** A stored stage would need writing from three loops
that already run concurrently, and would go stale exactly when someone is watching. It is cheap
to recompute from the review state, the QA thread and the job status. Two rules in
`task_board._build_stages` are deliberate: every stage is rendered including the unreached ones,
so the card shows what happens next and not only what happened; and `changes_requested` is
omitted entirely when it never occurred, because a greyed-out step implies a round trip that did
not happen.

**Work still in flight decides the stage; earlier attempts are history.** A task is a sequence of
attempts, not a set of them — QA rejects a merged change, the ticket reopens, and the fix arrives
as a fresh pull request that starts the review loop again. `_derive_stage` therefore reads the
furthest state among the *unmerged* pull requests, and only consults the QA thread and the merge
when nothing is in flight. Reading the task as "the furthest any of its PRs ever got" reported
that reopened ticket as `merged`, and — because a rejected QA thread stays unresolved by design,
and was consulted before the reviews — as `testing` for the whole of the second review round.
Both say the work is further along than it is, on exactly the round trip the pipeline exists to
automate. `had_changes` is still computed across every attempt, so a round trip on the first pull
request keeps `changes_requested` in the stepper. `tests/test_task_board.py` pins the sequence.

**Assigned-work identity comes from the token, not from configuration.** GitHub's
`filter=assigned` and Jira's `currentUser()` both resolve against whoever the stored credential
belongs to, so there is no login or account id to configure and nothing that can drift from the
connected integration. `assigned.py` queries each source independently and each swallows its own
failure: a dead Jira must cost only the Jira half, because a board that blanks reads as "nothing
assigned", which is the one wrong answer. A source that did not answer is reported in
`unavailable` rather than rendered as an empty queue. Note the credential asymmetry that is easy
to get backwards — the Jira API token is in `api_key` while `url` and `email` are under
`credentials`.

**The board offers exactly two writes, and the second is deliberate.** `POST /tasks/analyze`
re-runs the analysis and `POST /tasks/author` hands one work item to the authoring driver. The rule
this amends said there was exactly one, and it exists so a dashboard refresh cannot notify a team
twice — one deliberate click that opens one pull request satisfies that reasoning rather than
breaking it. Authoring is emphatically *not* fired on assignment: that has the same shape as the
mistake `report_sync.ensure_for_ticket` avoids by never running from the board listing, with a far
worse blast radius, since a morning's tickets would open a dozen pull requests together. Everything
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
`app/services/pipeline/review_flow.py` is the only thing that writes either. Three rules there are
deliberate:

- **A push to a pull request someone has already looked at goes back to the reviewer.** All
  three reviewed states send it back, and they differ only in the round count and the wording.
  The approval case is a safety property, not a nicety: an approval describes a diff, and when
  the diff changes the approval no longer covers it. Leaving the state `approved` meant
  `automerge.sweep_once` — which re-evaluates the gate every minute — merged commits no human
  had read, and the result was indistinguishable from a properly approved merge. A push after
  approval therefore revokes it, and the notification says so rather than reading as "round 3
  is ready". A push arriving *while* the reviewer is still deciding is reported but does not
  increment the round: they have not finished round one.
- **A push to a PR nobody has ever reviewed still counts for nothing.** That is ordinary
  development; counting it would turn the round number into a commit counter and make every PR
  look stalled. The analysis re-runs regardless — the review loop simply does not hear about it.
- **A `commented` review is recorded but moves nothing.** It carries no verdict, and letting
  drive-by remarks bump the round count would make a converging review look stuck.
- **A review request never un-approves.** Asking for a second opinion is normal, and silently
  dropping the approval would make a merge-ready PR look blocked.

**A reopened ticket's next pull request inherits its lineage.** The pipeline records
`ticket_keys` on the review row once an analysis completes, which covers every push after the
first. It does not cover the *first* run on a new pull request — which is exactly the reopened
-ticket case: a change merges, QA rejects it, the ticket goes back to In Progress, and the fix
arrives on a fresh branch as a new PR. That PR has no review row and no recorded keys, so it
started cold, missing the one thing it most needed: why the last attempt was rejected.
`work_item.resolve_key` falls back to reading the branch, title and body, and the siblings are
then a lookup. Two rules: a work item is never guessed — no ticket in the branch or title means
the run proceeds as genuinely new work, because attaching a guessed key would put one team's
rejection history in front of another team's PR; and only an earlier *merged* pull request
makes this a retry, since two PRs open in parallel on one ticket is ordinary. The review row is
now created at analysis time rather than waiting for a review event, because a PR analyzed but
never reviewed used to store no keys at all and so could never be found as a sibling.

**Auto-merge is off by default and gated on more than the approval.** It is the only path
that writes to a repo's default branch with no human in the loop. An approval means "the
change is right" — not that CI passed, which the reviewer may not have checked and which may
not have finished when they clicked. `review_flow.evaluate_merge_gate` independently requires
green CI, no merge conflict, and no confirmed security finding. Review findings do not block at
any priority, `p1` included: every priority is a model's judgement about the change, and the
reviewer approving it has already read the finding — findings render in the PR comment and in
the Slack notification whatever the gate decides. Gating on one as well made the approval
advisory rather than decisive, since a `p1` the reviewer had seen and accepted still could not
merge without being dismissed by hand first. Unverified security findings likewise do not
block, which is what keeps the confirmed/unverified split meaningful. Every refusal is reported
to Slack with the reason — an approved PR that silently stays open reads as a broken feature.

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

**Timestamps are stored as UTC instants and displayed in IST.** The two halves are
separate and both matter. Postgres sessions are pinned to UTC in `app/core/database.py` rather
than inheriting the server's zone — a session that inherits it serialized the same row as
`+05:30` on a developer's machine and `+00:00` in production, both naming the same instant,
with the difference invisible until something compared or cached them. Display is applied
once, in `frontend/src/lib/datetime.ts`, which passes an explicit `timeZone` so every viewer reads the
same wall clock regardless of where their browser thinks it is. `toLocaleString(undefined, …)`
is what that replaced: these are shared events people discuss with each other, and "the build
broke at 3" has to mean one moment. `parseInstant` reads a timestamp with no offset as UTC,
because SQLite stores UTC without labelling it and resolving against the browser's zone would
reintroduce exactly the drift being removed. Anything the backend formats into text for a
human names its zone — `google_meet` used to stamp "UTC" onto server-local times, which is
the same class of bug `datetimes.py` was written to fix.

**Scheduling goes through a real timezone library, never integer offsets.** The default zone
is `Asia/Kolkata` (UTC+05:30) and the half-hour offset breaks naive hour arithmetic. Times are
sent to Google with the zone attached rather than converted to UTC, which keeps recurring
events correct across a DST shift. Natural language is parsed by `dateparser`, which returns
nothing rather than guessing when no time can be read.

**The code-writing agent never runs where Locus's credentials live.** The one rule everything
else in autonomous mode is arranged around. Locus's working directory holds `.env` with
`SECRET_KEY` and `ENCRYPTION_KEY` — the value that must never change or every stored credential
becomes permanently undecryptable. `workspace.check_not_locus` compares a resolved source path
against Locus's own root **in both directions** and refuses with a named error. With a code root
this stops being hypothetical: Locus at `E:\Github\locus` plus `LOCUS_CODE_ROOT=E:\Github`
resolves the `locus` repo to exactly that directory, and that layout is the normal one, which makes
this the most likely misconfiguration the feature has.

**The agent's runtime is a setting, and it resolves in three layers.**
`app/services/authoring/agent_runtime.py` holds the driver, the model, the invocation template,
the context mode, the diff bounds, the commit identity, the source and workspace roots and the
calendar agent's two dials, resolving each as **account setting, then environment variable, then
the caller's own module constant**. Those were environment variables, which made every one of
them a single operator's answer for every tenant — including `LOCUS_AUTHORING_CONTEXT`, which
decides whether a team's internal Slack discussion may be sent to a third party. That is a
tenant's policy, not the operator's. Five rules. The resolved config lives in a **ContextVar**,
the third use of that pattern after `credential_context` and `llm_config`, and for the same
reason: `AGENT_EMAIL` alone is read from six places across two modules and none of them takes a
user, so a module-level "current settings" would let two accounts' runs overwrite each other's
source root and point one agent at the other's code. The last layer is the *caller's* constant,
passed in — `agent_runtime.max_changed_files(MAX_CHANGED_FILES)` — because that constant is where
the environment variable is read at import, and a second copy of the number here would be one
setting with two defaults that drift. Both the bound value and the environment value go through
the same normalizer, so an unrecognized driver name cannot reach the check that exists to stop
it, and an unrecognized one resolves to the do-nothing driver rather than to `opencode`: guessing
would run a shell in a checkout on the strength of a typo. `allow_in_place` is tri-state (NULL
inherits, 0 and 1 are choices), because stored as a boolean an account could never turn off a
deployment default that was on. And a malformed number is *absent*, not zero — a timeout of zero
kills every attempt instantly and a file cap of zero refuses every diff, so it must fall through
rather than be coerced into the most destructive value in the range.
`tests/test_agent_runtime.py` pins it.

**Letting a user set the source root does not weaken the workspace checks.** `check_not_locus`,
`check_is_git_repo` and `check_origin_matches` run on the resolved path whatever produced it, and
the denylist is enforced on the diff after the run. They never consulted where the value came
from, which is exactly what makes it safe for it to come from a form: an account pointing its
root at the tree holding `ENCRYPTION_KEY` gets the same named configuration error that setting
`LOCUS_CODE_ROOT` there has always produced.

**The calendar loop ticks on its own clock; the sweep interval is per user.** There is one loop,
so a per-account interval cannot be a per-account sleep. `calendar_agent` ticks every
`TICK_MINUTES` and sweeps a user only when *their* interval has elapsed, which is what lets one
account ask for ten minutes without the deployment's thirty, and stops another's aggressive
setting from becoming a Google rate limit for everybody. The last-swept time is in memory rather
than a column: it is a rate limiter, and the correct behaviour after a restart is to sweep, not
to remember that we nearly did. It is marked *after* the work, so a sweep that raised does not
rate-limit the user out of their next attempt.

**The source location and the workspace are different settings.** `LOCUS_CODE_ROOT` and
`repo_webhooks.source_path` say where your repos already sit — cloned, dependencies installed,
caches warm — because re-cloning per attempt spends the timeout on network. The agent still works
in a `git worktree` cut from that repo, so a human's branch, uncommitted changes and stashes are
never touched. This is not a convenience: a shared checkout can only have one branch out at a time,
and an agent running `git checkout` in the directory somebody is working in destroys their
afternoon and looks like a successful run. `LOCUS_ALLOW_IN_PLACE` — and the account setting that overrides it —
exists for trees that genuinely cannot be worktree'd, is off by default, and the README states
what it costs.

**A resolved path whose `origin` does not match the repo is refused.** `<root>/<name>` is a guess
based on a folder name, and `acme/api` and `beta/api` collapse to one directory under a flat root.
Pointing the agent at the wrong codebase produces a confident, entirely wrong pull request — worse
than refusing, because it looks like success. A path that is not a git repository is likewise
reported as a configuration error rather than as a failed authoring attempt: the two want
completely different responses.

**A forbidden path aborts the attempt rather than being reverted.** The denylist is enforced on the
diff, after the run, never by trusting the prompt. A run that tried to edit `.github/workflows/**`,
a secret or the credential path is a signal worth surfacing, and silently editing the agent's diff
means the reviewer reads something the agent did not produce. `migrations/**` is deliberately not
on the list — schema changes are legitimate work, and the review and CI gates catch a bad one.

**A review is requested once, on the pull request the agent actually created.** Autonomous mode
opened its pull requests with nobody requested, so the work never entered GitHub's own review
queue -- the place a reviewer looks -- and the first anybody heard of it was a Slack ping.
`autonomous_pr_reviewers` is an account setting resolved through `agent_runtime`
(`LOCUS_AUTHORING_PR_REVIEWERS`, then empty), deliberately **not** `settings.reviewers`: that list
names who is expected to review a repo and is used to address the review loop's notifications, and
turning it into a GitHub request would start notifying people who only agreed to be mentioned in a
channel. Three rules. The request fires only on the 201, never on the already-open path -- a rework
pushes to the branch the reviewer has already read, and re-requesting there re-notifies them every
round, which is what gets a bot muted. The pull request's author is dropped first, because GitHub
rejects a list naming them with a 422 covering the *whole* list, so the agent's own account
appearing in a team's reviewer list would cost everyone else their request too. And a failure is
logged and swallowed: the pull request is open, which is what the attempt was spent on, and failing
an authoring run over a notification would hand the work item back.
`tests/test_pr_reviewers.py` pins it.

**An empty diff opens no pull request.** An empty PR puts a reviewer's name on a request to read a
diff that does not exist.

**Every failure consumes an attempt.** A timeout, an oversized diff, a denylisted path, a failed
test gate and a driver that raised all record an `AuthoringAttempt` row and spend the bound.
Without that a reliably-failing ticket retries forever and the bound protects nothing — and
`PRReview.round_number`, the signal that makes a stalled review visible, stops meaning anything.

**A human commit on the branch ends autonomous mode for that work item** — at authoring time as
well as at rework time. An agent overwriting a person's work is the worst thing it can do quietly.
A branch carrying a *previous attempt's* commits is continued, so a rework builds on what the
reviewer already read; commits by anyone else hand the item back before the model is invoked.

**A handoff is written before it is announced.** The reverse — announcing a handoff that did not
persist — re-triggers the driver on the next event, so the team reads "it is yours now" while the
agent keeps working. A failed announcement leaves the work correctly stopped; a failed write leaves
it running with everybody told otherwise. The handoff announces once, because a repeat is what gets
a bot muted, and a muted bot takes the review pings and QA threads with it.

**The analysis models run locally; the authoring model does not.** Every model that reads your code
*automatically* — the security scanner, the code reviewer, the QA classifier, the asks summarizer —
runs on the configured endpoint, which defaults to loopback, on every push, without being asked.
That default is worth keeping, and pointing it at a hosted provider is a deliberate act the
settings panel states plainly rather than a performance dial. Authoring is the deliberate exception: OpenCode runs on its own configured
model, which is remote, so the brief leaves the machine on tickets a human explicitly handed over.
The mode toggle says so before the first attempt, every `AuthoringAttempt` records which model ran,
and `ticket_only` — an account setting, falling back to
`LOCUS_AUTHORING_CONTEXT` — drops the Slack transcript for teams that cannot send internal
discussion to a third party. "Runs entirely on local models" is false the moment
autonomous mode is used; the accurate claim is narrower and still strong.

**A busy reply carries a state and a time and nothing else.** `Availability` has three fields —
state, until, next_free — and **the type is the enforcement**: the reply is posted into a channel
other people read, and "in a 1:1 with Priya re: restructure" must not be able to reach it. There is
no field to leak it through. It names its timezone, because `google_meet` stamping "UTC" onto
server-local times is the bug that rule was written from, and it fires at most once per thread per
day: a repeating auto-responder gets the bot muted.

**An unreadable calendar reads free, never busy.** A broken token and a real meeting produce
identical silence, and defaulting to busy fails in the direction that makes the user unreachable —
the responder tells everybody they are in a meeting they are not in, and the reply they were
waiting for never comes. The breakage surfaces through `integration_health`.

**An interruption's importance is decided deterministically first.** The sender is a reviewer
mid-round, or the message names a work item `worklist.build()` reports blocked on you. Only when
neither fact applies is a classifier consulted, with no tools bound, and `unclear` resolves to
routine — the reply goes out either way, so the choice is between an important message getting a
plain reply and a focus block being interrupted over nothing, and the second is worse.
`importance_source` records which test decided, and the UI renders the model-made claim as the
weaker one.

**The calendar agent never holds a pipeline message.** Delaying a review request until a focus
block ends manufactures the exact silence that makes an approved pull request look like a broken
feature. The agent runs alongside the pipeline, never inside it.

**The scheduler's solver is plain Python, not a model.** A model asked to rearrange a calendar
produces plausible-looking schedules with overlaps and missed deadlines. Events are classified
by movability, conflicts resolve least-disruptive-first, and anything with external attendees
is reported as blocked rather than moved.

### Invariants the first live runs added

Everything below was found by running autonomous mode end to end against real services. None of
it was caught by the suite, and each failed in a way that looked like success — which is the
common thread and the reason they are grouped.

**A pass that failed is never rendered as a pass that found nothing.** These are different
claims and only one is evidence about the code. The comment printed "No issues detected in the
changed code." as its headline while the collapsed notes below recorded that every pass had
failed, so two dead scanners and a misdirected model backend sat unnoticed through a whole
pipeline run. `_incomplete_notice` says so instead, and says it whether or not the section found
anything: findings present with a scanner dead is the more dangerous case, because a partial
list reads as a complete one and nothing else in the output contradicts it. Only the passes that
actually failed are marked — a Slack outage says nothing about whether the code was scanned.

**The deterministic scanners must not depend on which event loop is running.** `reload=True`
makes uvicorn manage subprocesses, which selects a `SelectorEventLoop`, which on Windows cannot
spawn one — so `create_subprocess_exec` raised `NotImplementedError`, whose message is the empty
string, and the comment read `semgrep failed: `. Semgrep and Gitleaks therefore never ran in
development, silently, killing the confirmed half of the scan. They run through
`asyncio.to_thread(subprocess.run, …)`, which behaves the same on every platform and any loop.
Never interpolate a bare exception into a message either: `_describe` falls back to the class
name, because an empty one names neither the cause nor anything to search for.

**Git is never allowed to wait for a human.** An agent running unattended cannot answer a
credential prompt: on Windows the credential manager opens an account picker and the push blocks
until the attempt times out, spending it on a dialog nobody saw; on a server there is no helper
at all and the prompt fails in a way that reads like a rejected push. `run_git` disables
prompting outright — `GIT_TERMINAL_PROMPT=0`, no askpass, `GCM_INTERACTIVE=never`, and an empty
`credential.helper` — in one place rather than at each call site, because the failure mode of
missing one is a run that hangs rather than one that fails. That makes authentication necessarily
explicit, which is what `authenticated_remote` is for: it takes the host from the configured
remote rather than assuming github.com, so Enterprise keeps working, and returns `origin`
unchanged for ssh or local remotes, which carry their own credentials or need none. The push URL
carries the token and git echoes the remote it could not reach, so both paths are redacted —
unredacted this wrote the token into `AuthoringAttempt.error`, which the UI renders.

**A rework continues the branch the reviewer already read.** `existing_branch` was passed as
None for both triggers, directly beneath a comment saying otherwise, so the branch name picked up
the attempt number and every rework opened a *second* pull request. The review sat on one and the
fix on the other, `round_number` stopped tracking the round trip, and the abandoned PR pinned the
board. A QA rejection still opens a new pull request — that half of the comment was correct, and
is what `work_item.resolve_key` and `sibling_reviews` exist for. Strip the ticket key before
passing a stored `pr_title` back to the driver, which re-adds it: otherwise every attempt
prefixes it again.

**Both triggers reach the driver the same way, including the board's button.** The fix above
landed on the webhook path only, so `POST /tasks/author` kept passing the *issue's* linked branch
— which an agent-created branch is not, since `linkedBranches` returns only affirmatively linked
ones — and a click on a work item in `changes_requested` reproduced the whole failure it had just
removed: a second pull request, the review stranded on the first. `_pr_to_continue` picks the open
pull request (`review_state` neither `merged` nor `closed`, the same reading `_derive_stage`
uses), `authoring_flow.head_branch` and `bare_title` are shared with the webhook path rather than
reimplemented, and the trigger recorded is `changes_requested` when that is what the run is
answering — a manual click on a rejected pull request is a rework whoever pressed it. A branch
GitHub could not be read for falls back to a fresh one *and* falls back on the trigger with it: a
run that did not continue the branch is not responding to the review, and the pull request body
says what the run is. `tests/test_authoring_contract.py` pins it.

**The throughput cap gates opening a pull request, not writing one.** The cap exists to bound
*reviewer attention*, and a rework spends none — the reviewer is already reading that pull
request. Refusing there is the one refusal that makes the mode worse than useless: changes were
asked for and the agent is then forbidden from delivering them. `should_retry` takes `continuing`
and the board endpoint consults the cap only when no branch is being continued. Two things made
this urgent rather than theoretical. The usual way an account *reaches* the cap is duplicates
opened by the board button before it learned to rework, so the cap was blocking the fix for its
own cause. And `open_autonomous_prs` subtracted only `merged`, never `closed` — that state
arrived with "in flight means open, not merely un-merged" and this counter was not part of the
change — so closing the duplicates by hand did not release it either. Both are pinned, in
`tests/test_authoring_bound.py` and `tests/test_authoring_contract.py`.

**In flight means open, not merely un-merged.** GitHub sends the same `closed` action for a merge
and an abandonment and distinguishes them only by `merged`; the merge half was handled and the
other half discarded, so nothing ever left the review loop except by merging. A superseded pull
request sitting in `changes_requested` therefore pinned its task's stage for good — the board
showed "Changes requested, 2/9" for work that had merged and been signed off. `ReviewState.closed`
exists for this, `review_flow.record_closed` writes it (never walking back a merge), and both
`task_board._derive_stage` and `worklist.build` treat it as finished. Only an actual merge reports
as merged: every pull request having been closed unmerged means the work was abandoned, not
landed.

**One definition of which work item a pull request belongs to.** `pr_agent.work_item_keys` is it:
a tracker key when there is one, otherwise the GitHub issue the pull request closes, qualified by
its repository. There were two of these — the comms log had the issue fallback and the Google Docs
export did not — so on a repo with no tracker the export saw no work item, skipped the
ticket-keyed lookup in `report_sync.find_report`, and created a fresh document per pull request.
The document the board links, created from the ticket before any PR existed, was then never
written to again and still read "No pull request has been opened for this work yet" long after
the work had merged.

**`suggested_fix` is a `SuggestedFix`, not a string.** Handing the object to a helper that calls
`.strip()` raised on every render of a review finding that carried a fix — and because
`report_sync.refresh` swallows its own failure and returns the stored URL, the document silently
stopped being updated from the review and QA paths while every link to it kept resolving. That
swallowing is correct and stays; it is why a failure here has to be impossible rather than
tolerated.

**The channel a tester replies through must not change the record.** The Slack QA path rewrote
the report once the tester answered; the email path did everything else and never refreshed it,
so the report ended at the merge and never said whether the change worked — for the *ordinary*
case, since the brief reaches testers by email. `close_on_qa_signoff` is already careful to behave
identically across both channels; the document is part of that outcome and has to be too.

**Integration health is recorded for every service, not just Gmail.** Only the Gmail poller ever
wrote a row, so after a run making many successful GitHub, Slack and Docs calls the table held
one — and "absent" meant both "never attempted" and "attempted constantly, never instrumented",
which is exactly the ambiguity the feature exists to remove. `integration_health.record_stages`
derives it from the pipeline stage list, the one place every integration already reports its own
outcome, so a new stage is instrumented by adding a line to `STAGE_SERVICES`. A `skipped` stage
records nothing: absence has to keep meaning "never attempted".

**`backend/.env` is not authoritative on its own.** Bun loads the repo-root `.env` and passes it
to every child process, and `load_dotenv()` does not override a variable already in the
environment. The root file is a leftover from the pre-Next stack and still carried
`LLM_PROVIDER=gemini` beside a stale `GOOGLE_API_KEY`, so the backend resolved its model backend
to Google and sent every diff, Slack thread and ticket body it analysed to a third party — the
exact thing "the analysis models run locally" exists to prevent. Nothing leaked only because the
key was dead and every call 400'd. `scripts/dev.ts` strips the file's own keys from the child
environment rather than denylisting names, because a denylist needs updating whenever somebody
adds a variable and forgetting is silent.

## Database schema changes

New installs need no migrations — `Base.metadata.create_all()` at startup creates the current
schema. `backend/migrations/` exists to move *existing* databases forward. Scripts are numbered
and idempotent, so running the whole set is safe:

```bash
for m in migrations/0*.py; do uv run python "$m"; done
```

Note that `migrations/README.md`'s table is stale — it lists two scripts under old names, and
many more exist on disk. Trust the directory, not either document's count.

## Conventions

Ruff lints with `E,F,I,UP,B` at line-length 100. The integration service modules carry
per-file ignores for bare excepts (`E722`) — a blanket "never let a third-party SDK crash the
agent" guard that predates the config. Don't add new bare excepts in other modules to match;
the existing ones are grandfathered, not a pattern to follow.

Frontend UI follows shadcn conventions over Radix primitives with Tailwind v4. `components.json`
is gone with the Vite build — the shadcn CLI configured for a Vite project would write to paths
that no longer exist, so primitives under `src/components/ui/` are maintained by hand.

Every component is a client component. There is no server-side data fetching: the session is a
JWT in browser storage and the API is a separate origin, so a page that tried to render on the
server would have neither a token nor a reachable backend.

CORS allows any localhost port by regex, because Next picks the next free port when 3000
is taken and a fixed list breaks silently when that happens. Production origins stay
explicit.

`.gitattributes` declares `*.svg text`, so SVGs must be committed with LF. A CRLF-stored blob
gets rewritten on every checkout and shows as modified in a fresh clone.

## Known gaps

- The scheduler reads only the primary calendar; conflicts on secondary or shared calendars
  are invisible to it.
- Tests do not cover live calls to GitHub, Jira, or Slack. Response-shape handling for those
  is written against the documented APIs. Two full end-to-end runs have since exercised GitHub,
  Slack, Gmail and Google Docs for real, but *only* on the autonomous-mode path and only against
  one account — that is evidence, not coverage, and it is not repeatable in CI.
- **The review pass is the weakest half and should not be trusted unsupervised.** Across two
  live runs on code independently verified correct, all five `p1` findings were false positives,
  while both real correctness bugs were found by executing the acceptance criteria rather than
  by reading the diff. On the second run the model even identified the offending pattern and
  filed it as a `p3` quality nit, missing that it disabled a safety check. Findings deliberately
  do not block the merge gate at any priority, which is what keeps this survivable.
- Jira and Linear have not been exercised live. Both end-to-end runs used GitHub issues as the
  work item, so `assigned.py`'s Jira half and every tracker transition remain unproven.
- The QA sign-off has been proven over Gmail and over Slack, but Slack only with a human typing
  the reply: Locus correctly ignores messages carrying a `bot_id`, so the bot token cannot
  simulate a tester, and a read-only user token cannot post. There is no way to drive that half
  unattended, by design.
- Multi-instance deployment is guarded but not proven. The job claim is an atomic conditional
  UPDATE, and the two sweeps take Postgres advisory locks (`app/core/locks.py`), so
  duplicate outward messages are prevented by construction rather than by there being one
  process. It has not been run multi-instance in anger.
- Gitleaks is optional and not bundled, so committed-secret detection is skipped when it is
  absent.

**README.md's "Known limitations" is stale on one point:** it says repo registration is
API-only with no UI. `frontend/src/features/tasks/tasks-view.tsx` now calls `registerRepo`/`unregisterRepo`, so
that gap is closed. Verify against the code before repeating a limitation from either
document.
