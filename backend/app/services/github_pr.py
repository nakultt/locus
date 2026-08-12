"""
GitHub Pull Request Access
Direct API helpers for the PR Context Agent.

These are plain async functions rather than LangChain tools. The PR pipeline
drives them deterministically -- fetch this PR, get its diff, post this comment
-- so there is no reason to route through an LLM's tool selection.

Credentials are passed per call. Nothing is stored at module level; a
background worker and a live request must never share credential state.
"""

from pathlib import Path

import httpx

GITHUB_API_BASE = "https://api.github.com"

# Diffs beyond this go to the LLM truncated. A 20k-line refactor would blow the
# context window and cost more than the review is worth.
MAX_DIFF_CHARS = 60_000


def _headers(token: str, accept: str = "application/vnd.github+json") -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": accept,
        "X-GitHub-Api-Version": "2022-11-28",
    }


async def get_pull_request(token: str, repo: str, pr_number: int) -> dict:
    """
    Fetch pull request metadata.

    Args:
        token: GitHub token
        repo: "owner/name"
        pr_number: PR number

    Returns:
        The PR object from the GitHub API.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{GITHUB_API_BASE}/repos/{repo}/pulls/{pr_number}",
            headers=_headers(token),
        )
        response.raise_for_status()
        return response.json()


async def get_pr_diff(token: str, repo: str, pr_number: int) -> str:
    """
    Fetch the unified diff for a pull request.

    Uses the `.diff` media type, which returns raw text rather than JSON.
    Truncated at MAX_DIFF_CHARS.
    """
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.get(
            f"{GITHUB_API_BASE}/repos/{repo}/pulls/{pr_number}",
            headers=_headers(token, accept="application/vnd.github.v3.diff"),
        )
        response.raise_for_status()
        diff = response.text

    if len(diff) > MAX_DIFF_CHARS:
        return diff[:MAX_DIFF_CHARS] + "\n\n[diff truncated]"
    return diff


async def get_pr_files(token: str, repo: str, pr_number: int) -> list[dict]:
    """
    List files changed in a pull request, with per-file patches.

    Paginates; GitHub caps this endpoint at 3000 files.
    """
    files: list[dict] = []
    page = 1

    async with httpx.AsyncClient(timeout=60.0) as client:
        while True:
            response = await client.get(
                f"{GITHUB_API_BASE}/repos/{repo}/pulls/{pr_number}/files",
                headers=_headers(token),
                params={"per_page": 100, "page": page},
            )
            response.raise_for_status()
            batch = response.json()

            if not batch:
                break

            files.extend(batch)
            if len(batch) < 100:
                break
            page += 1

    return files


# Skip files above this size; a scanner gains nothing from a minified bundle
# or a checked-in fixture, and they dominate the time budget.
MAX_FILE_BYTES = 400_000

# Extensions Semgrep has rules for. Scanning images or lockfiles wastes time.
SCANNABLE_SUFFIXES = frozenset({
    ".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".java", ".rb", ".php",
    ".c", ".cpp", ".h", ".hpp", ".cs", ".rs", ".kt", ".scala", ".swift",
    ".sh", ".bash", ".yaml", ".yml", ".tf", ".sql",
})


async def get_changed_file_contents(
    token: str, repo: str, pr_number: int, ref: str
) -> tuple[dict[str, str], list[str]]:
    """
    Fetch the post-change contents of scannable files in a PR.

    Semgrep matches against a parsed AST, so it needs real source files -- handing
    it a unified diff yields nothing at all. This reconstructs what the code looks
    like after the PR.

    Args:
        ref: Head SHA or branch to read files at.

    Returns:
        (path -> content, notes about anything skipped)
    """
    files = await get_pr_files(token, repo, pr_number)
    contents: dict[str, str] = {}
    notes: list[str] = []

    async with httpx.AsyncClient(timeout=60.0) as client:
        for entry in files:
            path = entry.get("filename", "")
            if entry.get("status") == "removed":
                continue
            if Path(path).suffix.lower() not in SCANNABLE_SUFFIXES:
                continue

            try:
                response = await client.get(
                    f"{GITHUB_API_BASE}/repos/{repo}/contents/{path}",
                    headers=_headers(token, accept="application/vnd.github.raw"),
                    params={"ref": ref},
                )
                if response.status_code != 200:
                    continue

                raw = response.content
                if len(raw) > MAX_FILE_BYTES:
                    notes.append(f"skipped {path} (too large)")
                    continue

                contents[path] = raw.decode("utf-8", errors="replace")
            except Exception:
                # One unreadable file must not abort the scan.
                continue

    return contents, notes


async def get_pr_commits(token: str, repo: str, pr_number: int) -> list[str]:
    """Return commit subject lines for a PR (used for ticket-key extraction)."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{GITHUB_API_BASE}/repos/{repo}/pulls/{pr_number}/commits",
            headers=_headers(token),
            params={"per_page": 100},
        )
        response.raise_for_status()
        commits = response.json()

    return [
        c.get("commit", {}).get("message", "").split("\n")[0]
        for c in commits
    ]


# ============== Comment posting (idempotent) ==============

# Every comment Locus posts carries this marker. On the next push we find our
# own previous comment and edit it, instead of appending a new one. Without
# this, an actively developed PR collects a bot comment per push.
COMMENT_MARKER = "<!-- locus-pr-agent -->"


async def find_existing_comment(token: str, repo: str, pr_number: int) -> int | None:
    """
    Find a prior Locus comment on this PR.

    Returns:
        Comment id, or None if this is the first run.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{GITHUB_API_BASE}/repos/{repo}/issues/{pr_number}/comments",
            headers=_headers(token),
            params={"per_page": 100},
        )
        response.raise_for_status()
        comments = response.json()

    for comment in comments:
        if COMMENT_MARKER in comment.get("body", ""):
            return comment["id"]
    return None


async def upsert_pr_comment(token: str, repo: str, pr_number: int, body: str) -> dict:
    """
    Post a comment, or update the one we posted previously.

    The marker is prepended automatically.
    """
    marked_body = f"{COMMENT_MARKER}\n{body}"
    existing_id = await find_existing_comment(token, repo, pr_number)

    async with httpx.AsyncClient(timeout=30.0) as client:
        if existing_id is not None:
            response = await client.patch(
                f"{GITHUB_API_BASE}/repos/{repo}/issues/comments/{existing_id}",
                headers=_headers(token),
                json={"body": marked_body},
            )
        else:
            response = await client.post(
                f"{GITHUB_API_BASE}/repos/{repo}/issues/{pr_number}/comments",
                headers=_headers(token),
                json={"body": marked_body},
            )
        response.raise_for_status()
        return response.json()
