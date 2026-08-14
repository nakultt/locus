"""
GitHub Pull Request Access
Direct API helpers for the PR Context Agent.

These are plain async functions rather than LangChain tools. The PR pipeline
drives them deterministically -- fetch this PR, get its diff, post this comment
-- so there is no reason to route through an LLM's tool selection.

Credentials are passed per call. Nothing is stored at module level; a
background worker and a live request must never share credential state.
"""

import re
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


async def get_combined_ci_state(token: str, repo: str, head_sha: str) -> tuple[str, list[str]]:
    """
    Whether CI is green on a commit, across both systems GitHub offers.

    GitHub reports CI two ways and a repo can use either or both: the older
    commit *statuses* API, and the newer *check runs*. A repo whose CI posts
    check runs reports "pending" with zero statuses on the statuses endpoint
    forever, so reading only that would either block every merge or, if
    treated as success, wave through a red build.

    Returns:
        (state, failing) where state is "success", "failure", or "pending".
        A commit with no CI configured at all is "success" -- absent CI is not
        failing CI, and refusing to merge would make the feature unusable on
        repos that have none.
    """
    failing: list[str] = []
    saw_any = False
    pending = False

    async with httpx.AsyncClient(timeout=30.0) as client:
        statuses = await client.get(
            f"{GITHUB_API_BASE}/repos/{repo}/commits/{head_sha}/status",
            headers=_headers(token),
        )
        if statuses.status_code == 200:
            body = statuses.json()
            # total_count of 0 means "no statuses posted", which arrives as
            # state "pending" -- not a real pending build.
            if body.get("total_count", 0) > 0:
                saw_any = True
                for status in body.get("statuses") or []:
                    state = status.get("state")
                    if state == "failure" or state == "error":
                        failing.append(status.get("context") or "status")
                    elif state == "pending":
                        pending = True

        checks = await client.get(
            f"{GITHUB_API_BASE}/repos/{repo}/commits/{head_sha}/check-runs",
            headers=_headers(token),
        )
        if checks.status_code == 200:
            runs = checks.json().get("check_runs") or []
            if runs:
                saw_any = True
            for run in runs:
                if run.get("status") != "completed":
                    pending = True
                    continue
                conclusion = run.get("conclusion")
                # "neutral", "skipped", and "success" all pass. "cancelled"
                # is not a failure of the code, but it is not a pass either,
                # so it holds rather than merges.
                if conclusion in ("failure", "timed_out", "action_required"):
                    failing.append(run.get("name") or "check")
                elif conclusion == "cancelled":
                    pending = True

    if failing:
        return "failure", failing
    if pending:
        return "pending", []
    return "success", [] if saw_any else []


async def compare_commits(
    token: str, repo: str, base_sha: str, head_sha: str
) -> list[dict]:
    """
    Files changed between two commits.

    Used to answer "what happened since you last looked" for a reviewer, which
    is the difference between re-reading a whole diff and checking two things.

    Returns an empty list rather than raising when the compare fails: a
    resubmission notice with no delta is still useful, one that never sends
    because a compare 404'd is not.
    """
    if not base_sha or not head_sha or base_sha == head_sha:
        return []

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{GITHUB_API_BASE}/repos/{repo}/compare/{base_sha}...{head_sha}",
                headers=_headers(token),
            )
        if response.status_code != 200:
            return []
        files = response.json().get("files") or []
    except Exception:
        return []

    return [
        {
            "filename": f.get("filename", ""),
            "additions": f.get("additions", 0),
            "deletions": f.get("deletions", 0),
        }
        for f in files
    ]


async def merge_pull_request(
    token: str,
    repo: str,
    pr_number: int,
    merge_method: str = "squash",
    commit_title: str | None = None,
) -> tuple[bool, str]:
    """
    Merge a pull request.

    Returns:
        (merged, detail). A 405 means GitHub itself refused -- branch
        protection unsatisfied, or the PR is not mergeable -- and a 409 means
        the head moved since we checked. Both are reported rather than
        retried: something changed, and re-deciding is the caller's job.
    """
    payload: dict = {"merge_method": merge_method}
    if commit_title:
        payload["commit_title"] = commit_title

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.put(
            f"{GITHUB_API_BASE}/repos/{repo}/pulls/{pr_number}/merge",
            headers=_headers(token),
            json=payload,
        )

    if response.status_code == 200:
        return True, response.json().get("message", "Merged")

    try:
        detail = response.json().get("message", response.text)
    except Exception:
        detail = response.text

    return False, f"GitHub refused the merge ({response.status_code}): {detail}"


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


GITHUB_GRAPHQL = "https://api.github.com/graphql"

# GitHub resolves "Closes #12" / "Fixes #12" into a real link. REST does not
# expose that edge, so the linked-issue set only comes from GraphQL.
_LINKED_ISSUES_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      closingIssuesReferences(first: 10) {
        nodes { number title state url body author { login } }
      }
    }
  }
}
"""

# Bare "#12" mentions anywhere in the PR body. These are references rather than
# closing links, so they are fetched separately and marked as such.
ISSUE_REF_PATTERN = re.compile(r"(?:^|\s)#(\d{1,6})\b")


async def get_linked_issues(token: str, repo: str, pr_number: int) -> list[dict]:
    """
    Issues this PR closes, per GitHub's own link graph.

    Uses GraphQL because `closingIssuesReferences` has no REST equivalent --
    REST would force us to re-parse the body and guess.

    Returns:
        Issue dicts; empty on any failure, since context is best-effort.
    """
    owner, name = repo.split("/", 1)

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            GITHUB_GRAPHQL,
            headers=_headers(token),
            json={
                "query": _LINKED_ISSUES_QUERY,
                "variables": {"owner": owner, "name": name, "number": pr_number},
            },
        )
        if response.status_code != 200:
            return []

        payload = response.json()

    try:
        nodes = (
            payload["data"]["repository"]["pullRequest"]
            ["closingIssuesReferences"]["nodes"]
        )
    except (KeyError, TypeError):
        return []

    return [
        {
            "number": n.get("number"),
            "title": n.get("title", ""),
            "state": (n.get("state") or "").lower(),
            "url": n.get("url", ""),
            "body": (n.get("body") or "")[:2000],
            "author": (n.get("author") or {}).get("login", ""),
            "relation": "closes",
        }
        for n in nodes
        if n
    ]


async def get_referenced_issues(
    token: str, repo: str, body: str | None, exclude: set[int]
) -> list[dict]:
    """
    Issues mentioned as "#N" in the PR body but not formally linked.

    Args:
        exclude: Issue numbers already returned as closing links.
    """
    if not body:
        return []

    numbers = {
        int(m) for m in ISSUE_REF_PATTERN.findall(body)
    } - exclude

    issues: list[dict] = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        for number in sorted(numbers)[:5]:
            try:
                response = await client.get(
                    f"{GITHUB_API_BASE}/repos/{repo}/issues/{number}",
                    headers=_headers(token),
                )
                if response.status_code != 200:
                    continue
                data = response.json()

                # This endpoint also returns PRs; only issues are wanted here.
                if "pull_request" in data:
                    continue

                issues.append({
                    "number": data.get("number"),
                    "title": data.get("title", ""),
                    "state": data.get("state", ""),
                    "url": data.get("html_url", ""),
                    "body": (data.get("body") or "")[:2000],
                    "author": (data.get("user") or {}).get("login", ""),
                    "relation": "mentions",
                })
            except Exception:
                continue

    return issues


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
