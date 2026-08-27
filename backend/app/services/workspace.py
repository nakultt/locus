"""
Where the code is, and where the agent is allowed to change it.

Two different questions, and conflating them is how the agent ends up editing
Locus itself.

**The source** is where your repositories already sit on disk -- cloned,
dependencies installed, build caches warm. Re-cloning per attempt throws that
away and spends the timeout on network, so Locus is told where they are.

**The workspace** is where the agent works, and it is always isolated: a
`git worktree` cut from the local repository. A worktree from a local repo is
near-instant, shares the object store, and leaves the developer's own checkout
completely untouched -- their branch, their uncommitted changes, their stashes.
That last point is not negotiable: a shared checkout can only have one branch
out at a time, and an agent running `git checkout` in the directory someone is
working in destroys their afternoon and looks like a successful run.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

# A folder holding many repos, e.g. E:\\Github. Optional -- a repo Locus has
# never seen must still work, or autonomous mode only functions on machines
# that happen to be set up correctly.
CODE_ROOT_ENV = "LOCUS_CODE_ROOT"
WORKSPACE_ROOT_ENV = "LOCUS_WORKSPACE_ROOT"
ALLOW_IN_PLACE_ENV = "LOCUS_ALLOW_IN_PLACE"
WORKSPACE_TTL_DAYS = int(os.getenv("LOCUS_WORKSPACE_TTL_DAYS") or 3)

GIT_TIMEOUT_SECONDS = 300


class WorkspaceError(RuntimeError):
    """
    A configuration problem, reported as one.

    Deliberately distinct from an authoring failure: "your LOCUS_CODE_ROOT
    points at Locus itself" and "the agent could not write this ticket" want
    completely different responses, and reporting the first as the second sends
    someone hunting through prompts.
    """


@dataclass
class Workspace:
    """One isolated checkout the agent may write to."""

    path: Path
    branch: str
    base_branch: str
    # The local repository the worktree was cut from, if there was one.
    source: Path | None
    # True when this is the source checkout itself, under LOCUS_ALLOW_IN_PLACE.
    in_place: bool = False


def run_git(
    args: list[str], cwd: Path | str, *, check: bool = True, timeout: int | None = None
) -> subprocess.CompletedProcess:
    """Run one git command, with output captured so failures can be reported."""
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout or GIT_TIMEOUT_SECONDS,
    )
    if check and result.returncode != 0:
        raise WorkspaceError(
            f"git {' '.join(args)} failed: {(result.stderr or result.stdout).strip()}"
        )
    return result


def locus_root() -> Path:
    """
    Locus's own tree -- the one holding backend/.env.

    Resolved from this file rather than from the working directory, which a
    background loop does not control.
    """
    return Path(__file__).resolve().parent.parent.parent.parent


def normalize_remote(url: str) -> str:
    """
    Reduce a git remote URL to "owner/name", lowercased.

    SSH and HTTPS forms of the same remote must compare equal, or the origin
    check below refuses every correctly-configured repo.
    """
    cleaned = (url or "").strip()
    if cleaned.endswith(".git"):
        cleaned = cleaned[:-4]
    cleaned = cleaned.rstrip("/")

    if cleaned.startswith("git@") and ":" in cleaned:
        cleaned = cleaned.split(":", 1)[1]
    else:
        for prefix in ("https://", "http://", "ssh://git@", "ssh://", "git://"):
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix):]
                break
        if "/" in cleaned and "." in cleaned.split("/")[0]:
            cleaned = cleaned.split("/", 1)[1]  # drop the host

    parts = [p for p in cleaned.split("/") if p]
    return "/".join(parts[-2:]).lower() if len(parts) >= 2 else cleaned.lower()


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except (ValueError, OSError):
        return False


def check_not_locus(path: Path) -> None:
    """
    Refuse a source path that is Locus's own tree, or contains it.

    This is the single most important rule in the whole feature, and with a
    code root it stops being hypothetical: if Locus lives at `E:\\Github\\locus`
    and someone sets `LOCUS_CODE_ROOT=E:\\Github`, then authoring the `locus`
    repo resolves to Locus's own directory -- the one holding `backend/.env`
    and `ENCRYPTION_KEY`, the value that must never change or every stored
    credential becomes permanently undecryptable.

    Compared in both directions, and it **refuses with a named error** rather
    than skipping silently. That layout is the normal one, which makes this the
    most likely misconfiguration this feature has.
    """
    root = locus_root()
    resolved = path.resolve()

    if resolved == root.resolve() or _is_within(resolved, root) or _is_within(root, resolved):
        raise WorkspaceError(
            f"Refusing to author in {resolved}: it is Locus's own tree, or "
            f"contains it ({root}). That directory holds backend/.env and "
            "ENCRYPTION_KEY, which must never change. Set source_path for this "
            "repo, or point LOCUS_CODE_ROOT somewhere that does not contain "
            "Locus itself."
        )


def check_is_git_repo(path: Path) -> None:
    """A path that is not a git repository is a configuration error."""
    if not (path / ".git").exists():
        raise WorkspaceError(
            f"{path} is not a git repository. Check source_path, or "
            f"{CODE_ROOT_ENV}."
        )


def check_origin_matches(path: Path, repo: str) -> None:
    """
    Refuse a checkout whose `origin` is not the repo being worked on.

    `<root>/<name>` is a guess based on a folder name, and `acme/api` and
    `beta/api` collapse to the same directory under a flat root. Pointing the
    agent at the wrong codebase produces a confident, entirely wrong pull
    request -- which is far worse than refusing, because it looks like success.
    """
    result = run_git(["remote", "get-url", "origin"], path, check=False)
    if result.returncode != 0:
        raise WorkspaceError(f"{path} has no origin remote to check against {repo}")

    found = normalize_remote(result.stdout)
    if found != repo.lower():
        raise WorkspaceError(
            f"{path} has origin {found}, not {repo}. A folder name is a guess; "
            "set source_path for this repo rather than relying on the layout."
        )


def resolve_source(repo: str, source_path: str | None) -> Path | None:
    """
    Find the local checkout for `owner/name`, or None to clone fresh.

    First hit wins:
      1. the repo's own `source_path`, if set
      2. `<LOCUS_CODE_ROOT>/<name>`   -- the common layout
      3. `<LOCUS_CODE_ROOT>/<owner>/<name>` -- for people who nest by org
      4. None -- no local copy; the caller clones into the workspace root

    Step 4 matters: a monorepo folder is a convenience, not a requirement, and
    a repo Locus has never seen must still work.

    An explicitly configured `source_path` that does not exist raises rather
    than falling through. Someone who named a path meant that path, and
    silently cloning a second copy elsewhere is how you end up debugging why
    your changes are not in your checkout.
    """
    owner, _, name = repo.partition("/")

    if source_path:
        explicit = Path(source_path).expanduser()
        if not explicit.exists():
            raise WorkspaceError(
                f"source_path {explicit} does not exist for {repo}"
            )
        _validate(explicit, repo)
        return explicit

    root_value = (os.getenv(CODE_ROOT_ENV) or "").strip()
    if not root_value:
        return None

    root = Path(root_value).expanduser()
    for candidate in (root / name, root / owner / name):
        if candidate.exists():
            _validate(candidate, repo)
            return candidate

    return None


def _validate(path: Path, repo: str) -> None:
    """All three checks, in the order that reports the clearest error first."""
    check_not_locus(path)
    check_is_git_repo(path)
    check_origin_matches(path, repo)


def workspace_root() -> Path:
    root = (os.getenv(WORKSPACE_ROOT_ENV) or "").strip()
    if root:
        return Path(root).expanduser()
    import tempfile

    return Path(tempfile.gettempdir()) / "locus-workspaces"


def allow_in_place() -> bool:
    """
    Whether the agent may work directly in the source checkout.

    Off by default, and what it costs is real: the agent shares a working tree
    with a human, `git checkout` becomes destructive, concurrent attempts on
    one repo become impossible, and the self-edit check is the only thing
    standing between the agent and whatever else lives in that directory.

    It exists because some repositories genuinely cannot be worktree'd --
    submodule-heavy trees, build systems with absolute paths baked in -- not as
    a convenience.
    """
    return (os.getenv(ALLOW_IN_PLACE_ENV) or "").strip() in ("1", "true", "yes")


def prune_old_workspaces(root: Path | None = None) -> int:
    """
    Delete kept-on-failure worktrees older than the TTL.

    A failed run whose tree is gone is close to undebuggable, and this plan
    expects failures -- so they are kept, and pruned on a timer rather than
    immediately.
    """
    base = (root or workspace_root()) / "work"
    if not base.exists():
        return 0

    cutoff = time.time() - WORKSPACE_TTL_DAYS * 86400
    removed = 0
    for repo_dir in base.iterdir():
        if not repo_dir.is_dir():
            continue
        for attempt_dir in repo_dir.iterdir():
            try:
                if attempt_dir.stat().st_mtime < cutoff:
                    shutil.rmtree(attempt_dir, ignore_errors=True)
                    removed += 1
            except OSError:
                continue
    return removed
