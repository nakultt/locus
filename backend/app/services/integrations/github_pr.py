"""
GitHub Pull Request Access
Direct API helpers for the PR Context Agent.

These are plain async functions rather than LangChain tools. The PR pipeline
drives them deterministically -- fetch this PR, get its diff, post this comment
-- so there is no reason to route through an LLM's tool selection.

Credentials are passed per call. Nothing is stored at module level; a
background worker and a live request must never share credential state.
"""

import logging
import re
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

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


# Public alias. Other modules calling the GitHub REST API should send the same
# headers -- including the pinned API version -- rather than assembling their
# own and drifting when it changes.
build_headers = _headers


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


async def get_default_branch(token: str, repo: str) -> str:
    """
    The repository's default branch.

    Read rather than assumed: hard-coding `main` cuts an authoring branch from
    a branch that does not exist on every repo still on `master`, and the
    failure surfaces as a confusing git error rather than a naming problem.
    Falls back to `main` when the call fails, which is the modern default and
    the only useful guess.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{GITHUB_API_BASE}/repos/{repo}", headers=_headers(token)
        )

    if response.status_code != 200:
        return "main"
    return response.json().get("default_branch") or "main"


async def request_reviewers(
    token: str,
    repo: str,
    pr_number: int | None,
    logins: list[str],
    *,
    author: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> list[str]:
    """
    Ask the named GitHub users to review a pull request.

    Returns the logins actually requested, empty when there was nothing to ask
    or the call failed. **A failure is never raised**: the pull request is
    open, which is the outcome the caller spent an attempt on, and failing an
    authoring run because a review could not be requested would hand a work
    item back over a notification.

    The author is dropped first. GitHub rejects a request naming the pull
    request's own author with a 422 covering the *whole* list, so the agent's
    own account appearing in a team's reviewer list -- which is easy to do,
    since it is a teammate everywhere else -- would silently cost everyone
    else their request too.
    """
    if not pr_number or not logins:
        return []

    wanted = [
        login for login in logins
        if not author or login.lower() != author.lower()
    ]
    if not wanted:
        return []

    async def post(http: httpx.AsyncClient) -> list[str]:
        response = await http.post(
            f"{GITHUB_API_BASE}/repos/{repo}/pulls/{pr_number}/requested_reviewers",
            headers=_headers(token),
            json={"reviewers": wanted},
        )
        if response.status_code in (200, 201):
            return wanted
        logger.warning(
            "Could not request reviewers %s on %s#%s (%s): %s",
            ", ".join(wanted), repo, pr_number, response.status_code, response.text,
        )
        return []

    try:
        if client is not None:
            return await post(client)
        async with httpx.AsyncClient(timeout=30.0) as own:
            return await post(own)
    except Exception as exc:
        logger.warning(
            "Could not request reviewers on %s#%s: %s", repo, pr_number, exc
        )
        return []


async def create_pull_request(
    token: str,
    repo: str,
    *,
    title: str,
    head: str,
    base: str,
    body: str,
    draft: bool = False,
    reviewers: list[str] | None = None,
) -> dict:
    """
    Open a pull request, resolving the two 422s that actually happen.

    GitHub returns 422 both for "a pull request already exists for this head"
    and for "no commits between base and head", and they need opposite
    handling:

    - **Already open.** The retry path hits this constantly -- a rework pushes
      to the same branch, and the pull request from the previous attempt is
      still there. Treated as success and the existing one is returned, since
      that is exactly what the caller wanted to end up with.
    - **No commits ahead.** The agent produced nothing. Reported as an error,
      because an empty pull request is worse than none: it puts a reviewer's
      name on a request to read a diff that does not exist.

    `reviewers` are requested only on the pull request this call actually
    created. The already-open path above returns somebody else's -- usually a
    previous attempt's, which a reviewer has already been asked to read and may
    already have reviewed -- and re-requesting there would re-notify them on
    every rework, which is what gets a bot muted.

    Returns:
        The pull request object on success, or `{"error": ...}`. A dict rather
        than a raise so the caller can record the attempt either way -- every
        outcome consumes an attempt, and one that raised past the recording
        would not.
    """
    payload = {
        "title": title, "head": head, "base": base, "body": body, "draft": draft
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{GITHUB_API_BASE}/repos/{repo}/pulls",
            headers=_headers(token),
            json=payload,
        )

        if response.status_code == 201:
            created = response.json()
            if reviewers:
                await request_reviewers(
                    token,
                    repo,
                    created.get("number"),
                    reviewers,
                    author=(created.get("user") or {}).get("login"),
                    client=client,
                )
            return created

        if response.status_code == 422:
            detail = ""
            try:
                errors = response.json().get("errors") or []
                detail = " ".join(str(e.get("message", "")) for e in errors)
            except Exception:
                detail = response.text

            if "no commits between" in detail.lower():
                return {"error": f"No commits between {base} and {head}"}

            # Anything else 422 on a create is almost always the existing one.
            existing = await client.get(
                f"{GITHUB_API_BASE}/repos/{repo}/pulls",
                headers=_headers(token),
                params={"head": f"{repo.split('/')[0]}:{head}", "state": "open"},
            )
            if existing.status_code == 200 and existing.json():
                return existing.json()[0]

            return {"error": f"GitHub refused the pull request (422): {detail}"}

    try:
        message = response.json().get("message", response.text)
    except Exception:
        message = response.text
    return {"error": f"GitHub refused the pull request ({response.status_code}): {message}"}


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


async def get_pr_commit_authors(token: str, repo: str, pr_number: int) -> list[str]:
    """
    The author email of every commit on a pull request.

    Separate from `get_pr_commits`, which returns subject lines for ticket-key
    extraction. The email is what distinguishes a previous authoring attempt
    from a person taking the branch over, and the two questions want different
    fields off the same payload.

    The committer object is explicitly null on commits GitHub cannot match to
    an account, so the email is read from the commit itself rather than from
    the linked user -- `.get(key, default)` does not save you when the key is
    present and the value is None.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{GITHUB_API_BASE}/repos/{repo}/pulls/{pr_number}/commits",
            headers=_headers(token),
            params={"per_page": 100},
        )
        response.raise_for_status()
        commits = response.json()

    authors = []
    for entry in commits:
        commit = entry.get("commit") or {}
        author = commit.get("author") or {}
        email = author.get("email")
        if email:
            authors.append(email)
    return authors


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


# ============== Inline review comments ==============

# Marks a Locus inline comment, the same way COMMENT_MARKER marks the summary.
# Inline comments cannot be edited in place across pushes -- the line they were
# anchored to may not exist any more -- so this is used to find and remove the
# previous round's before posting the current one.
INLINE_MARKER = "<!-- locus-inline -->"


async def get_diff_line_positions(
    token: str, repo: str, pr_number: int
) -> dict[str, set[int]]:
    """
    Which lines of which files this PR's diff actually touches.

    An inline comment can only be anchored to a line that appears in the diff;
    GitHub rejects anything else with a 422. A finding may well point at a line
    the diff does not include -- the scanner reads whole reconstructed files,
    not the diff -- so the caller checks against this before trying to post one.

    Returns:
        Mapping of file path -> set of line numbers in the *head* revision that
        can carry a comment. Only added and context lines qualify; a deleted
        line has no line number on the right-hand side to attach to.
    """
    diff_text = await get_pr_diff(token, repo, pr_number)

    commentable: dict[str, set[int]] = {}
    current_file: str | None = None
    new_line = 0

    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            current_file = line[6:].strip()
            commentable.setdefault(current_file, set())
            continue
        if line.startswith("@@"):
            # "@@ -a,b +c,d @@" -- c is where the new-side hunk starts.
            try:
                new_span = line.split("+", 1)[1].split(maxsplit=1)[0]
                new_line = int(new_span.split(",")[0])
            except (IndexError, ValueError):
                new_line = 0
            continue
        if current_file is None or new_line <= 0:
            continue

        if line.startswith("+"):
            commentable[current_file].add(new_line)
            new_line += 1
        elif line.startswith("-"):
            # Deleted: exists only on the left, so nothing to anchor to.
            continue
        elif line.startswith(" "):
            commentable[current_file].add(new_line)
            new_line += 1

    return commentable


async def clear_inline_comments(token: str, repo: str, pr_number: int) -> int:
    """
    Delete the inline comments Locus left on a previous run.

    Unlike the summary comment these cannot be edited in place: an inline
    comment is bound to a line in a particular commit, and after a push that
    line may have moved or gone. Leaving them would stack a fresh set on top of
    every stale one, which is precisely the noise the summary marker exists to
    prevent.

    Failures are swallowed per comment: a stale comment left behind is untidy,
    but failing the run over it would cost the analysis.

    Returns:
        How many were deleted.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(
                f"{GITHUB_API_BASE}/repos/{repo}/pulls/{pr_number}/comments",
                headers=_headers(token),
                params={"per_page": 100},
            )
            response.raise_for_status()
            comments = response.json()
        except Exception:
            return 0

        removed = 0
        for comment in comments:
            if INLINE_MARKER not in (comment.get("body") or ""):
                continue
            try:
                deleted = await client.delete(
                    f"{GITHUB_API_BASE}/repos/{repo}/pulls/comments/{comment['id']}",
                    headers=_headers(token),
                )
                if deleted.status_code in (200, 204):
                    removed += 1
            except Exception:
                continue

    return removed


async def post_inline_comments(
    token: str,
    repo: str,
    pr_number: int,
    head_sha: str,
    comments: list[dict],
) -> tuple[int, list[str]]:
    """
    Post review comments anchored to specific lines of the diff.

    This is the only place a ```suggestion block does anything useful: GitHub
    renders the Apply button on an inline review comment, and renders the same
    fence as an ordinary code block in the issue-style summary comment.

    Posted individually rather than as one review. A single review request is
    rejected in full if any one of its comments has a bad anchor, which would
    lose every good suggestion alongside the bad one; posting one at a time
    means a rejected anchor costs only its own comment.

    Args:
        comments: dicts of {path, line, body}, already checked against
            `get_diff_line_positions`.

    Returns:
        (how many posted, non-fatal error notes)
    """
    posted = 0
    notes: list[str] = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        for comment in comments:
            payload = {
                "body": f"{INLINE_MARKER}\n{comment['body']}",
                "commit_id": head_sha,
                "path": comment["path"],
                "line": comment["line"],
                "side": "RIGHT",
            }
            # A suggestion spanning several lines has to declare where it
            # starts, or GitHub anchors it to the last line only and applying
            # it drops the rest of the range.
            if comment.get("start_line") is not None:
                payload["start_line"] = comment["start_line"]
                payload["start_side"] = "RIGHT"
            try:
                response = await client.post(
                    f"{GITHUB_API_BASE}/repos/{repo}/pulls/{pr_number}/comments",
                    headers=_headers(token),
                    json=payload,
                )
            except Exception as e:
                notes.append(f"inline comment on {comment['path']} failed: {e}")
                continue

            if response.status_code in (200, 201):
                posted += 1
            else:
                # 422 is the common one: the line is not in the diff after all.
                notes.append(
                    f"inline comment on {comment['path']}:{comment['line']} "
                    f"rejected ({response.status_code})"
                )

    return posted, notes
