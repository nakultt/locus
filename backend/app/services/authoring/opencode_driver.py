"""
The OpenCode authoring driver.

Where autonomous mode becomes real, and where almost all of the risk lives. A
shell in a checkout is the largest capability in the system; every rule below
exists because of it.

The shape of one attempt:

    resolve the source  ->  cut an isolated worktree  ->  prepare_command
      ->  write the prompt to a file  ->  run OpenCode under a wall clock
      ->  read the diff  ->  denylist, size caps, test gate
      ->  commit, push, open the pull request

Every step that can refuse does so *after* the run and *on the diff*, never by
trusting the prompt. A model that read attacker-influenced text is not a thing
to take promises from.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shlex
import shutil
import subprocess
import time
from pathlib import Path

from app.services.authoring import agent_runtime
from app.services.authoring.authoring import AuthoringRequest, AuthoringResult, context_mode
from app.services.authoring.workspace import (
    Workspace,
    WorkspaceError,
    _is_within,
    allow_in_place,
    authenticated_remote,
    prune_old_workspaces,
    redact,
    resolve_source,
    run_git,
    same_path,
    workspace_root,
)
from app.services.integrations import github_pr

logger = logging.getLogger(__name__)

# The command is a **template, not hard-coded flags**. OpenCode's CLI surface
# moves, and a driver that pins today's flags breaks on an upgrade with a
# non-zero exit and no useful message. Pin the exact invocation against the
# installed version at integration time and record it in the README.
DEFAULT_COMMAND = "opencode run --prompt-file {prompt} --cwd {workspace}"

# The deployment-wide defaults. Each is now an account setting that falls back
# to its environment variable; call the `agent_runtime` accessor rather than
# reading these constants, or an account's own bound is silently ignored.
TIMEOUT_SECONDS = int(os.getenv("LOCUS_AUTHORING_TIMEOUT_SECONDS") or 1200)
MAX_CHANGED_FILES = int(os.getenv("LOCUS_MAX_CHANGED_FILES") or 25)
MAX_CHANGED_LINES = int(os.getenv("LOCUS_MAX_CHANGED_LINES") or 600)

# Enforced on the diff, after the run, before the pull request is opened.
#
# A touched denylist path **aborts the attempt and records it**. It does not
# open a pull request with those files reverted: a run that tried is a signal
# worth surfacing, and silently editing the agent's diff means the reviewer
# reads something the agent did not produce.
#
# `migrations/**` is deliberately absent. Schema changes are legitimate work,
# and the review and CI gates are what catch a bad one.
DENIED_PATTERNS = (
    # A model that read attacker-influenced text must not edit what CI runs.
    ".github/workflows/",
    # Secrets.
    ".env",
    ".pem",
    ".key",
    # The credential path itself.
    "backend/app/security.py",
    "backend/app/services/credential_context.py",
)


def denied_paths(paths: list[str]) -> list[str]:
    """
    Which of these the agent is forbidden to touch.

    Directory patterns match anywhere in the path; bare extension-style ones
    are matched against the last segment, so `.env` catches `.env`,
    `backend/.env.local` and `config/.env` without catching `environment.py`.
    """
    hits: list[str] = []

    for path in paths:
        lowered = path.lower()
        name = lowered.rsplit("/", 1)[-1]

        for pattern in DENIED_PATTERNS:
            directory_like = "/" in pattern
            matched = (
                pattern in lowered
                if directory_like
                else (name.startswith(pattern) or name.endswith(pattern))
            )
            if matched:
                hits.append(path)
                break

    return hits


def _slug(value: str) -> str:
    """A ticket key safe for a branch and a directory name."""
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in value).strip("-")


def prepare_workspace(
    repo: str,
    *,
    source_path: str | None,
    ticket_key: str,
    attempt: int,
    base_branch: str,
    existing_branch: str | None,
    clone_url: str | None = None,
) -> Workspace:
    """
    An isolated checkout to work in, and the branch to work on.

    A worktree cut from the local repository when there is one, a fresh clone
    when there is not. Either way the developer's own checkout keeps its
    branch, its uncommitted changes and its stashes -- that is the whole point,
    and the reason `LOCUS_ALLOW_IN_PLACE` is off by default.
    """
    source = resolve_source(repo, source_path)

    if source is not None and allow_in_place():
        # The escape hatch. The self-edit check has already run inside
        # resolve_source, and it is the only thing standing between the agent
        # and whatever else lives in that directory.
        base = base_branch or _default_branch(source)
        branch = existing_branch or f"locus/{_slug(ticket_key)}-{attempt}"
        return Workspace(
            path=source, branch=branch, base_branch=base, source=source, in_place=True
        )

    owner, _, name = repo.partition("/")
    target = (
        workspace_root() / "work" / f"{owner}__{name}" /
        f"{_slug(ticket_key)}-{attempt}"
    )
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    target.parent.mkdir(parents=True, exist_ok=True)

    if source is None:
        if not clone_url:
            raise WorkspaceError(
                f"No local checkout for {repo} and no clone URL available. Set "
                "source_path for this repo, or LOCUS_CODE_ROOT."
            )
        run_git(["clone", clone_url, str(target)], target.parent)
        base = base_branch or _default_branch(target)
        branch = existing_branch or f"locus/{_slug(ticket_key)}-{attempt}"
        _checkout(target, branch, base, fetched=True)
        return Workspace(
            path=target, branch=branch, base_branch=base, source=None
        )

    # Fetch once, under the caller's per-repo lock, then cut the worktree. The
    # fetch is what makes a rework build on what the reviewer already read
    # rather than on a stale local base.
    # Fetched from the authenticated URL rather than the bare remote name.
    # The source checkout's own `origin` is an unauthenticated https URL, and
    # with prompting disabled that fetch simply fails -- silently, since this
    # is check=False -- leaving the rework to branch from a stale base. The
    # refspec is required when fetching from a URL: without it the remote
    # tracking refs are not updated and `_checkout` cannot find origin/<base>.
    run_git(
        [
            "fetch",
            _remote_for(source, clone_url),
            "+refs/heads/*:refs/remotes/origin/*",
            "--prune",
        ],
        source,
        check=False,
    )

    # Clear registrations whose directory is gone, before adding one back.
    # Removing a worktree directory with `shutil.rmtree` -- which the block
    # above does on a re-run, and which `prune_old_workspaces` does on every
    # TTL sweep -- deletes the files but leaves git's registration behind. The
    # next `worktree add` at that path then fails permanently with "is a
    # missing but already registered worktree", and because the path is keyed
    # by attempt number the failure is invisible until a retry lands on it.
    # Prune is safe: it only drops registrations whose directory no longer
    # exists, so a live worktree is untouched.
    run_git(["worktree", "prune"], source, check=False)
    base = base_branch or _default_branch(source)
    branch = existing_branch or f"locus/{_slug(ticket_key)}-{attempt}"

    _release_worktree_for_branch(source, branch)

    if _branch_exists(source, branch):
        try:
            run_git(["worktree", "add", str(target), branch], source)
        except WorkspaceError as exc:
            if "already used by worktree" in str(exc).lower():
                _release_worktree_for_branch(source, branch)
                run_git(["worktree", "add", str(target), branch], source)
            else:
                raise
        if existing_branch and _branch_exists(source, f"origin/{branch}"):
            run_git(["reset", "--hard", f"origin/{branch}"], target)
    else:
        start = f"origin/{branch}" if (existing_branch and _branch_exists(source, f"origin/{branch}")) else (
            f"origin/{base}" if _branch_exists(source, f"origin/{base}") else base
        )
        run_git(["worktree", "add", "-b", branch, str(target), start], source)

    return Workspace(path=target, branch=branch, base_branch=base, source=source)


def _release_worktree_for_branch(source: Path, branch: str) -> None:
    """
    Remove any previous attempt worktrees that currently hold this branch.

    Git forbids checking out the same branch in multiple worktrees. When a
    previous attempt fails and its worktree is kept for debugging, the next
    attempt on that branch (a rework) would fail with 'already used by worktree'.
    Releasing prior attempt worktrees frees the branch for the new run.
    """
    res = run_git(["worktree", "list", "--porcelain"], source, check=False)
    if res.returncode != 0:
        return

    branch_ref = f"refs/heads/{branch}"
    worktree_path = None
    admin_base = source / ".git" / "worktrees" if (source / ".git").is_dir() else None

    for line in res.stdout.splitlines():
        line = line.strip()
        if line.startswith("worktree "):
            worktree_path = line[len("worktree "):].strip()
        elif line.startswith("branch "):
            curr = line[len("branch "):].strip()
            if (curr == branch_ref or curr == branch) and worktree_path:
                p = Path(worktree_path).resolve()
                if not same_path(p, source):
                    run_git(["worktree", "remove", "--force", str(p)], source, check=False)
                    if p.exists():
                        shutil.rmtree(p, ignore_errors=True)
                    if admin_base and admin_base.exists():
                        for admin in admin_base.iterdir():
                            gitdir_file = admin / "gitdir"
                            if gitdir_file.exists():
                                try:
                                    target_p = Path(gitdir_file.read_text().strip()).resolve()
                                    if same_path(target_p, p) or _is_within(target_p, p):
                                        shutil.rmtree(admin, ignore_errors=True)
                                except Exception:
                                    pass
            worktree_path = None

    run_git(["worktree", "prune"], source, check=False)


def _remote_for(source: Path, clone_url: str | None) -> str:
    """
    What to fetch from: the authenticated clone URL, or the plain remote.

    The clone URL already carries the token, so it is preferred when the
    checkout's own remote is https and would otherwise need a credential
    helper. A local or ssh remote is left alone -- see `authenticated_remote`.
    """
    if not clone_url:
        return "origin"
    url = run_git(["remote", "get-url", "origin"], source, check=False).stdout.strip()
    return clone_url if url.startswith("https://") else "origin"


def _default_branch(path: Path) -> str:
    """
    The checkout's own default branch.

    Read rather than assumed: cutting from `main` in a repo still on `master`
    fails with a git error that reads as a bug rather than a naming problem.
    """
    result = run_git(
        ["symbolic-ref", "--short", "refs/remotes/origin/HEAD"], path, check=False
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip().split("/", 1)[-1]

    for candidate in ("main", "master"):
        if _branch_exists(path, f"origin/{candidate}") or _branch_exists(path, candidate):
            return candidate
    return "main"


def _branch_exists(path: Path, ref: str) -> bool:
    return run_git(
        ["rev-parse", "--verify", "--quiet", ref], path, check=False
    ).returncode == 0


def _checkout(path: Path, branch: str, base: str, *, fetched: bool = False) -> None:
    if _branch_exists(path, branch) or _branch_exists(path, f"origin/{branch}"):
        run_git(["checkout", branch], path)
    else:
        start = f"origin/{base}" if fetched and _branch_exists(path, f"origin/{base}") else base
        run_git(["checkout", "-b", branch, start], path)


def remove_workspace(workspace: Workspace) -> None:
    """
    Drop a worktree, on success only.

    Kept on failure: a failed run whose tree is gone is close to undebuggable,
    and this plan expects failures. `prune_old_workspaces` sweeps them later.
    """
    if workspace.in_place or workspace.source is None:
        shutil.rmtree(workspace.path, ignore_errors=True)
        return
    run_git(
        ["worktree", "remove", "--force", str(workspace.path)],
        workspace.source,
        check=False,
    )


def branch_commit_authors(
    workspace: Workspace, base_branch: str, branch: str
) -> list[str]:
    """Who wrote the commits on this branch that are not on the base."""
    ref = f"origin/{base_branch}" if _branch_exists(workspace.path, f"origin/{base_branch}") else base_branch
    result = run_git(
        ["log", "--format=%ae", f"{ref}..{branch}"], workspace.path, check=False
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


# Commits the driver itself makes carry this address, which is how a human's
# commits on a branch are told apart from a previous attempt's. Configurable,
# because a team may want the agent's commits attributed to a real bot account.
AGENT_EMAIL = os.getenv("LOCUS_AGENT_EMAIL") or "locus-agent@users.noreply.github.com"
AGENT_NAME = os.getenv("LOCUS_AGENT_NAME") or "Locus"


def agent_email() -> str:
    """
    The address the agent's own commits carry, for this account.

    A function rather than the constant because it is also the test for "did a
    human commit on this branch": a run that resolved a different identity than
    the one that made the commits would read a previous attempt's work as a
    person's and hand the item back.
    """
    return agent_runtime.agent_email(AGENT_EMAIL)


def agent_name() -> str:
    return agent_runtime.agent_name(AGENT_NAME)


def attribution_trailer(driver: str, model: str | None, attempt: int) -> str:
    """
    The line that says a machine wrote this commit.

    The pull request body already carries the machine-authored banner, but a
    pull request is a view and the commit is the record: it outlives the PR, it
    is what `git log` and `git blame` show, and it is what someone reads two
    years later when they are working out why a line exists. Disclosure that
    lives only in the pull request is disclosure that expires.

    Written as git trailers so it is greppable (`git log --grep`) and survives
    a squash merge, which folds the messages of every commit into one body.
    """
    ran = f"{driver} running {model}" if model else driver
    return (
        f"Machine-authored: written by {ran}, attempt {attempt}.\n"
        f"Co-authored-by: {agent_name()} <{agent_email()}>"
    )


def stamp_attribution(
    workspace: Workspace,
    base_branch: str,
    driver: str,
    model: str | None,
    attempt: int,
) -> None:
    """
    Append the attribution trailer to every commit the agent made.

    Every one, not just the tip: the agent is free to split its work, and a
    trailer on the last commit only would leave the rest of them looking
    hand-written -- which is the claim this exists to prevent.

    Rewriting is safe here and nowhere else: these commits exist only in a
    throwaway worktree and have never been pushed, so nothing else can be
    holding the old hashes. Commits that already carry the trailer are left
    alone, so a rework does not stamp the previous attempt's commits twice.

    Best-effort. A commit whose message could not be rewritten is worth far
    less than the diff it carries, so a failure here must not fail the run --
    the pull request body still carries the banner.
    """
    ref = (
        f"origin/{base_branch}"
        if _branch_exists(workspace.path, f"origin/{base_branch}")
        else base_branch
    )
    listed = run_git(
        ["log", "--format=%H", f"{ref}..HEAD"], workspace.path, check=False
    )
    if listed.returncode != 0:
        return

    shas = [line.strip() for line in listed.stdout.splitlines() if line.strip()]
    if not shas:
        return

    trailer = attribution_trailer(driver, model, attempt)
    marker = "Machine-authored: written by"

    existing = run_git(["log", "-1", "--format=%B"], workspace.path, check=False)
    if existing.returncode == 0 and marker not in existing.stdout:
        run_git(
            [
                "-c", f"user.email={agent_email()}",
                "-c", f"user.name={agent_name()}",
                "commit", "--amend", "--no-edit",
                "-m", existing.stdout.strip(),
                "-m", trailer,
            ],
            workspace.path,
            check=False,
        )


def human_commits_on(workspace: Workspace, base_branch: str, branch: str) -> bool:
    """
    Whether a person has committed to this branch.

    The rule from 4.2 and 5.1, and the worst thing the agent can do quietly is
    overwrite somebody's work. A branch carrying a previous attempt's commits
    is continued; one carrying anyone else's is handed back.
    """
    authors = branch_commit_authors(workspace, base_branch, branch)
    return any(author.lower() != agent_email().lower() for author in authors)


SCOPE_INSTRUCTIONS = """
## Scope

Change only what the ticket asks for. Specifically:

- Do not reformat, re-indent or reorganise files the change does not need.
- Do not add a dependency without saying why in the commit message.
- Do not edit CI workflows, environment files, or anything holding a secret.
- Keep the diff small enough for one person to review in a sitting. A change
  too large to read is a change nobody reads.

Commit your work. Do not push, do not open a pull request, and do not merge --
that is handled for you once you exit.
""".strip()

QA_SCOPE_INSTRUCTIONS = """
## Scope

Focus on the tester's report. Specifically:

- Fix exactly what the tester said did not work, completely and accurately.
- The reviewer asks listed above were already agreed and implemented. Keep them
  working; do not undo them, and do not treat them as the thing to build.
- Do NOT work on Locus's internal PR analysis, automated scan findings, code
  review findings, or bot inline suggestions.
- Do not implement or modify features from linked issues or background tickets
  unless the tester asked for it.
- Do not make unrelated changes outside what the tester reported.
- Do not reformat, re-indent or reorganise files the change does not need.
- Do not add a dependency without saying why in the commit message.
- Do not edit CI workflows, environment files, or anything holding a secret.
- Keep the diff focused and small enough for one person to review in a sitting.

Commit your work. Do not push, do not open a pull request, and do not merge --
that is handled for you once you exit.
""".strip()


REWORK_SCOPE_INSTRUCTIONS = """
## Scope

Focus on implementing the reviewer's requested changes. Specifically:

- Address every change requested by the reviewer completely and accurately.
- Work ONLY on the reviewer asks listed in "What reviewers have asked for".
- Do NOT work on Locus's internal PR analysis, automated scan findings, code review findings, or bot inline suggestions.
- Do not implement or modify features from linked issues or background tickets unless explicitly requested by the reviewer.
- Do not make unrelated changes outside what the reviewer asked for.
- Do not reformat, re-indent or reorganise files the change does not need.
- Do not add a dependency without saying why in the commit message.
- Do not edit CI workflows, environment files, or anything holding a secret.
- Keep the diff focused and small enough for one person to review in a sitting.

Commit your work. Do not push, do not open a pull request, and do not merge --
that is handled for you once you exit.
""".strip()


def build_prompt(request: AuthoringRequest) -> str:
    """
    The brief, as a file.

    Written to a file rather than passed as an argument: a context brief runs
    to thousands of characters and will exceed command-line limits on Windows.

    Order matters. For a rework or QA rejection, the requested changes or rejection
    are elevated to the top so the model treats them as the primary goal rather than
    re-implementing the original ticket requirements from scratch.

    **A QA rejection and a reviewer rework are different briefs.** Both were
    rendered as the second one, because `is_rework` fired on `request.asks`
    being non-empty and a QA rejection carries the review rounds' asks forward.
    So a run answering the testing team was told "a code reviewer requested
    changes", handed the *already-satisfied* asks as its PRIMARY GOAL, and told
    by the context note to "focus exclusively on the reviewer asks above" --
    with the tester's actual words a hundred lines further down, under a heading
    the scope block had just instructed it to ignore. The agent did what it was
    asked: it re-implemented the previous round and never touched what the
    tester reported. The asks still appear, because a fix must not undo a change
    the reviewer already agreed to, but they appear as a constraint and the
    rejection is the goal.
    """
    is_qa_rejection = request.trigger == "qa_rejected" or (
        bool(request.rejection) and request.trigger != "changes_requested"
    )
    is_rework = not is_qa_rejection and (
        request.trigger == "changes_requested" or bool(request.asks)
    )

    parts: list[str] = []

    if is_qa_rejection:
        # A QA rejection opens a *new* pull request on a new branch, so this
        # says "fix" rather than "rework the pull request you are on".
        parts += [
            f"# Fix after testing: {request.ticket_key}: {request.title}",
            "",
            "The previous attempt at this work item was merged, and the testing "
            f"team then reported that it does not work. In the repository "
            f"`{request.repo}`, on the branch already checked out for you, your "
            "PRIMARY GOAL is to fix exactly what the tester reported.",
            "",
            "## What the tester reported (PRIMARY GOAL)",
            "",
            "In the tester's own words:",
            "",
            "> " + (request.rejection or "").strip().replace("\n", "\n> "),
        ]

        if request.asks:
            parts += [
                "",
                "## Already agreed with the reviewer (do not undo)",
                "",
                "These were requested in earlier review rounds and are already "
                "implemented. They are constraints on your fix, not work to "
                "redo -- keep them working and do not reimplement them.",
                "",
            ]
            parts += [f"{n}. {ask}" for n, ask in enumerate(request.asks, start=1)]

        parts += [
            "",
            "## The ticket",
            "",
            (request.description or "").strip() or
            "_The ticket carries no description. Work from the title and the "
            "context below._",
        ]
    elif is_rework:
        branch_desc = f" on the branch `{request.existing_branch}`" if request.existing_branch else ""
        parts += [
            f"# Rework: {request.ticket_key}: {request.title}",
            "",
            f"You are reworking an existing pull request{branch_desc} in the repository "
            f"`{request.repo}`, on the branch already checked out for you.",
            "",
            "A code reviewer has reviewed the pull request and requested changes. "
            "Your PRIMARY GOAL is to address and implement the reviewer's requested changes. "
            "Work ONLY on the reviewer asks. Do NOT work on Locus internal PR analysis or bot inline comments. "
            "Apply your changes directly to the checked out code on this branch. "
            "Do not start from scratch or undo existing correct work.",
        ]

        if request.asks:
            parts += [
                "",
                "## What reviewers have asked for (PRIMARY GOAL)",
                "",
                "Every one of these must be addressed and implemented. "
                "A request satisfied in an earlier round must not be undone by this one.",
                "",
            ]
            parts += [f"{n}. {ask}" for n, ask in enumerate(request.asks, start=1)]

        parts += [
            "",
            "## The ticket",
            "",
            (request.description or "").strip() or
            "_The ticket carries no description. Work from the title and the "
            "context below._",
        ]
    else:
        parts += [
            f"# {request.ticket_key}: {request.title}",
            "",
            "You are writing the change for this work item in the repository "
            f"`{request.repo}`, on the branch already checked out for you.",
            "",
            "## The ticket",
            "",
            (request.description or "").strip() or
            "_The ticket carries no description. Work from the title and the "
            "context below._",
        ]

    if request.context.strip():
        if is_rework or is_qa_rejection:
            goal = (
                "the tester's report above"
                if is_qa_rejection
                else "the reviewer asks above"
            )
            parts += [
                "",
                "## Context gathered by Locus",
                "",
                "_Note: This context is provided strictly for background reference. "
                "Do NOT treat internal analysis, scanner findings, or linked issue descriptions "
                f"as work items to implement during this attempt. Focus exclusively on {goal}._",
                "",
                request.context.strip(),
            ]
        else:
            parts += ["", "## Context gathered by Locus", "", request.context.strip()]
    elif context_mode() == "ticket_only":
        # Said outright rather than left as an empty section: a reader
        # otherwise cannot tell a missing brief from a suppressed one.
        parts += [
            "",
            "## Context",
            "",
            "_Internal discussion was deliberately withheld from this run "
            "(LOCUS_AUTHORING_CONTEXT=ticket_only)._",
        ]

    if not (is_rework or is_qa_rejection) and request.asks:
        parts += [
            "",
            "## What reviewers have asked for, oldest first",
            "",
            "Every one of these still applies. A request satisfied in an "
            "earlier round must not be undone by this one.",
            "",
        ]
        parts += [f"{n}. {ask}" for n, ask in enumerate(request.asks, start=1)]

    # Only when it was not already the headline. Repeating it under "why the
    # last attempt came back" after stating it as the goal reads as two
    # different things being asked for.
    if request.rejection and not is_qa_rejection:
        parts += [
            "",
            "## Why the last attempt came back from testing",
            "",
            "In the tester's own words:",
            "",
            "> " + request.rejection.strip().replace("\n", "\n> "),
        ]

    if is_qa_rejection:
        scope_text = QA_SCOPE_INSTRUCTIONS
    elif is_rework or request.rejection:
        scope_text = REWORK_SCOPE_INSTRUCTIONS
    else:
        scope_text = SCOPE_INSTRUCTIONS
    parts += ["", scope_text]
    return "\n".join(parts)


def build_command(
    prompt_path: Path, workspace_path: Path, default_command: str | None = None
) -> list[str]:
    """
    The agent invocation, from the configured template.

    A template rather than hard-coded flags, because a coding CLI's surface
    moves and a driver pinning today's flags breaks on an upgrade with a
    non-zero exit and no useful message.

    `default_command` is the driver's own template, used when the account has
    not overridden it. It is a parameter rather than a module constant because
    two drivers share this function and their invocations differ -- but the
    account-level override is one setting, so a team that pinned a template
    keeps it whichever driver they select.
    """
    template = agent_runtime.command(default_command or DEFAULT_COMMAND).strip()
    # The model is the agent CLI's, not Locus's. This exists only to pin one
    # when a team wants reproducibility across attempts, and is unset by
    # default. Both CLIs spell the flag `--model`.
    return _command_from_template(
        template, prompt_path, workspace_path, model=agent_runtime.model().strip()
    )


def _command_from_template(
    template: str, prompt_path: Path, workspace_path: Path, *, model: str
) -> list[str]:
    """
    Render one template to argv, appending `--model` when one is pinned.

    Split in non-posix mode on Windows, because posix mode treats the
    backslashes in a Windows workspace path as escapes and eats them, and every
    path here is a Windows path. The cost is that non-posix mode *keeps* the
    quotes around a quoted argument, so `-p "do the thing"` would reach the CLI
    as a literal `"do the thing"` including the quote characters. That never
    mattered while the only template passed bare words; it matters for
    `claude -p`, whose prompt is a single argument that has to be quoted to
    survive splitting. So the quotes are stripped afterwards, which is a no-op
    for a template that has none.
    """
    rendered = template.format(prompt=str(prompt_path), workspace=str(workspace_path))
    parts = [
        _unquote(part) for part in shlex.split(rendered, posix=os.name != "nt")
    ]

    if model and "--model" not in parts:
        parts += ["--model", model]

    return parts


def _unquote(part: str) -> str:
    """Drop one matching pair of surrounding quotes, if there is one."""
    for quote in ('"', "'"):
        if len(part) >= 2 and part.startswith(quote) and part.endswith(quote):
            return part[1:-1]
    return part



# Terminal escape sequences: colour and cursor control (CSI), and the OSC
# sequences a progress display uses for hyperlinks and window titles.
_ANSI = re.compile(
    r"\x1b\[[0-9;?]*[ -/]*[@-~]"
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"
    r"|\x1b[@-Z\\-_]"
)


def _plain(text: str) -> str:
    """
    Agent output with terminal escapes removed.

    This output is not only logged: on a failure it becomes
    `AuthoringResult.error`, which is stored on `AuthoringAttempt.error` and
    rendered in the UI, so escape codes reach a person as literal `[2m` noise
    wrapped around the one line they need to read.

    Stripped here rather than asked for politely. Every driver's CLI has a
    flag for it -- `--color never` and friends -- and Codex still emitted
    escapes with that flag set, because the flag governs its *own* rendering
    and not what a tool it shells out to writes. One place that cannot be
    missed beats three flags that can.
    """
    return _ANSI.sub("", text)



def probe_cli(command: list[str], timeout: int = 6) -> str:
    """
    Run a short, read-only CLI command and return its output, or "".

    For settings-page questions like "which models can you run" -- never for
    the agent itself. Bounded and swallowing, because one of these CLIs hangs
    indefinitely on its main verb and a settings page that inherits that is a
    page nobody can use to switch away from it.
    """
    try:
        done = subprocess.run(
            command,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if done.returncode != 0:
        return ""
    return _plain(done.stdout or "")


async def run_agent(
    command: list[str], workspace: Path, timeout: int | None = None
) -> tuple[int, str]:
    """
    Run the agent under a wall clock, returning (returncode, output).

    The timeout kills the subprocess and is reported as a timed-out attempt --
    which consumes an attempt like every other failure, or a ticket that
    reliably hangs retries forever and the bound protects nothing.
    """
    if timeout is None:
        # Resolved here rather than as a default argument, which would freeze
        # the deployment's value at import and ignore the account's.
        timeout = agent_runtime.timeout_seconds(TIMEOUT_SECONDS)

    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(workspace),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            # Closed, never inherited. The same rule `run_git` follows: an
            # agent running unattended cannot answer a prompt, so it must not
            # be able to wait for one. Inheriting stdin cost three seconds and
            # a "no stdin data received" warning on every Claude Code run, and
            # a CLI that decided to read further would have hung until the
            # wall clock killed it -- spending an attempt on a prompt nobody
            # saw.
            stdin=asyncio.subprocess.DEVNULL,
        )
    except NotImplementedError:
        # The running event loop cannot spawn a subprocess, so run it on a
        # thread instead.
        #
        # This is not hypothetical and it is not rare: on Windows, uvicorn
        # picks the loop with
        #
        #     if sys.platform == "win32" and not use_subprocess:
        #         return asyncio.ProactorEventLoop
        #     return asyncio.SelectorEventLoop
        #
        # and `--reload` sets use_subprocess. So the command this project
        # documents for running the backend puts the app on a SelectorEventLoop,
        # where `create_subprocess_exec` raises NotImplementedError -- and the
        # whole authoring feature is a subprocess. Autonomous mode returned a
        # bare 500 on every attempt, while the same code called from a script
        # worked, because `asyncio.run` gets the Proactor loop.
        #
        # A driver whose availability depends on how its host was launched is
        # a driver that fails in exactly one environment and passes every test.
        return await asyncio.to_thread(_run_agent_blocking, command, workspace, timeout)

    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError:
        process.kill()
        await process.wait()
        return 124, f"Timed out after {timeout}s"

    return process.returncode or 0, _plain(
        (stdout or b"").decode("utf-8", "replace")
    )


def _run_agent_blocking(
    command: list[str], workspace: Path, timeout: int
) -> tuple[int, str]:
    """
    The threaded fallback for `run_agent`, with the same contract.

    Same return shape and the same 124-on-timeout, so the caller cannot tell
    which path ran -- including the timeout being reported as a spent attempt
    rather than an error.
    """
    try:
        done = subprocess.run(
            command,
            cwd=str(workspace),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            # As above: the threaded fallback must behave identically, or the
            # driver waits for a human on exactly one of the two code paths.
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return 124, f"Timed out after {timeout}s"

    return done.returncode or 0, _plain(
        (done.stdout or "") + (done.stderr or "")
    )


def changed_files(workspace: Workspace, base_branch: str) -> list[str]:
    """
    Every path the agent touched, committed or not.

    Both are read: an agent that edited files without committing them has still
    produced a diff, and the denylist has to see it before anything is staged.
    """
    ref = (
        f"origin/{base_branch}"
        if _branch_exists(workspace.path, f"origin/{base_branch}")
        else base_branch
    )
    paths: set[str] = set()

    for args in (
        ["diff", "--name-only", ref],
        ["diff", "--name-only", "--cached"],
        ["ls-files", "--others", "--exclude-standard"],
    ):
        result = run_git(args, workspace.path, check=False)
        if result.returncode == 0:
            paths.update(
                line.strip().replace("\\", "/")
                for line in result.stdout.splitlines()
                if line.strip()
            )

    return sorted(paths)


def diff_size(workspace: Workspace, base_branch: str) -> tuple[int, int]:
    """(files, lines) across the whole change, staged and unstaged alike."""
    ref = (
        f"origin/{base_branch}"
        if _branch_exists(workspace.path, f"origin/{base_branch}")
        else base_branch
    )
    result = run_git(
        ["diff", "--numstat", ref], workspace.path, check=False
    )
    if result.returncode != 0:
        return 0, 0

    files = 0
    lines = 0
    for row in result.stdout.splitlines():
        parts = row.split("\t")
        if len(parts) < 3:
            continue
        files += 1
        for value in parts[:2]:
            if value.isdigit():
                lines += int(value)

    return files, lines


def run_shell(command: str, workspace: Path, timeout: int = 900) -> tuple[int, str]:
    """Run a configured shell command in the worktree, output captured."""
    result = subprocess.run(
        command,
        cwd=str(workspace),
        shell=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.returncode, ((result.stdout or "") + (result.stderr or ""))[-4000:]


def build_pr_body(
    request: AuthoringRequest,
    *,
    driver: str,
    model: str | None,
    test_failure: str | None,
    doc_url: str | None,
) -> str:
    """
    The pull request body. The order here is not stylistic.

    The machine-authored line comes first because knowing a diff was
    model-written is material to how carefully it is read, and hiding it is the
    single most dishonest thing this feature could do.
    """
    issue = request.ticket_key
    lines = [
        f"> **Machine-authored.** Written by `{driver}`"
        + (f" running `{model}`" if model else "")
        + f", attempt {request.attempt}. A person has not read this diff yet.",
        "",
    ]

    if "#" in issue and "/" in issue:
        # A GitHub issue key, "owner/repo#N". The closing keyword is what makes
        # get_linked_issues find it.
        lines += [f"Closes {issue}", ""]
    else:
        lines += [f"Work item: **{issue}**", ""]

    lines += [f"## {request.title}", ""]
    if request.description:
        lines += [request.description.strip(), ""]

    if request.trigger != "initial":
        reason = {
            "changes_requested": "a reviewer requested changes",
            "qa_rejected": "the testing team rejected the previous attempt",
        }.get(request.trigger, request.trigger)
        lines += [f"This is attempt {request.attempt}, responding to {reason}.", ""]

    if request.asks:
        lines += ["### What reviewers asked for", ""]
        lines += [f"- {ask}" for ask in request.asks]
        lines += [""]

    if request.rejection:
        lines += [
            "### Why the last attempt came back",
            "",
            "> " + request.rejection.strip().replace("\n", "\n> "),
            "",
        ]

    if test_failure:
        # Stated at the top of what a reviewer reads, not buried. Opening
        # nothing after three tries leaves the human with silence, which reads
        # as the feature being broken; a failing PR they can see is strictly
        # better as long as it is labelled -- and the merge gate requires green
        # CI, so it cannot land.
        lines += [
            "### ⚠️ The test gate failed, and this was the final attempt",
            "",
            "```",
            test_failure.strip()[-2000:],
            "```",
            "",
        ]
    elif (request.settings or {}).get("test_command"):
        lines += ["The configured test command passed in the agent's worktree.", ""]
    else:
        # `test_failure` is None both when the gate passed and when there was
        # no gate to run, so claiming a pass on the strength of it alone tells
        # the reviewer a test suite verified this diff when none exists. That
        # is the same failure mode as an unparseable review degrading to an
        # empty pass: a run that checked nothing must not read as a clean one.
        lines += [
            "No test command is configured for this repository, so nothing "
            "verified this diff before the pull request opened.",
            "",
        ]

    if doc_url:
        lines += [f"[Full analysis and history]({doc_url})", ""]

    return "\n".join(lines).strip()


class CliDriver:
    """
    Drives a coding CLI in an isolated worktree and opens the pull request.

    Every refusal happens on the diff after the run, never by trusting the
    prompt. Every outcome returns an `AuthoringResult` rather than raising:
    the caller records the attempt either way, and an exception escaping past
    the recording would not consume an attempt.

    **Almost none of this is specific to any one CLI.** Three things are: the
    name, the invocation template, and the label recorded when no model is
    pinned. Everything else -- resolving the source, cutting the worktree, the
    prepare command, the wall clock, the denylist, the size caps, the test
    gate, attribution, the human-commit check, the push with prompting
    disabled, the pull request and its reviewers -- is the same work whichever
    binary writes the code. A second driver therefore subclasses this and
    overrides those three, rather than copying a thousand lines that would
    then drift apart one fix at a time.

    Subclasses set:
        name: recorded on every attempt and rendered in the UI.
        default_command: the invocation, used when the account has not set its
            own template. `{prompt}` and `{workspace}` are substituted.
        default_model_label: what to record when no model is pinned. A label
            rather than a guess -- "which model wrote this" must not be
            answered with the name of one nobody selected.
    """

    name = "cli"
    default_command = DEFAULT_COMMAND
    default_model_label = "cli-default"
    # The executable the template is expected to invoke. See `_own_settings`.
    binary = ""

    def _own_settings(self) -> bool:
        """
        Whether the account's stored invocation belongs to *this* driver.

        `command` and `model` are one account-level setting each, shared across
        drivers -- but their values are not portable. A stored template names a
        binary and a pinned model names one provider's catalogue, so switching
        the driver while leaving them in place ran the *previous* driver's
        command line: selecting Claude Code and getting `opencode run ... --model
        opencode/muse-spark-...`, which is the "looks like the setting never
        saved" failure with a shell behind it.

        Matched on the first token of the resolved template, which is the
        executable. When it does not match, the stored invocation was written
        for another driver and neither it nor the pinned model is used -- the
        driver falls back to its own defaults and says so, rather than running
        something the account did not select.
        """
        template = agent_runtime.command(self.default_command).strip()
        if not template:
            return True
        try:
            first = shlex.split(template, posix=os.name != "nt")[0]
        except (ValueError, IndexError):
            return False
        return Path(first).stem.lower() == (self.binary or self.name).lower()

    def build_command(self, prompt_path: Path, workspace_path: Path) -> list[str]:
        template = self.default_command
        if self._own_settings():
            template = agent_runtime.command(self.default_command).strip()
        else:
            logger.info(
                "Ignoring the stored agent command: it does not invoke %s. "
                "Using this driver's default.",
                self.binary or self.name,
            )

        model = self._model()
        argv = _command_from_template(
            template,
            prompt_path,
            workspace_path,
            # The label recorded when nothing is pinned is not a model name and
            # must never be passed to a CLI as one.
            model="" if model == self.default_model_label else model,
        )

        effort = self._effort()
        if effort:
            argv += self.effort_args(effort)

        return argv

    # The reasoning levels this CLI accepts, in ascending order. Declared here
    # rather than in the UI so there is one list: the form renders it and the
    # driver validates against it, and a level the CLI would reject never
    # reaches a run. Empty means the CLI has no such knob.
    effort_levels: tuple[str, ...] = ()

    # Model ids offered in the settings dropdown. Deliberately *not* a
    # hand-written catalogue of a provider's models: a name that does not exist
    # is a failed attempt that spends the bound, and these lists go stale the
    # week after they are written. Each driver either asks its CLI (see
    # `discover_models`) or offers only values documented by the CLI itself.
    #
    # The dropdown always also offers a custom value, because a list that has
    # gone stale must not be a dead end.
    static_model_choices: tuple[str, ...] = ()

    @classmethod
    def discover_models(cls) -> list[str]:
        """
        Ask the CLI what it can run, when it can answer.

        Best-effort and bounded: this is called to render a settings page, so
        a CLI that is slow, missing or broken must cost a shorter list rather
        than a page that will not load. One of the three CLIs on this machine
        hangs indefinitely on its main verb, which is exactly why the timeout
        is short and the failure is swallowed.
        """
        return []

    @classmethod
    def model_choices(cls) -> list[str]:
        """
        What the settings dropdown offers, discovered first and static second.

        Order preserved and duplicates dropped, so a discovered list reads the
        way the CLI printed it.
        """
        seen: set[str] = set()
        choices: list[str] = []
        for name in [*cls.discover_models(), *cls.static_model_choices]:
            cleaned = (name or "").strip()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                choices.append(cleaned)
        return choices

    def effort_args(self, level: str) -> list[str]:
        """
        How this CLI is told to think harder, as argv.

        A method rather than a flag name, because the three spellings are not
        interchangeable: OpenCode takes `--variant`, Claude Code takes
        `--effort`, and Codex takes a config override
        (`-c model_reasoning_effort="high"`) rather than a flag at all. The
        stored setting is the plain level, so it survives a driver change; this
        turns it into whatever the selected CLI wants.
        """
        return []

    def _options(self) -> dict:
        """This driver's stored model and reasoning level."""
        return agent_runtime.driver_options(self.name)

    def _model(self) -> str:
        """
        The model this attempt actually ran on.

        The per-driver pin first, then the legacy single `authoring_model` --
        but only when that one was written for this driver, which is what
        `_own_settings` decides. Resolved through the same path
        `build_command` uses, because `author()` used to read
        `LOCUS_OPENCODE_MODEL` from the environment while the command line
        carried the account's setting, so an account that pinned a model had
        every attempt recorded against a different one. "Every
        `AuthoringAttempt` records which model ran" is the claim that makes
        autonomous mode auditable.
        """
        pinned = self._options().get("model")
        if pinned:
            return pinned
        if not self._own_settings():
            return self.default_model_label
        return agent_runtime.model().strip() or self.default_model_label

    def _effort(self) -> str:
        """
        The reasoning level, validated against what this CLI accepts.

        A level the CLI would reject is dropped rather than passed on. Codex
        exits 1 on an unknown value, which spends an attempt on a typo in a
        settings field; the other two are less strict, and a driver that fails
        differently depending on which CLI is selected is worse than one that
        ignores a value it cannot use.
        """
        level = (self._options().get("effort") or "").strip().lower()
        if not level or level not in self.effort_levels:
            return ""
        return level

    async def author(
        self, request: AuthoringRequest, integration_configs: dict
    ) -> AuthoringResult:
        started = time.monotonic()
        model = self._model()

        def failed(error: str, **extra) -> AuthoringResult:
            return AuthoringResult(
                opened=False,
                error=error,
                driver=self.name,
                model=model,
                context_mode=context_mode(),
                duration_seconds=round(time.monotonic() - started, 2),
                **extra,
            )

        # Both keys, in the order the rest of the codebase uses them. A PAT
        # connected through the integrations UI is stored under `api_key`
        # (`get_integration_configs` puts it there, and `agent.py` reads it
        # from there); `token` is what a tool body sees after
        # `get_github_tools` rebinds it. Reading only `token` meant autonomous
        # mode reported "GitHub is not connected" on a perfectly connected
        # account -- and reported it as an authoring failure, which spends an
        # attempt, so the bound was consumed by a key name.
        github_config = integration_configs.get("github") or {}
        token = github_config.get("api_key") or github_config.get("token")
        if not token:
            return failed("GitHub is not connected, so no pull request could be opened")

        settings = request_settings(request)
        base_branch = request.base_branch or await github_pr.get_default_branch(
            token, request.repo
        )

        try:
            workspace = prepare_workspace(
                request.repo,
                source_path=settings.get("source_path"),
                ticket_key=request.ticket_key,
                attempt=request.attempt,
                base_branch=base_branch,
                existing_branch=request.existing_branch,
                clone_url=f"https://x-access-token:{token}@github.com/{request.repo}.git",
            )
        except WorkspaceError as exc:
            # A configuration problem, reported as one. Distinct from an
            # authoring failure, which is what makes it debuggable.
            return failed(str(exc))
        except Exception as exc:
            return failed(f"Could not prepare a workspace: {exc}")

        keep = True
        try:
            # Stamp the agent identity onto the worktree before the agent runs.
            #
            # SCOPE_INSTRUCTIONS tells the agent to commit its own work, and it
            # does so with whatever identity the checkout carries -- the
            # developer's. The `-c user.email=...` on Locus's own commit below
            # never applies, because by then there is nothing left to commit
            # and that case is deliberately tolerated.
            #
            # Two things break when the agent commits as a person. The record
            # contradicts the disclosure: the pull request says machine-
            # authored while `git blame` credits a human, and the history is
            # the copy that outlives the pull request. And `human_commits_on`
            # decides whether somebody has started by comparing authors
            # against AGENT_EMAIL, so the agent's own commits read as a human's
            # and the next rework hands the work item back -- the guard firing
            # on the work it was meant to protect.
            #
            # Local to the worktree, so the developer's own config is untouched.
            run_git(["config", "user.email", AGENT_EMAIL], workspace.path, check=False)
            run_git(["config", "user.name", AGENT_NAME], workspace.path, check=False)

            # Someone started. Refuse before the model is invoked -- an agent
            # overwriting a person's work is the worst thing it can do quietly.
            if request.existing_branch and human_commits_on(
                workspace, base_branch, workspace.branch
            ):
                result = failed(
                    f"{workspace.branch} carries commits by a human, so the "
                    "agent did not run."
                )
                result.hand_back_reason = (
                    f"Somebody has already started on {workspace.branch}. "
                    "The branch is untouched."
                )
                return result

            prepare = settings.get("prepare_command")
            if prepare:
                # The cheapest possible place to find out the environment is
                # wrong: before any model is invoked.
                code, output = run_shell(prepare, workspace.path)
                if code != 0:
                    return failed(
                        f"prepare_command failed before the agent ran:\n{output}",
                        workspace_path=str(workspace.path),
                    )

            head_before = run_git(["rev-parse", "HEAD"], workspace.path, check=False).stdout.strip()

            prompt_path = workspace.path / ".locus-prompt.md"
            prompt_path.write_text(build_prompt(request), encoding="utf-8")

            code, output = await run_agent(
                self.build_command(prompt_path, workspace.path), workspace.path
            )
            prompt_path.unlink(missing_ok=True)
            logger.info(
                "%s agent finished with code %s:\n%s", self.name, code, output
            )

            if code == 124:
                return failed(output, workspace_path=str(workspace.path))
            if code != 0:
                return failed(
                    f"{self.name} exited {code}:\n{output[-3000:]}",
                    workspace_path=str(workspace.path),
                )

            head_now = run_git(["rev-parse", "HEAD"], workspace.path, check=False).stdout.strip()
            run_git(["add", "-A"], workspace.path, check=False)
            staged = run_git(["diff", "--cached", "--name-only"], workspace.path, check=False).stdout.strip()

            if head_now == head_before and not staged:
                return failed(
                    "The agent produced no changes in this attempt, so nothing was committed or pushed",
                    workspace_path=str(workspace.path),
                )

            paths = changed_files(workspace, base_branch)
            if not paths:
                # No empty pull request. It puts a reviewer's name on a request
                # to read a diff that does not exist.
                return failed(
                    "The agent produced no changes, so no pull request was opened",
                    workspace_path=str(workspace.path),
                )

            forbidden = denied_paths(paths)
            if forbidden:
                # Aborts and records; it does not open a PR with those files
                # reverted. A run that tried is a signal worth surfacing, and
                # editing the agent's diff means the reviewer reads something
                # the agent did not produce.
                return failed(
                    "The agent touched paths it must not: "
                    + ", ".join(sorted(forbidden)),
                    workspace_path=str(workspace.path),
                )

            run_git(["add", "-A"], workspace.path, check=False)
            files, lines = diff_size(workspace, base_branch)

            max_files = agent_runtime.max_changed_files(MAX_CHANGED_FILES)
            max_lines = agent_runtime.max_changed_lines(MAX_CHANGED_LINES)

            if files > max_files or lines > max_lines:
                # Reviewer attention is the scarce resource this mode spends. A
                # 4,000-line agent-authored diff is not reviewable, and this is
                # not retried with a smaller scope: the ticket was too big for
                # the mode, which is information the human should get.
                return failed(
                    f"The change is too large to review: {files} files and "
                    f"{lines} lines, over the {max_files}-file / "
                    f"{max_lines}-line cap.",
                    files_changed=files,
                    lines_changed=lines,
                    workspace_path=str(workspace.path),
                )

            test_failure = None
            test_command = settings.get("test_command")
            if test_command:
                code, output = run_shell(test_command, workspace.path)
                if code != 0:
                    if settings.get("attempts_remaining", 0) > 0:
                        return failed(
                            f"The test gate failed:\n{output}",
                            files_changed=files,
                            lines_changed=lines,
                            workspace_path=str(workspace.path),
                        )
                    # Final attempt: open it anyway, labelled. Silence after
                    # three tries reads as the feature being broken.
                    #
                    # A command that fails without printing anything still
                    # failed. Falling back to the exit code matters: an empty
                    # string here reads as "no failure" and the body would
                    # claim the gate passed, which is exactly the dishonesty
                    # the machine-authored line exists to prevent.
                    test_failure = output.strip() or (
                        f"`{test_command}` exited {code} with no output"
                    )

            commit = run_git(
                [
                    "-c", f"user.email={agent_email()}",
                    "-c", f"user.name={agent_name()}",
                    "commit", "-m",
                    f"{request.ticket_key}: {request.title}",
                    "-m", attribution_trailer(self.name, model, request.attempt),
                ],
                workspace.path,
                check=False,
            )
            if commit.returncode != 0 and "nothing to commit" not in commit.stdout.lower():
                return failed(
                    f"Could not commit the agent's work: {commit.stderr or commit.stdout}",
                    workspace_path=str(workspace.path),
                )

            # The agent commits its own work, so the message above is usually
            # never written -- "nothing to commit" is the normal path, not the
            # exception. Stamp the attribution onto whatever it did write.
            stamp_attribution(workspace, base_branch, self.name, model, request.attempt)

            # Pushed to an authenticated URL, not to `origin`. The worktree
            # inherits the source checkout's remote, which is unauthenticated,
            # so this used to depend on whatever credential helper happened to
            # be installed -- a dialog on a developer's machine and nothing at
            # all on a server. An agent that runs unattended cannot answer
            # either. No upstream is set, deliberately: the token would be
            # written into the worktree's .git/config.
            push = run_git(
                [
                    "push",
                    authenticated_remote(workspace.path, token),
                    f"{workspace.branch}:{workspace.branch}",
                ],
                workspace.path,
                check=False,
            )
            if push.returncode != 0:
                # The branch moved under us. Recorded; the next attempt
                # re-fetches rather than force-pushing over whatever landed.
                #
                # Redacted: the URL above carries the token, and git echoes the
                # remote it failed to reach. Unredacted this wrote the token
                # into `AuthoringAttempt.error`, which the UI renders.
                return failed(
                    redact(f"Push rejected: {(push.stderr or push.stdout).strip()}"),
                    files_changed=files,
                    lines_changed=lines,
                    workspace_path=str(workspace.path),
                )

            pull_request = await github_pr.create_pull_request(
                token,
                request.repo,
                title=f"{request.ticket_key}: {request.title}",
                head=workspace.branch,
                base=base_branch,
                body=build_pr_body(
                    request,
                    driver=self.name,
                    model=model,
                    test_failure=test_failure,
                    doc_url=settings.get("doc_url"),
                ),
                # Account-level, and empty unless somebody typed a login. A
                # review request is a notification the recipient cannot undo,
                # so it is only ever sent to people an account named.
                reviewers=agent_runtime.pr_reviewers(),
            )
            if "error" in pull_request:
                return failed(
                    pull_request["error"],
                    files_changed=files,
                    lines_changed=lines,
                    workspace_path=str(workspace.path),
                )

            keep = False
            return AuthoringResult(
                opened=True,
                pr_number=pull_request.get("number"),
                pr_url=pull_request.get("html_url"),
                branch=workspace.branch,
                files_changed=files,
                lines_changed=lines,
                driver=self.name,
                model=model,
                context_mode=context_mode(),
                source_path=str(workspace.source) if workspace.source else None,
                workspace_path=str(workspace.path),
                duration_seconds=round(time.monotonic() - started, 2),
            )
        finally:
            # Removed on success, kept on failure: a failed run whose tree is
            # gone is close to undebuggable, and this plan expects failures.
            if not keep:
                remove_workspace(workspace)
            prune_old_workspaces()



class OpenCodeDriver(CliDriver):
    """
    OpenCode, the original driver.

    Everything it does lives in `CliDriver`. This names it, points it at
    OpenCode's invocation, and says what to record when no model is pinned.
    """

    name = "opencode"
    binary = "opencode"
    default_command = DEFAULT_COMMAND
    default_model_label = "opencode-default"
    # `--variant` is documented as "provider-specific reasoning effort", so the
    # set a given model accepts is the provider's rather than OpenCode's. These
    # are the three its own help names.
    effort_levels = ("minimal", "high", "max")

    def effort_args(self, level: str) -> list[str]:
        return ["--variant", level]

    @classmethod
    def discover_models(cls) -> list[str]:
        """
        `opencode models` prints one `provider/model` per line.

        The only one of the three CLIs that can answer this, so it is the only
        one with a dropdown that is not a short curated list. Note this is a
        different verb from the one that hangs -- `models` returns in a couple
        of seconds where `run` does not return at all.
        """
        output = probe_cli(["opencode", "models"])
        return [
            line.strip()
            for line in output.splitlines()
            if line.strip() and "/" in line
        ]


def request_settings(request: AuthoringRequest) -> dict:
    """
    The per-repo authoring settings this request carries.

    Threaded on the request rather than re-resolved here, so the driver has no
    database session and `resolve_settings` stays the only place the chain is
    walked -- the worker, the API and the driver cannot disagree about what a
    run will do.
    """
    return request.settings or {}
