# Implementation Plan — Coding Agent

> **Goal.** Close the last human step. Today a ticket lands on someone, they write the code,
> and Locus takes over from the pull request onward. This plan has Locus write the code too:
> a ticket is assigned, an agent picks it up in a workspace of cloned repositories, works
> until the tests pass, and opens a pull request. Everything after that — analysis, senior
> dev review, merge, testing team — runs unchanged, because the pipeline already starts at a
> pull request.

**The workspace is a folder of clones.** One directory holds the repositories Locus is allowed
to work in, cloned once and kept. A job does not re-clone; it takes a `git worktree` off the
existing clone, works there, pushes, and the worktree is removed. This is cheap (the object
store is shared, so a worktree costs a checkout rather than a fetch), it survives restarts,
and it gives each job an isolated working tree — two jobs on one repository cannot overwrite
each other's files, which a single shared checkout would guarantee.

**What does not change.** The agent's only output is a pushed branch and an opened pull
request. `webhooks.py`, `review_flow.py`, `automerge.py`, `merge_actions.py` and
`qa_feedback.py` are untouched. That is the point of putting the agent in front of the
pipeline rather than inside it.

---

## Phase 0 — Foundation (blocking)

### 0.1 The workspace root and the repository pool

A configured directory (`WORKSPACE_ROOT`) holding one clone per registered repository.

- `app/services/workspace.py`: `ensure_clone(repo)`, `open_worktree(repo, branch)`,
  `discard_worktree(handle)`.
- Clones are made once and fetched thereafter. A missing clone is created on first use so
  adding a repository to the pool needs no separate step.
- Every path is resolved and checked to be inside `WORKSPACE_ROOT` before any write. A repo
  name arrives from a webhook and a ticket, which is to say from outside — `../` in one must
  not reach the filesystem. This is the same reasoning as escaping repository names into the
  GraphQL query in `issue_links`.
- Worktrees are removed in a `finally`, and orphans are swept at startup alongside
  `worker.recover_stale_jobs`. A crashed job otherwise leaves a checkout per attempt and the
  disk fills silently.

**Blocks:** everything below.

### 0.2 Push credentials scoped to the pool

The agent pushes. Today's stored GitHub token is the user's, with whatever scope they granted.

- Push with the registered repository's own credential, never a token that reaches beyond the
  pool. A deploy key per repository is the tighter option and is worth the setup.
- The token must never be written into the worktree — no `.git-credentials`, no remote URL
  carrying it. Use an askpass helper or a per-invocation header so a leaked worktree is not a
  leaked credential.

**Blocks:** 2.4 (opening the pull request).

### 0.3 Per-repo build and test commands

The agent has to see its own failures, and only the repository knows how to run its tests.

- Add `test_command`, `build_command`, `setup_command` to `RepoWebhook`, resolved through
  `agent_settings.resolve_settings` like every other setting — repo value wins, blank falls
  back to the account default. Do not read either source directly.
- A repository with no test command is allowed but the job is marked as such on the pull
  request, because "the tests pass" and "there are no tests" must not read identically to a
  reviewer.

**Blocks:** 2.3. An agent that cannot run the tests produces pull requests that do not
compile, and the senior dev spends their review budget on that instead of on the design.

---

## Phase 1 — The job

### 1.1 `CodingJob`

`PRJob` cannot carry this: it is keyed `(repo, pr_number)` and a coding job has no pull
request yet — which is the entire point of it.

```
id, ticket_key, repo, branch, kind, status, attempts,
started_at, completed_at, result_json, error, owner_id
```

`kind` is one of `implement`, `address_review`, `fix_after_qa`. Same table, different brief;
splitting them into three tables would triplicate the claim and recovery logic for no gain.

Reuse what `worker.py` already earned:

- The claim is a conditional `UPDATE queued -> running`; only the worker whose UPDATE reported
  a row proceeds. Two workers racing must produce one branch, not two pull requests.
- `recover_stale_jobs` bounded by `attempts`, failing past `MAX_ATTEMPTS` with a reason rather
  than requeueing forever.
- **Its own `STALE_JOB_MINUTES`.** A coding run is far slower than a 30–60s analysis, and
  reclaiming a live one means two agents pushing to one branch. Set it well clear of the
  slowest legitimate run, for the same reason the analysis one is.

### 1.2 One job per work item, ever

A ticket must not be picked up twice. The guard is a unique constraint on
`(ticket_key, owner_id)` for non-terminal states plus the claim above — not a check-then-write,
which races with itself.

Re-entry after a review or a QA rejection is a **new** job of a different `kind`, deliberately:
the first job's history is on the pull request and in the report document, and reusing the row
would lose the attempt count that stops a loop.

### 1.3 Migration

`021_coding_jobs.py`, numbered and idempotent like the rest. New installs are covered by
`Base.metadata.create_all()`.

---

## Phase 2 — The agent

### 2.1 The brief

Almost all of this exists. Assembling it is a composition, not new retrieval.

| Source | What it carries |
| --- | --- |
| `report_sync._ticket_brief` | The requirement as whoever filed it wrote it |
| `context_brief.build(ticket_key=…)` | Slack discussion, issue bodies, prior rounds on the work item |
| `resolve_settings(...).context_documents` | The org's style guide and security policy, plus the repo's own — concatenated, not overridden |
| `review_flow.summarize_asks` | `address_review` only: what the reviewer asked for, every round |
| `work_item.qa_rejection` | `fix_after_qa` only: the tester's verdict verbatim |

A repository's own `CLAUDE.md` or equivalent is read from the worktree and included. It is the
most accurate description of the codebase's conventions that exists, and it is already written.

### 2.2 Tools

Read file, write file, list, run command. Nothing else — no Slack, no Jira, no GitHub API
beyond the push in 2.4.

This is a deliberate narrowing. The rest of the pipeline holds the rule that a model reading
attacker-influenced text has no tools bound; a coding agent breaks it by construction, since
it reads a ticket body and a Slack thread and then writes code. The compensating control is
that its output can only ever become a pull request a human approves — never a merge, never a
message to a person, never a ticket transition.

`run command` is restricted to the resolved build/test/setup commands rather than being a
general shell. An agent that can run anything in a workspace holding several repositories and
a push credential is a much larger thing to reason about than one that can run the tests.

### 2.3 The loop

Work, run the tests, read the failures, work again. Bounded by attempts and by wall clock.

Terminates in exactly one of:

- **Tests pass** → commit, push, open the pull request (2.4).
- **Budget spent** → the job fails with the last test output stored. **It opens nothing.** A
  failed coding job is a task that stays `assigned` with an error on its card, not a broken
  pull request sent to a senior dev. Sending one costs the reviewer's attention and, more than
  once, their willingness to look at the next one.
- **Nothing to do** — the agent judged the work already done — is a failure with that reason,
  not a success. A silent no-op that reports success is indistinguishable from work.

### 2.4 The pull request

- Branch named from the work item, so `work_item.resolve_key` finds the ticket off the branch
  with no further plumbing. It already reads branch, title and body.
- The body carries the requirement, what was changed, and the test output.
- **Marked as agent-authored** — label, title prefix, and stated in the body. A senior dev
  reviewing agent code reviews it differently, and they are entitled to know which they are
  looking at.
- Opening the PR fires `opened`. The existing pipeline takes it from there. Nothing is called
  directly, for the same reason `automerge` does not call `run_merge_actions`: it would
  double-fire against the webhook.

---

## Phase 3 — The trigger

### 3.1 `assignment_loop`

Today `/tasks` is pull-only: `task_board.fetch_assigned` runs when someone opens the board.
Nothing acts on an assignment.

A fourth loop in `main.py`'s lifespan, beside `worker_loop`, `qa_email_loop` and
`merge_gate_loop`. For each assigned work item with no branch, no pull request and no coding
job, queue one.

Takes an advisory lock — add `CODING_LOCK` to `locks.py` beside `MERGE_SWEEP_LOCK` and
`QA_POLL_LOCK`. Without it two instances start coding the same ticket and the team gets two
pull requests for one ticket, which is worse than the duplicate-notification case the other
locks prevent.

### 3.2 Off by default, and per repository

`auto_code` on `RepoWebhook`, resolved through `agent_settings`, defaulting off. This writes
branches to a customer's repository without anyone asking each time; it is opt-in per
repository, exactly as `auto_merge` is.

### 3.3 Re-entry

- `changes_requested` recorded by `review_flow` → queue `address_review`.
- `qa_feedback.handle_qa_reply` verdict `broken` → queue `fix_after_qa`.

Both push to the **existing** branch where one is still open, so `synchronize` fires and
`record_resubmission` sends it back to the reviewer at the right round number. After a merged
attempt there is no branch to push to and the job opens a fresh pull request, which
`work_item.is_retry` already recognises and announces.

---

## Phase 4 — Surfacing it

### 4.1 A `coding` stage

Add `TaskStage.coding` between `assigned` and `branch_created`. Conditional like
`branch_created` and `changes_requested`: rendered only when a coding job exists, so a ticket
a human is writing does not show a step it will never reach.

`_derive_stage` reads it below every pull-request stage, for the reason the linked branch
ranks there — the job row outlives the run, and letting it win would walk a reviewed card
backwards on every refresh.

### 4.2 The card

The current attempt, the last test output on a failure, and a re-run button. Re-running a
failed coding job is a second write on the board; it is safe for the same reason
`POST /tasks/analyze` is — it reaches nobody. Queueing a coding job for a task that already
has one must be refused, not queued twice.

### 4.3 The record

The agent's run belongs in the document with everything else. `comms_log` with
`loop="coding"` — `full_report` already renders an unknown loop rather than dropping it, so
the section appears with no change to the renderer.

---

## Phase 5 — What has to be true before this is sold

### 5.1 Capacity

`MOE_BASE_URL` holds one model at a time and the default timeout is already 600s because agent
loops chain calls. A coding loop with test feedback is an order of magnitude more calls than a
review pass, and while it runs, every analysis and every review notification queues behind it.

This is the constraint that decides whether the feature is usable, and it is not solvable by
design. Either a second model server, or the coding agent points at a hosted model — which
changes the "inference is local and loopback-bound" claim, and that claim is customer-facing.
Decide this before Phase 2, because it changes what Phase 2 is allowed to assume.

### 5.2 The merge gate must not accept an agent approval

`evaluate_merge_gate` requires the state to be `approved`. It does not ask *who* approved.
With a coding agent writing pull requests, an agent-approved, agent-written change can reach
`main` with nothing human in the path.

Add an approver identity check. This is a small change to a function that already exists, and
it is the single control that keeps auto-merge defensible once the code is machine-written.

### 5.3 One real ticket, end to end

Phase 7.2 of the previous plan is still open — no live run against real GitHub, Jira and Slack
has happened. Doing that with a human writing the code is a prerequisite for doing it with an
agent, not an alternative to it.

---

## Sequencing

0 → 1 → 2 → 3 → 4, and 5.1 answered before 2 starts.

Phases 0 and 1 are ordinary backend work with no model involved and are worth doing first for
that reason: they are testable, and they are what makes Phase 2 replaceable. If the agent in
2.3 turns out to be the wrong one, the workspace, the job and the trigger are all still right.

**A narrower first slice**, if the greenfield case is not worth the risk yet: build 0, 1, and
the `address_review` and `fix_after_qa` kinds only. Those start from someone having stated
exactly what is wrong, the diffs are small, the context is already assembled, and a bad
attempt costs one rejected review rather than a wrong feature. `implement` is the same
machinery pointed at a vaguer brief, and can be turned on later per repository.
