# Locus v2 — Three Agents, Two Modes

> **Status.** Not started. **This is the only plan for this project.**
>
> It absorbs and replaces `MODES_PLAN.md` (the two-mode design) and
> `IMPLEMENTATION_PLAN.md` (the original two-feature plan, whose work has shipped), both of which
> have been deleted. What was still live in them is carried below: the mode design in full, and
> the two deferrals under *Inherited decisions*.
>
> The shape of the work: **OpenCode is the authoring driver**, the time agent is promoted to a
> named **calendar agent**, and the authoring dial, presets, per-work-item resolution and the
> attempt bound carry over intact.

---

## Inherited decisions

Two things were deliberately not built earlier, and the reasoning still applies. Recording them
here so the choice is not silently re-made.

**Proactive scheduler triggers — deferred then, built now (Phase 6).** The scheduler has always run
on request: plan, review, apply. Firing it automatically was deferred because *"proposing calendar
changes nobody asked for"* needs somewhere to deliver the proposal, which is a notification system
rather than a scheduling one. Phase 6 builds the trigger and Phase 7 builds the delivery, which is
why they are one pair and not two independent phases — the original objection is exactly what
Phase 7 answers.

**A scheduling framework (APScheduler, Celery) — still deferred.** In-process asyncio loops cover
the need; Phase 6 adds a fourth to the three already running. Adding a dependency for this would be
premature, and *"the real forcing function is multi-instance deployment, which needs row locking
regardless"* — still true, and still not done.

**Nothing here has run against live third-party services.** Response shapes are written against the
documented APIs. The solver, the parsers and the credential isolation are exercised directly and do
not depend on those services; every call that reads or writes to them is unproven. That is
unchanged by this plan and is the first thing to fix once the pipeline is exercised for real.

---

## The architecture

### Three agents. Everything else is deterministic, on purpose.

| Agent | Reads | Returns | Tools bound |
|---|---|---|---|
| **Analysis** *(built)* | the diff, Slack, tickets | findings, a review verdict | **none** |
| **OpenCode** *(new)* | a brief assembled by Locus | a branch and a pull request | a checkout and a shell — nothing else |
| **Calendar** *(new)* | a calendar, an inbound message | availability, a reschedule proposal | **none** on the classifier half |

Everything below is *not* an agent, and each one is a deliberate refusal:

- **the review request** — `format_review_notification` builds a string, `post_review_notification`
  posts it
- **the merge gate** — `evaluate_merge_gate` is a set of boolean checks
- **the QA routing** — the verdict classifier is a model with no tools; what happens next is code
- **the board moves** — `project_board.move_card`, ordered by the board's own columns
- **the settings resolution** — one module, and nothing else may disagree with it

Every one of those either sends a message to a person or writes to a branch. A second path to
the same outward message is the failure `comms_log` and the idempotent PR comment were both
written to prevent, and a model deciding whether to notify a reviewer produces a review request
that silently does not send — which is indistinguishable from a reviewer ignoring you.

### The flow, end to end

```
   ticket assigned
        │
        ├── ASSISTED ──────────── you write the code, push a branch
        │
        └── AUTONOMOUS ───────── OpenCode agent
                                   ├── reuses the issue's linked branch, or cuts one
                                   ├── runs on OpenCode's own model (remote)
                                   ├── commits, pushes
                                   └── opens the pull request
        │
        ▼
   GitHub `opened` webhook            ← the join. Nothing downstream knows which arm ran.
        │
   analysis job ─── context · security scan · code review · PR comment · Slack
        │
   review round trip ─── rounds counted · asks recorded · reviewer notified
        │
   merge gate ─── approval + green CI + no conflict + no confirmed finding
        │
   QA thread ─── brief sent · verdict read · ticket closed or reopened
        │
   board card + one living document, at every step

   CALENDAR AGENT runs alongside, never inside: it answers for you when you are
   booked, and never holds a pipeline message.
```

### Six decisions, settled before any code

**1. The author is a plug, and nothing downstream learns which one ran.**
The pipeline is webhook-driven off pull-request events. An OpenCode-authored PR flows through
the analysis, the review round trip, the QA thread and the board moves unchanged. This is what
makes the second mode a setting rather than a fork.

**2. The agent that writes code never runs where Locus's own credentials live.**
OpenCode gets a shell. Locus's working directory holds `.env` with `SECRET_KEY` and
`ENCRYPTION_KEY` — the one value that must never change or every stored credential becomes
permanently undecryptable. The driver runs in an isolated workspace with a scoped token and no
access to the backend's own tree. This is the single most important rule in the document.

**3. Autonomous is bounded, and failures consume the bound too.**
An agent that reworks indefinitely destroys `PRReview.round_number`, the signal that makes a
stalled review visible. A run that times out, blows the diff cap, or fails the test gate spends
an attempt exactly as a rejected review does — otherwise a reliably-failing ticket retries
forever and the bound protects nothing.

**4. The mode resolves per work item.**
Work item → repo → account, most specific wins. As one global switch the riskiest ticket in the
backlog sets policy for every ticket, so teams leave it off and the mode is never exercised.

**5. The calendar agent never holds a pipeline message.**
Delaying a review request until a focus block ends manufactures the exact silence that makes an
approved pull request look like a broken feature.

**6. Analysis stays local. Authoring does not — and the product must say so.**
Every model that reads your code *automatically* — the security scanner, the code reviewer, the QA
classifier, the asks summarizer — runs on `MOE_BASE_URL` over loopback, on every push, without
being asked. That is unchanged and it is the claim worth keeping.

The authoring agent is different. A local 35B model writing production code against a real ticket
is the weakest link in the whole mode, so **OpenCode runs on its own configured model**, which is
remote. That is a deliberate trade: better diffs in exchange for the brief leaving the machine, on
tickets a human explicitly handed over.

It is not a footnote. "Runs entirely on local models" becomes false the moment autonomous mode is
used, so the phrase has to change everywhere it appears — the README, the mode toggle, and the
pitch deck. The accurate claim is narrower and still strong: **every model that reads your code
without being asked runs locally; the one that writes code runs when you hand it a ticket, on a
model you choose.**

---

## Phase 1 — the authoring dial

Settings plumbing. Ships alone, changes no behaviour, everything else depends on it.

### 1.1 Migration `022_authoring_mode.py`

Follows `021_project_board_sync.py` exactly — `create_all`, then an `inspect`-guarded
`ALTER TABLE` per column, idempotent.

```
repo_webhooks.authoring_mode            TEXT           -- NULL = "says nothing", fall through
repo_webhooks.autonomous_max_rounds     INTEGER        -- NULL = fall through
repo_webhooks.preset_label              TEXT           -- display only
pr_agent_defaults.authoring_mode        TEXT NOT NULL DEFAULT 'assisted'
pr_agent_defaults.autonomous_max_rounds INTEGER NOT NULL DEFAULT 2
pr_agent_defaults.preset_label          TEXT
```

The repo columns are nullable and the defaults columns are not, and the asymmetry is the point:
`NULL` is how the resolver hears "this repo says nothing". A defaults row that exists is a
deliberate choice, so it must never read back as `NULL`.

`autonomous_max_rounds` defaults to `2` — the first attempt plus two reworks. Three swings, then
a person.

Also creates `work_item_settings` (a new table; `create_all` makes it and the `ALTER` loop skips
it).

### 1.2 Models

Add the three columns to `RepoWebhook` and `PRAgentDefaults`, then:

```python
class WorkItemSettings(Base):
    """
    Per-work-item overrides of the authoring mode.

    The third and most specific source `resolve_settings` reads. Autonomy is a
    judgement about *this ticket* -- a dependency bump and a change to the
    credential path are not the same risk -- and an account-wide toggle forces
    the most dangerous ticket to set policy for all of them.

    Deliberately narrow: only the authoring fields live here. Rows are sparse,
    so absence means "inherit", never "assisted".
    """

    __tablename__ = "work_item_settings"

    id = Column(Integer, primary_key=True, index=True)
    # Jira key ("LOC-42") or the "owner/repo#N" fallback worklist._task_key
    # already groups on. Same key space as PRReview.ticket_keys.
    ticket_key = Column(String(128), nullable=False, index=True)
    authoring_mode = Column(String(16), nullable=True)
    autonomous_max_rounds = Column(Integer, nullable=True)
    # Set when the bound was exhausted, or when a human took the branch over.
    # Distinct from someone choosing `assisted` by hand: this reads in the UI
    # as "handed back after N attempts", and it is what stops the next event
    # re-triggering the driver.
    handed_back_at = Column(DateTime(timezone=True), nullable=True)
    handed_back_reason = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    __table_args__ = (
        UniqueConstraint("owner_id", "ticket_key", name="uq_work_item_settings"),
    )
```

`UniqueConstraint` needs adding to the `sqlalchemy` import at `models.py:6`.

### 1.3 The resolver — `app/services/agent_settings.py`

`EffectiveSettings` gains `authoring_mode`, `autonomous_max_rounds`, `preset_label`.
`resolve_settings` gains `ticket_key: str | None = None`, and the chain becomes
**work item → repo → defaults → fallback**, with `sources["authoring_mode"]` gaining
`"work_item"` and `"handed_back"`.

`ticket_key=None` must resolve exactly as today, so every existing call site is untouched and
`tests/test_agent_defaults.py` keeps passing unchanged. The work-item layer reads *only* the two
authoring fields. A row with `handed_back_at` set forces `assisted` regardless of what sits above
it.

### 1.4 Schemas, endpoints, frontend

`AuthoringMode` enum (`assisted` | `autonomous`). Fields added to `RepoRegister`,
`RepoRegistration`, `PRAgentDefaults`, `PRAgentDefaultsUpdate`.

```
GET  /tasks/mode?task_key=...   -> WorkItemMode   (resolved, with source)
PUT  /tasks/mode?task_key=...   -> WorkItemMode   (upsert; null deletes the row)
```

Both 404 on a task not assigned to the caller — never 403, which would confirm the key exists.

An unrecognised mode string falls back to `assisted` rather than 400-ing: a bad value should
degrade to the safe behaviour, not block the save.

In `src/lib/api.ts`, `registerRepo` already takes fifteen positional arguments and has exactly
one caller (`src/pages/tasks.tsx:288`). **Convert it to an options object in this phase** — it is
a one-file change now and will not stay that way.

### 1.5 Tests — `tests/test_authoring_mode.py`

Resolution chain in both directions; `ticket_key=None` resolves identically to today;
`handed_back_at` forces assisted; all five `sources` values; `PUT /tasks/mode` on another user's
task 404s; a null mode deletes the row rather than storing null.

---

## Phase 2 — presets

A preset is a **template applied at write time**, never a stored authority. `resolve_settings` is
the sole arbiter of what a run does; a preset expanded at read time would add a second resolution
layer above it and reintroduce exactly the drift it exists to prevent.

`app/services/presets.py` holds one dict so the API and UI cannot disagree:

```python
PRESETS = {
    "assisted":   {"label": "Assisted",   "values": {"authoring_mode": "assisted",  ...}},
    "autonomous": {"label": "Autonomous", "values": {"authoring_mode": "autonomous",
                                                     "autonomous_max_rounds": 2, ...}},
}
```

Both set `auto_merge_on_approval: False`. A preset must never be the thing that enables the only
path writing to a default branch — that stays a separate, deliberate tick.

`GET /webhooks/presets` returns them. Picking one in `GlobalDefaults` (`src/ui/tasks/setup.tsx:90`)
calls `setValues({...values, ...preset.values})` — it mutates form state and nothing else. Every
dial stays visible and editable below. `preset_label` is stored for display only; the UI compares
saved dials against the preset to render "Assisted (modified)".

---

## Phase 3 — the driver contract

The seam. One phase, small, and it is what lets Phase 4 be replaced later without touching
anything else.

### 3.1 `app/services/authoring.py`

```python
class AuthoringRequest(BaseModel):
    ticket_key: str
    title: str
    description: str | None
    repo: str
    base_branch: str
    existing_branch: str | None   # the issue's linked branch, when there is one
    context: str                  # context_brief.build() output, verbatim
    asks: list[str]               # every reviewer ask, oldest first
    rejection: str | None         # QA's own words, on a post-rejection attempt
    attempt: int

class AuthoringResult(BaseModel):
    opened: bool
    pr_number: int | None
    pr_url: str | None
    branch: str | None
    files_changed: int
    lines_changed: int
    error: str | None
    driver: str

class AuthoringDriver(Protocol):
    name: str
    async def author(self, request: AuthoringRequest,
                     integration_configs: dict) -> AuthoringResult: ...
```

The driver's entire contract is **open a pull request and return its number**. It does not merge,
comment, or notify. Everything after the PR exists is the pipeline that already runs.

### 3.2 Registry

`LOCUS_AUTHORING_DRIVER`, default `none`. `NoneDriver` returns
`error="No authoring driver configured"` rather than an empty success — the same distinction
`comms_log` draws between a search that found nothing and one that never ran.

### 3.3 `AuthoringAttempt` — migration `023_authoring_attempts.py`

Append-only, the same argument as `PRReviewRound`: a mutable counter cannot answer "why did it
try again".

```
id, owner_id, ticket_key (index), repo, pr_number (nullable),
attempt, trigger, driver, model, context_mode, source_path, workspace_path,
opened, error, files_changed, lines_changed, duration_seconds, created_at
```

`trigger` ∈ `initial` | `changes_requested` | `qa_rejected`. It distinguishes "the agent has tried
three things" from "the agent tried once and a reviewer pushed back twice".

`model` and `context_mode` are recorded per attempt rather than read from config at display time.
"Which model wrote this, and how much of our internal discussion did it see" is asked after the
fact, when a config value has already moved on.

The same migration adds the three per-repo authoring columns, on `repo_webhooks` **and**
`pr_agent_defaults` so they resolve through `resolve_settings` like everything else:

```
source_path      TEXT   -- where this repo is checked out; NULL falls back to LOCUS_CODE_ROOT
prepare_command  TEXT   -- run once in the worktree before the agent (uv sync, npm ci)
test_command     TEXT   -- the gate in 4.6; NULL means no gate
```

All three nullable, because `NULL` is how the resolver hears "says nothing" and a repo with no
local checkout must still fall through to a managed clone.

**`PRJob.pr_number` is `NOT NULL` today** and an authoring job has no PR number when it starts.
Relax the column in this migration. Queuing with `0` as a sentinel is the tempting alternative and
it will be read as a real PR number by something downstream within a release.

### 3.4 `POST /tasks/author`

A board action, not a webhook. The same rule `report_sync.ensure_for_ticket` follows — it is
called from `GET /tasks/detail` and never from the listing, because a refresh would act on every
assigned item at once. Authoring on assignment has that shape with a far worse blast radius: a
morning's tickets would open a dozen pull requests together.

Guards, in order: task assigned to caller (else 404) → resolved mode is autonomous (else 409,
naming the source) → not handed back (else 409 with the reason) → driver configured (else 503) →
throughput cap not exceeded (else 429).

This is the board's **second** write. The CLAUDE.md invariant "the board offers exactly one write"
must be amended rather than quietly broken: the rule exists so a dashboard refresh cannot notify a
team twice, and a deliberate click that opens a pull request satisfies it.

---

## Phase 4 — the OpenCode driver

The phase `MODES_PLAN` left as a seam. This is where autonomous mode becomes real, and where
almost all the risk lives.

### 4.1 Where the code lives, and where the agent works

Two different questions, and conflating them is how the agent ends up editing Locus itself.

**The source** is where your repositories already sit on disk. **The workspace** is where the agent
is allowed to make changes. The first is configuration; the second is always isolated.

#### The source setting

Most people already have their repos cloned, with dependencies installed and build caches warm.
Re-cloning per attempt throws that away and spends the timeout on network, so Locus should be told
where they are:

```
LOCUS_CODE_ROOT        a folder holding many repos, e.g. E:\Github
repo_webhooks.source_path    an explicit path for one repo, overriding the root
```

Both are optional and both go through `resolve_settings`, so a repo that names its own path wins
and everything else falls back to the root. Resolution for `owner/name`, first hit wins:

1. the repo's `source_path`, if set
2. `<LOCUS_CODE_ROOT>/<name>` — the common layout
3. `<LOCUS_CODE_ROOT>/<owner>/<name>` — for people who nest by org
4. **no local copy found** → clone into the workspace root, as before

Step 4 matters. A monorepo folder is a convenience, not a requirement; a repo Locus has never seen
must still work, or autonomous mode only functions on machines that happen to be set up correctly.

#### Three checks before that path is used

**It is a git repository.** A path that is not one is a configuration error, reported as such
rather than as a failed authoring attempt.

**Its `origin` matches the repo being worked on.** `<root>/<name>` is a guess based on a folder
name, and two different `acme/api` and `beta/api` collapse to the same directory under a flat
root. Pointing the agent at the wrong codebase produces a confident, entirely wrong pull request.
Compare `git remote get-url origin` against the expected `owner/name` and refuse on mismatch.

**It is not Locus's own tree, and does not contain it.** This is the rule from decision 2, and with
a code root it stops being hypothetical: if Locus lives at `E:\Github\locus` and someone sets
`LOCUS_CODE_ROOT=E:\Github`, then authoring the `locus` repo resolves to Locus's own directory —
the one holding `backend/.env` and `ENCRYPTION_KEY`, the value that must never change or every
stored credential becomes permanently undecryptable.

The check compares the resolved path against the backend's own root in both directions and
**refuses with a named error**, never a silent skip. It is the single most likely misconfiguration
this feature has, because that layout is the normal one.

#### The workspace is still isolated

Locating the source does **not** mean editing it. The agent works in a `git worktree` cut from the
local repository:

```
LOCUS_WORKSPACE_ROOT   default: <system temp>/locus-workspaces
<root>/work/<owner>__<name>/<ticket>-<attempt>/
```

A worktree from a local repo is near-instant, shares the object store, and leaves the developer's
own checkout completely untouched — their uncommitted changes, their current branch, their stashes.
That last point is the reason this is not negotiable: a shared checkout can only have one branch
out at a time, and an agent that runs `git checkout` in the directory someone is working in
destroys their afternoon and looks like a successful run.

An **advisory lock per repo** guards the fetch and the worktree add (`app/services/locks.py`
already has the pattern). The worktree is **removed on success and kept on failure**, pruned after
`LOCUS_WORKSPACE_TTL_DAYS` (default 3) — a failed run whose tree is gone is close to undebuggable,
and this plan expects failures.

#### Dependencies, and the one escape hatch

A fresh worktree has no `node_modules` and no `.venv`, so the test gate in 4.6 cannot run. Add a
per-repo `prepare_command` (`uv sync --extra security`, `npm ci`) run once in the worktree before
the agent starts. Its failure fails the attempt before any model is invoked, which is the cheapest
possible place to find out the environment is wrong.

`LOCUS_ALLOW_IN_PLACE=1` lets the agent work directly in the source checkout. **Off by default**,
and the README states what it costs: the agent shares a working tree with a human, `git checkout`
becomes destructive, concurrent attempts on one repo are impossible, and the self-edit check is the
only thing standing between the agent and whatever else lives in that directory. It exists because
some repositories genuinely cannot be worktree'd — submodule-heavy trees, or build systems with
absolute paths baked in — not as a convenience.


### 4.2 Reusing the issue's branch

`issue_links.fetch` already queries `linkedBranches` from the issue side — it exists precisely for
*"a branch created from that panel before any pull request exists"*. If the work item has one:

- **and it has no commits beyond the base** → check it out and work on it. The ticket's existing
  Development-panel link keeps pointing at the right place, and the board stays coherent.
- **and it has commits authored by a human** → **refuse, and hand the work item back.** Someone
  started. This is the plan's human-commit rule applied at authoring time rather than only at
  rework time, and it is the same reasoning: an agent overwriting a person's work is the worst
  thing it can do quietly.
- **and it has commits from a previous attempt** → continue on it, so a rework builds on what the
  reviewer already read rather than starting over.

With no linked branch, cut `locus/<ticket-key>-<attempt>` from `base_branch`.

### 4.3 Invoking OpenCode

```
LOCUS_OPENCODE_CMD   default: opencode run --prompt-file {prompt} --cwd {workspace}
LOCUS_OPENCODE_MODEL default: unset — OpenCode's own configured model is used
```

The command is a **template, not hard-coded flags.** OpenCode's CLI surface moves, and a driver
that hard-codes today's flags breaks on an upgrade with a non-zero exit and no useful message.
Pin the exact invocation against the installed version at integration time and put it in the
README.

The prompt is written to a file rather than passed as an argument — a context brief runs to
thousands of characters and will exceed command-line limits on Windows.

**The model is OpenCode's, not Locus's.** The driver does not override it: OpenCode is configured
independently and Locus invokes it. `LOCUS_OPENCODE_MODEL` exists only to pin a specific model when
a team wants reproducibility across attempts, and is unset by default.

This is the one place the pipeline reaches a third party, so three rules apply:

- **The mode toggle names the model and states that the brief leaves the machine.** A user turning
  on autonomous mode must see which model will receive their ticket, their Slack discussion and
  their source — before the first attempt, not in a changelog.
- **The `AuthoringAttempt` row records the model.** "Which model wrote this diff" is the first
  question asked when an agent-authored change turns out to be wrong, and a mutable config value
  cannot answer it retroactively.
- **`LOCUS_AUTHORING_CONTEXT` controls how much of the brief goes out** — `full` (default; the
  whole `context_brief`, which is what makes the output good) or `ticket_only` (title, description
  and acceptance criteria; drops the Slack transcript and issue bodies). A team that cannot send
  internal discussion to a third party gets a usable mode rather than no mode, and the setting is
  recorded on the attempt so the trade is visible per PR.

**Check the model's data-retention terms before pointing it at a private repository.** Free tiers
commonly reserve the right to train on inputs, and the inputs here are proprietary source and
internal Slack threads. This is a procurement question, not an engineering one, and it belongs in
the README rather than being discovered later.

The prompt is: the ticket title and description, `context_brief.build()` verbatim, then `asks`
(every reviewer request across every round, oldest first — one satisfied in round two is still
something the rework must not undo), then `rejection` if this follows a QA failure. Then explicit
scope instructions: change only what the ticket asks for, do not reformat untouched files, do not
add dependencies without saying why in the commit message.

### 4.4 What it is forbidden to touch

Enforced on the **diff, after the run, before the PR is opened** — not by trusting the prompt.

| Path | Why |
|---|---|
| `.github/workflows/**` | a model that read attacker-influenced text must not edit what CI runs |
| `**/.env*`, `**/*.pem`, `**/*.key` | secrets |
| `backend/app/security.py`, `credential_context.py` | the credential path |

A touched denylist path **aborts the attempt and records it**. It does not open a PR with those
files reverted — a run that tried is a signal worth surfacing, and silently editing the agent's
diff means the reviewer reads something the agent did not produce.

`migrations/**` is deliberately *not* on the list. Schema changes are legitimate work, and the
review and CI gates are what catch a bad one.

### 4.5 Time and size bounds

```
LOCUS_AUTHORING_TIMEOUT_SECONDS   default 1200   (20 minutes)
LOCUS_MAX_CHANGED_FILES           default 25
LOCUS_MAX_CHANGED_LINES           default 600
```

The wall-clock cap kills the subprocess and records a timed-out attempt. The size caps are checked
against the diff before opening: **a 4,000-line agent-authored diff is not reviewable**, and the
throughput cap in Phase 5 exists for exactly the same reason — reviewer attention is the scarce
resource this whole mode spends.

Exceeding a cap consumes an attempt. It is not retried automatically with a smaller scope; the
ticket was too big for the mode, which is information the human should get.

### 4.6 The test gate

If the resolved settings carry a `test_command` (4.1, migration 023), run it in the worktree
after the agent finishes — with `prepare_command` having already installed dependencies there.

- **Passes** → open the PR.
- **Fails, and attempts remain** → consume the attempt, do not open a PR, retry with the failure
  appended to the prompt.
- **Fails on the last attempt** → **open it anyway**, with the failure stated at the top of the PR
  body and in the handoff message.

That last rule matters. Opening nothing after three tries leaves the human with silence, which
reads as the feature being broken. A failing PR they can see is strictly better, as long as it is
labelled — and the merge gate already requires green CI, so it cannot land.

### 4.7 `github_pr.create_pull_request` does not exist yet

`app/services/github_pr.py` reads pull requests, merges them, and comments on them — it has no
create. Add it in this phase:

```python
async def create_pull_request(
    token: str, repo: str, *, title: str, head: str, base: str, body: str,
    draft: bool = False,
) -> dict:
```

Handle the two failures that actually happen: a PR already open for that head (GitHub returns 422
— treat as success and return the existing one, since the retry path will hit this) and a head
with no commits ahead of base (422 — the agent produced nothing; see 4.9).

### 4.8 The pull request body

Non-negotiable content, in this order:

1. **A line stating the change was machine-authored**, naming the driver and the model. Knowing a
   diff was model-written is material to how carefully it is read, and hiding it is the single
   most dishonest thing this feature could do.
2. The ticket, linked with a closing keyword so `get_linked_issues` finds it.
3. Attempt number, and the reviewer asks or QA rejection it is responding to.
4. The test-gate result, including a failure.
5. The report document link.

### 4.9 Failure modes, each with a defined outcome

| What happened | Outcome |
|---|---|
| OpenCode exits non-zero | attempt recorded with stderr; no PR |
| Produced no diff | attempt recorded; **no empty PR** |
| Exceeded time or size cap | attempt recorded with the measurement |
| Touched a denylisted path | attempt recorded, named; no PR |
| Human commits on the linked branch | work item handed back immediately |
| Test gate failed, attempts remain | attempt consumed, retried |
| Push rejected (branch moved) | attempt recorded; the next one re-fetches |

Every row consumes an attempt. That is decision 3: without it, a reliably-failing ticket retries
forever and the bound protects nothing.

### 4.10 Tests — `tests/test_opencode_driver.py`

The subprocess is faked; these are about the driver's decisions, not about OpenCode.

- a source path resolving to Locus's own tree is refused, and the error names it
- a source path whose `origin` does not match the repo is refused
- `<root>/<name>` and `<root>/<owner>/<name>` both resolve; neither existing falls back to a clone
- the worktree is cut from the local repo and the source checkout's branch is unchanged afterwards
- `prepare_command` failing fails the attempt before the model is invoked
- a denylisted path in the diff aborts and opens no PR
- a diff over the file or line cap aborts and records the measurement
- an empty diff opens no PR
- a linked branch with human commits hands the work item back and does not run the agent
- a linked branch with a prior attempt's commits is continued, not recreated
- the worktree is removed on success and kept on failure
- the prompt file contains the context brief, every ask, and the rejection text
- a 422 for an already-open PR resolves to that PR rather than failing
- the PR body names the driver and the model
- the test gate failing on the final attempt opens the PR with the failure stated

---

## Phase 5 — the bound and the handoff

Nothing before this is dangerous; nothing before this is complete either.

### 5.1 `authoring.should_retry()`

Returns `(False, reason)` when: the item is handed back; the mode is not autonomous; attempts
under this ticket ≥ `autonomous_max_rounds + 1`; or **a human has pushed to the branch since the
last attempt**.

### 5.2 Triggers

- **Changes requested** — in `_run_review_job` (`webhooks.py:1007`), after the board move and
  before the Slack early-return, so a repo with no review channel still gets the behaviour it
  enabled.
- **QA rejection** — in `qa_feedback.handle_qa_reply`'s `BROKEN` arm, after the reopen. The retry
  opens a *new* pull request, which is exactly what `work_item.resolve_key` and `sibling_reviews`
  were built for: the new PR inherits the rejection history for free.

### 5.3 The handoff

Write `handed_back_at` + `handed_back_reason`, then announce to the review Slack channel, to
`comms_log`, and into the report document on the next `report_sync.refresh`.

The wording states the count and what happens next: *"Locus attempted this three times and the
test suite is still failing. It is yours now — the branch, the review thread and the report are
unchanged."*

**The database write commits even if the announcement raises.** The reverse — announcing a handoff
that did not persist — re-triggers the driver on the next event.

### 5.4 The throughput guard

`MAX_OPEN_AUTONOMOUS_PRS = 3` per (owner, repo), counted from `AuthoringAttempt` joined to
`PRReview.state != merged`.

This is the rubber-stamping mitigation. The approval opening the merge gate is a review submitted
by a real person — the risk is not the absence of a human, it is more pull requests arriving than
anyone can genuinely read, with auto-merge making a fast click terminal. An interlock between the
two settings would not touch that; a cap does.

Exceeded: `POST /tasks/author` returns 429, and the automatic retries hold **silently** — a held
retry that reports every minute trains people to ignore the channel, the same rule
`automerge.sweep_once` follows.

### 5.5 Merge gate additions

Two stated blockers in `evaluate_merge_gate`: an agent-authored PR touching `.github/workflows/**`
never auto-merges at any approval; and the approving reviewer must differ from the PR author —
true today by construction, worth asserting so it cannot regress.

Review findings still do not block at any priority, `p1` included. Do not quietly tighten that for
authored PRs: it would make the approval advisory, which is the failure the current wording
describes.

---

## Phase 6 — the calendar agent

Substantially built already and entirely request-driven: a 367-line solver in
`services/scheduler.py`, 497 lines in `calendar.py`, eight endpoints in `routers/schedule.py`, and
**no background loop**. `POST /schedule/apply` already exists as the human-confirm step, which is
exactly the propose-only shape this needs.

### 6.1 `TimeAgentSettings` — migration `024_calendar_agent.py`

One row per user, `owner_id` unique — per user rather than per repo, because a calendar belongs to
a person.

```
enabled              INTEGER NOT NULL DEFAULT 0
auto_apply           INTEGER NOT NULL DEFAULT 0   -- propose vs act
auto_reply_invites   INTEGER NOT NULL DEFAULT 0
auto_reply_busy      INTEGER NOT NULL DEFAULT 0
working_hours_start  STRING(5)  DEFAULT '09:30'
working_hours_end    STRING(5)  DEFAULT '18:30'
protect_focus_blocks INTEGER NOT NULL DEFAULT 1
slack_member_id      STRING(32)                   -- resolved once via auth.test
```

Four defaults are off, each for a reason. `enabled`, because a feature that starts touching a
calendar unasked is the worst first impression available. `auto_apply`, because a moved meeting is
visible to everyone invited. Both auto-replies, because they post to real people — the same
category as auto-merge, and they earn the same treatment.

Times are `HH:MM` interpreted in `User.timezone` through a real timezone library. The default zone
is UTC+05:30 and the half-hour offset breaks naive hour arithmetic.

`slack_member_id` holds `U04AB…`, not a handle. A Slack mention arrives in message text as
`<@U04AB…>` while `reviewer_contacts` stores handles — different namespaces that never compare
equal, which is why mention matching silently never fires without this.

### 6.2 `calendar_agent_loop` in `app/services/worker.py`

The fourth loop, started in `main.py`'s lifespan beside `worker_loop`, `qa_email_loop` and
`merge_gate_loop`. Takes a new `CALENDAR_LOCK` advisory lock — two instances proposing the same
reshuffle would double-notify.

Interval in minutes, not seconds: the ceiling on how fast a calendar changes is far below the
ceiling on how fast Google rate-limits.

Per enabled user: `scheduler.find_conflicts` over the next 14 days, then
`plan_for_new_event` / `plan_for_deadline` — all already written and tested.

### 6.3 Propose-only

With `auto_apply` off, the proposal is stored and surfaced; `POST /schedule/apply` executes it,
unchanged. Anything with external attendees is reported blocked rather than moved —
`scheduler.classify_event`'s existing behaviour, which this phase must not weaken.

---

## Phase 7 — availability and interruption

Phase 6 makes the calendar agent autonomous. This makes it answer the question the calendar exists
to answer: **can this person be reached right now, and if not, when?**

### 7.1 `app/services/availability.py`

```python
class Availability(BaseModel):
    """
    Whether the owner can be reached, and until when.

    Carries no event title, attendee, location or description. The type is the
    enforcement: a busy reply is posted into a channel other people read, and
    "in a 1:1 with Priya re: restructure" must not be able to reach it. There
    is no field to leak.
    """
    state: Literal["free", "busy", "focus", "off_hours"]
    until: datetime | None
    next_free: datetime | None
```

Reads the primary calendar through `google_auth.valid_access_token` — never
`credentials["access_token"]` raw, which works for exactly one hour after the integration is
connected and returns 401 forever after.

**Returns `free` when the calendar cannot be read.** A broken token and a real meeting produce
identical silence, and defaulting to busy fails in the direction that makes the user unreachable.
The breakage surfaces through `integration_health`, which is what it is for.

### 7.2 Where an interruption comes from

Extend `routers/slack_events.py`. Three placement rules:

1. **After** the QA-thread lookup fails (`slack_events.py:161`) — a QA reply must reach
   `qa_feedback`, never be intercepted.
2. The existing `bot_id` / `subtype` early-return **stays** and now protects this path too: the
   busy reply is posted by the bot, and without that guard it would answer itself. The same
   self-triggering failure the `@locus ignore` marker rule prevents.
3. The `thread_ts` requirement is relaxed **for this branch only** — a top-level channel mention
   carries none, and being pinged in a channel is the ordinary case.

### 7.3 Importance is decided deterministically first

1. Sender is a reviewer on a repo where you have an open review round → **important**
2. The message names a work item `worklist.build()` reports blocked on you → **important**
3. It is a QA thread → not an interruption; `qa_feedback` owns it
4. Otherwise → a classifier returning `important` / `routine` / `unclear`, **no tools bound**,
   following `qa_feedback.classify_reply` exactly

`unclear` resolves to **routine**. The busy reply goes out either way, so the two failure modes are
"an important message got a plain reply" and "a focus block was interrupted over nothing". The
second is worse.

### 7.4 The reply, and the proposal

Off by default. State and end time only, and it **names its timezone** — "booked until 15:30 IST",
never "until 15:30". Anything the backend formats for a human names its zone; `google_meet`
stamping "UTC" onto server-local times is the bug that rule was written from.

`focus` and `busy` read differently: a meeting has an end time, a focus block is a choice. Off-hours
gets the plainest version and no reschedule offer.

**One reply per thread per day**, checked against `InterruptionEvent` before sending. A repeating
auto-responder gets the bot muted, and a muted bot takes the review pings with it.

On `important` + `busy`/`focus`, `scheduler.find_free_slot` produces candidate times and the
proposal waits in the UI. Sent to Slack as *options*, never as a booking — writing to someone
else's calendar from an automated reply is a write nobody approved.

### 7.5 `InterruptionEvent` — migration `025_interruptions.py`

This cannot live in `communication_events`: that table's `repo` and `pr_number` are `NOT NULL` and
an interruption has neither. Reusing it means inventing a sentinel repo the next reader takes for
real.

```
id, owner_id, occurred_at, channel, participant, thread_ts, slack_channel,
availability_state, importance, importance_source, replied, reply_body,
proposal_id, excerpt
```

`importance_source` (`reviewer` | `worklist` | `classifier`) is what makes a wrong escalation
debuggable. `reply_body` is stored **as sent**, passed to the log rather than reconstructed — the
reason `merge_actions._qa_email_text` exists.

---

## Phase 8 — the board surface

- **Mode chip** on each card (`task-card.tsx`): `Assisted` / `Autonomous` / `Handed back`, the last
  carrying its reason and styled as attention, not error — it is the mode working.
- **Override toggle** in the detail panel (`pipeline.tsx`), bound to `GET`/`PUT /tasks/mode`, with
  the resolved source printed beneath it. The `sources` dict already exists for this.
- **An `authoring` stage** in `_build_stages`, rendered **only** when the resolved mode is
  autonomous — the same rule `changes_requested` follows, because a greyed-out step implies a round
  trip that did not happen. `_derive_stage` ranks it below `branch_created`, since the attempt row
  stays behind forever and a rule letting it win walks a reviewed card backwards on every refresh.
- **Attempt history** on the task: each `AuthoringAttempt` with its trigger and outcome. This is
  where a handed-back item explains itself.
- **Availability chip** in the header, reading the same `availability.current_status` the Slack
  reply uses, so the channel and the UI cannot disagree. Times render through
  `src/lib/datetime.ts` with its explicit `timeZone`.
- **Interruptions strip** on `scheduler.tsx`: who reached you while you were busy, what Locus said,
  and any proposal waiting. `importance_source` in plain words — *"your reviewer, mid-round"*,
  *"names LOC-42, blocked on you"*, *"judged important"*. The third is the only model-made claim on
  the strip and should read as weaker than the other two.

---

## Phase 9 — documentation

### 9.1 New CLAUDE.md invariants

- **The code-writing agent never runs where Locus's credentials live.** Isolated worktree, scoped
  token, denylist enforced on the diff.
- **A forbidden path aborts the attempt rather than being reverted.** The reviewer must read what
  the agent produced.
- **An empty diff opens no pull request.**
- **Every failure consumes an attempt.** Otherwise a reliably-failing ticket retries forever.
- **A human commit on the branch ends autonomous mode for that work item** — at authoring time as
  well as at rework time.
- **A busy reply carries a state and a time and nothing else.** The type is the enforcement.
- **An unreadable calendar reads free, never busy.**
- **The source location and the workspace are different settings.** `LOCUS_CODE_ROOT` says where
  your repos are; the agent still works in a worktree cut from them, so a human's checkout, branch
  and uncommitted changes are never touched.
- **A resolved source path is rejected if it is Locus's own tree, or contains it.** With a code
  root this is the likely misconfiguration, not a hypothetical one.
- **A resolved path whose `origin` does not match the repo is refused.** A folder name is a guess,
  and the failure mode is a confident pull request against the wrong codebase.
- **The analysis models run locally; the authoring model does not.** The mode toggle names the
  model and states that the brief leaves the machine, and every attempt records which model ran.

### 9.2 Invariants to amend

- *"The board offers exactly one write"* — now two; restate why authoring satisfies the reasoning.
- *"Models that read attacker-influenced text have no tools bound"* — autonomous mode is the
  deliberate exception. Name it, list the compensating constraints from 4.1/4.4/5.5, and say
  nothing else may claim the same exemption.
- *"Two background loops start in main.py's lifespan"* — already stale at three; becomes four.
- *"Every message is recorded, not summarized"* — `comms_log` stays the only writer for anything
  keyed to a pull request; `InterruptionEvent` is a second table because that one requires a repo
  and a PR number.

### 9.3 README

The two modes, **and the local/remote split stated plainly** — analysis runs on the local server,
authoring runs on OpenCode's model, with the data-retention caveat from 4.3;
`LOCUS_AUTHORING_DRIVER`, `LOCUS_OPENCODE_CMD`, `LOCUS_OPENCODE_MODEL`,
`LOCUS_AUTHORING_CONTEXT`, `LOCUS_CODE_ROOT`, `LOCUS_WORKSPACE_ROOT`,
`LOCUS_ALLOW_IN_PLACE` and the bounds — with the self-edit refusal called out, since the
`E:\Github` / `E:\Github\locus` layout triggers it; the GitHub token scoping (`contents:write` + `pull_requests:write`, explicitly **not**
`workflow`); the Slack scopes the busy reply needs and the `auth.test` step. Also correct the
stale "repo registration is API-only" line while in there.

---

## Ordering

```
Phase 1 (dial) ──┬── Phase 2 (presets, flag-gated until 4 lands)
                 └── Phase 3 (contract, ships with `none`)
                          └── Phase 4 (OpenCode)  ──  Phase 5 (bound)   ← autonomous is real here
Phase 6 (calendar agent) ── Phase 7 (availability)     independent of 1–5
Phase 8 (board UI) ── after 1; richer after 5 and 7
Phase 9 (docs) ── with each phase, not at the end
```

Phases 1, 2, 3, 6 and 7 each ship alone. The 6→7 pair is the entire calendar half and can go
first if that work is worth more sooner.

**Phase 5 is not optional.** Shipping Phase 4 without the bound means the first reviewer who
requests changes twice gets an agent that reworks forever, and `round_number` — the signal that
makes a stalled review visible — stops meaning anything.

## Risks worth naming before starting

**The driver is the product risk and almost none of the plan.** Phases 1–3 and 5–9 are plumbing
around a seam. Whether autonomous mode is any good depends on how well OpenCode does with the
brief. Measure that on real tickets before promising the mode to anyone.

**A shell in a checkout is the largest capability in the system.** Every rule in 4.1 and 4.4 exists
because of it. Do not relax the workspace isolation for convenience during development — that is
exactly when it would get relaxed and stay relaxed.

**The rework loop can converge on nonsense.** An agent satisfying each reviewer ask literally can
make the change worse. `autonomous_max_rounds = 2` bounds it; the report document's "earlier
attempts" section is what lets someone see it happened.

**OpenCode's CLI will move.** The command is a template for that reason, and the README must
record the version it was pinned against.

**Autonomous mode sends proprietary source and internal Slack threads to a third party.** That is
the cost of a model good enough to be worth using, and the mitigations are disclosure rather than
prevention: the toggle names the model, the attempt records it, and `ticket_only` exists for teams
that cannot send discussion out. Confirm the provider's retention and training terms before the
first real repository — it is the one risk here that cannot be walked back after the fact.

**An auto-responder is the feature users disable first.** A busy reply that fires twice gets the
bot muted, which takes the review pings and QA threads down with it. The once-per-thread-per-day
cap is load-bearing, not polish.
