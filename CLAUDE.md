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
`app/services/project_board.py` writes the card. A board's columns are not columns: they are
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
separate and both matter. Postgres sessions are pinned to UTC in `app/database.py` rather
than inheriting the server's zone — a session that inherits it serialized the same row as
`+05:30` on a developer's machine and `+00:00` in production, both naming the same instant,
with the difference invisible until something compared or cached them. Display is applied
once, in `src/lib/datetime.ts`, which passes an explicit `timeZone` so every viewer reads the
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

Note that `migrations/README.md`'s table is stale — it lists two scripts under old names, and
many more exist on disk. Trust the directory, not either document's count.

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
- Multi-instance deployment is guarded but not proven. The job claim is an atomic conditional
  UPDATE, and the two sweeps take Postgres advisory locks (`app/services/locks.py`), so
  duplicate outward messages are prevented by construction rather than by there being one
  process. It has not been run multi-instance in anger.
- Gitleaks is optional and not bundled, so committed-secret detection is skipped when it is
  absent.

**README.md's "Known limitations" is stale on one point:** it says repo registration is
API-only with no UI. `src/pages/tasks.tsx` now calls `registerRepo`/`unregisterRepo`, so
that gap is closed. Verify against the code before repeating a limitation from either
document.
