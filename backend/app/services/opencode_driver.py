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
import shlex
import shutil
import subprocess
import time
from pathlib import Path

from app.services import github_pr
from app.services.authoring import AuthoringRequest, AuthoringResult, context_mode
from app.services.workspace import (
    Workspace,
    WorkspaceError,
    allow_in_place,
    prune_old_workspaces,
    resolve_source,
    run_git,
    workspace_root,
)

logger = logging.getLogger(__name__)

# The command is a **template, not hard-coded flags**. OpenCode's CLI surface
# moves, and a driver that pins today's flags breaks on an upgrade with a
# non-zero exit and no useful message. Pin the exact invocation against the
# installed version at integration time and record it in the README.
DEFAULT_COMMAND = "opencode run --prompt-file {prompt} --cwd {workspace}"

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
    run_git(["fetch", "origin", "--prune"], source, check=False)
    base = base_branch or _default_branch(source)
    branch = existing_branch or f"locus/{_slug(ticket_key)}-{attempt}"

    if _branch_exists(source, branch):
        run_git(["worktree", "add", str(target), branch], source)
    else:
        start = f"origin/{base}" if _branch_exists(source, f"origin/{base}") else base
        run_git(["worktree", "add", "-b", branch, str(target), start], source)

    return Workspace(path=target, branch=branch, base_branch=base, source=source)


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


def human_commits_on(workspace: Workspace, base_branch: str, branch: str) -> bool:
    """
    Whether a person has committed to this branch.

    The rule from 4.2 and 5.1, and the worst thing the agent can do quietly is
    overwrite somebody's work. A branch carrying a previous attempt's commits
    is continued; one carrying anyone else's is handed back.
    """
    authors = branch_commit_authors(workspace, base_branch, branch)
    return any(author.lower() != AGENT_EMAIL.lower() for author in authors)


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


def build_prompt(request: AuthoringRequest) -> str:
    """
    The brief, as a file.

    Written to a file rather than passed as an argument: a context brief runs
    to thousands of characters and will exceed command-line limits on Windows.

    Order matters. The ticket first, then the accumulated context, then every
    reviewer ask oldest first -- a request satisfied in round two is still
    something this rework must not undo -- then the QA rejection when this
    follows a failure, then the scope rules.
    """
    parts = [
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

    if request.asks:
        parts += [
            "",
            "## What reviewers have asked for, oldest first",
            "",
            "Every one of these still applies. A request satisfied in an "
            "earlier round must not be undone by this one.",
            "",
        ]
        parts += [f"{n}. {ask}" for n, ask in enumerate(request.asks, start=1)]

    if request.rejection:
        parts += [
            "",
            "## Why the last attempt came back from testing",
            "",
            "In the tester's own words:",
            "",
            "> " + request.rejection.strip().replace("\n", "\n> "),
        ]

    parts += ["", SCOPE_INSTRUCTIONS]
    return "\n".join(parts)


def build_command(prompt_path: Path, workspace_path: Path) -> list[str]:
    """
    The OpenCode invocation, from the configured template.

    A template rather than hard-coded flags, because OpenCode's CLI surface
    moves and a driver pinning today's flags breaks on an upgrade with a
    non-zero exit and no useful message.
    """
    template = (os.getenv("LOCUS_OPENCODE_CMD") or DEFAULT_COMMAND).strip()
    rendered = template.format(prompt=str(prompt_path), workspace=str(workspace_path))
    parts = shlex.split(rendered, posix=os.name != "nt")

    # The model is OpenCode's, not Locus's. This exists only to pin one when a
    # team wants reproducibility across attempts, and is unset by default.
    model = (os.getenv("LOCUS_OPENCODE_MODEL") or "").strip()
    if model and "--model" not in parts:
        parts += ["--model", model]

    return parts


async def run_agent(
    command: list[str], workspace: Path, timeout: int = TIMEOUT_SECONDS
) -> tuple[int, str]:
    """
    Run the agent under a wall clock, returning (returncode, output).

    The timeout kills the subprocess and is reported as a timed-out attempt --
    which consumes an attempt like every other failure, or a ticket that
    reliably hangs retries forever and the bound protects nothing.
    """
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(workspace),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError:
        process.kill()
        await process.wait()
        return 124, f"Timed out after {timeout}s"

    return process.returncode or 0, (stdout or b"").decode("utf-8", "replace")


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
    else:
        lines += ["The configured test command passed in the agent's worktree.", ""]

    if doc_url:
        lines += [f"[Full analysis and history]({doc_url})", ""]

    return "\n".join(lines).strip()


class OpenCodeDriver:
    """
    Drives OpenCode in an isolated worktree and opens the pull request.

    Every refusal happens on the diff after the run, never by trusting the
    prompt. Every outcome returns an `AuthoringResult` rather than raising:
    the caller records the attempt either way, and an exception escaping past
    the recording would not consume an attempt.
    """

    name = "opencode"

    async def author(
        self, request: AuthoringRequest, integration_configs: dict
    ) -> AuthoringResult:
        started = time.monotonic()
        model = (os.getenv("LOCUS_OPENCODE_MODEL") or "").strip() or "opencode-default"

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

        token = (integration_configs.get("github") or {}).get("token")
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

            prompt_path = workspace.path / ".locus-prompt.md"
            prompt_path.write_text(build_prompt(request), encoding="utf-8")

            code, output = await run_agent(
                build_command(prompt_path, workspace.path), workspace.path
            )
            prompt_path.unlink(missing_ok=True)

            if code == 124:
                return failed(output, workspace_path=str(workspace.path))
            if code != 0:
                return failed(
                    f"{self.name} exited {code}:\n{output[-3000:]}",
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

            if files > MAX_CHANGED_FILES or lines > MAX_CHANGED_LINES:
                # Reviewer attention is the scarce resource this mode spends. A
                # 4,000-line agent-authored diff is not reviewable, and this is
                # not retried with a smaller scope: the ticket was too big for
                # the mode, which is information the human should get.
                return failed(
                    f"The change is too large to review: {files} files and "
                    f"{lines} lines, over the {MAX_CHANGED_FILES}-file / "
                    f"{MAX_CHANGED_LINES}-line cap.",
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
                    "-c", f"user.email={AGENT_EMAIL}",
                    "-c", f"user.name={AGENT_NAME}",
                    "commit", "-m",
                    f"{request.ticket_key}: {request.title}",
                ],
                workspace.path,
                check=False,
            )
            if commit.returncode != 0 and "nothing to commit" not in commit.stdout.lower():
                return failed(
                    f"Could not commit the agent's work: {commit.stderr or commit.stdout}",
                    workspace_path=str(workspace.path),
                )

            push = run_git(
                ["push", "-u", "origin", workspace.branch], workspace.path, check=False
            )
            if push.returncode != 0:
                # The branch moved under us. Recorded; the next attempt
                # re-fetches rather than force-pushing over whatever landed.
                return failed(
                    f"Push rejected: {(push.stderr or push.stdout).strip()}",
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


def request_settings(request: AuthoringRequest) -> dict:
    """
    The per-repo authoring settings this request carries.

    Threaded on the request rather than re-resolved here, so the driver has no
    database session and `resolve_settings` stays the only place the chain is
    walked -- the worker, the API and the driver cannot disagree about what a
    run will do.
    """
    return request.settings or {}
