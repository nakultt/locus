"""
Search term construction for cross-tool context lookup.

Naive searching gives poor results: Slack tokenizes on punctuation, so an
unquoted `LOC-431` matches messages containing "loc" or "431" anywhere, and a
PR titled "Fix payment webhook timeouts" searched verbatim matches almost
nothing. This module builds ranked, quoted queries instead.
"""

import re

# Words that carry no signal in a PR title. Searching for "fix" returns every
# message anyone ever sent.
STOPWORDS: frozenset[str] = frozenset({
    "a", "an", "the", "and", "or", "but", "if", "then", "for", "to", "of",
    "in", "on", "at", "by", "with", "from", "into", "onto", "up", "down",
    "is", "are", "was", "were", "be", "been", "being", "do", "does", "did",
    "this", "that", "these", "those", "it", "its",
    # Conventional-commit and PR-title noise
    "fix", "fixes", "fixed", "bug", "bugfix", "hotfix", "patch",
    "add", "adds", "added", "update", "updates", "updated", "change",
    "changes", "changed", "remove", "removes", "removed", "refactor",
    "chore", "feat", "feature", "test", "tests", "docs", "doc", "wip",
    "merge", "revert", "bump", "cleanup", "improve", "improves",
})

# Conventional-commit prefix: "feat(api): ..." -> drop "feat(api):"
_CONVENTIONAL_PREFIX = re.compile(r"^\s*\w+(\([^)]*\))?\s*:\s*")

# Branch decoration: "feature/", "bugfix/", trailing "-1234"
_BRANCH_PREFIX = re.compile(r"^(feature|feat|bugfix|fix|hotfix|chore|release|docs)/", re.I)

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_]{2,}")


def significant_words(text: str | None, limit: int = 4) -> list[str]:
    """
    Pull the distinctive words out of a title or branch name.

    "Fix payment webhook timeouts" -> ["payment", "webhook", "timeouts"]
    Order is preserved: earlier words in a title are usually the subject.
    """
    if not text:
        return []

    cleaned = _CONVENTIONAL_PREFIX.sub("", text)
    cleaned = _BRANCH_PREFIX.sub("", cleaned)
    cleaned = cleaned.replace("-", " ").replace("_", " ").replace("/", " ")

    seen: dict[str, None] = {}
    for match in _WORD.finditer(cleaned):
        word = match.group(0).lower()
        if word in STOPWORDS or word.isdigit():
            continue
        seen.setdefault(word, None)

    return list(seen)[:limit]


def slack_queries(
    ticket_keys: list[str],
    repo: str,
    pr_number: int,
    title: str | None = None,
    branch: str | None = None,
    issue_numbers: list[int] | None = None,
) -> list[str]:
    """
    Build Slack search queries, most precise first.

    Ticket keys and URLs are quoted so Slack treats them as phrases; unquoted,
    `LOC-431` is tokenized and matches "loc" or "431" independently, which
    returns noise.

    Returns:
        Deduplicated queries ordered precise -> broad.
    """
    queries: list[str] = []

    # Exact identifiers.
    queries.extend(f'"{key}"' for key in ticket_keys)

    # The PR itself, however it was shared.
    queries.append(f'"github.com/{repo}/pull/{pr_number}"')

    short_repo = repo.split("/")[-1]
    queries.append(f'"{short_repo}#{pr_number}"')

    # Linked issues.
    for number in (issue_numbers or [])[:3]:
        queries.append(f'"{short_repo}#{number}"')

    # Topic fallback: the distinctive words together, so all must appear.
    # Only worth issuing when the title yields at least two real terms --
    # a single common word returns noise.
    words = significant_words(title) or significant_words(branch)
    if len(words) >= 2:
        queries.append(" ".join(words[:3]))

    deduped: dict[str, None] = {}
    for q in queries:
        deduped.setdefault(q, None)
    return list(deduped)


def jira_jql(
    ticket_keys: list[str],
    title: str | None = None,
    branch: str | None = None,
    project_hint: str | None = None,
) -> str | None:
    """
    Build a JQL query for tickets related to a PR when no key was found.

    Direct key lookup is handled separately and is always preferred; this is
    the fallback that finds a ticket the PR forgot to reference.

    Returns:
        A JQL string, or None when there is nothing worth searching for.
    """
    words = significant_words(title) or significant_words(branch)
    if len(words) < 2:
        return None

    # `text ~` searches summary, description and comments. Quote each term so
    # JQL treats it literally.
    terms = " AND ".join(f'text ~ "{w}"' for w in words[:3])

    clauses = [f"({terms})"]
    if project_hint:
        clauses.append(f'project = "{project_hint}"')
    if ticket_keys:
        # Exclude keys already fetched directly.
        keys = ", ".join(f'"{k}"' for k in ticket_keys)
        clauses.append(f"key NOT IN ({keys})")

    return " AND ".join(clauses) + " ORDER BY updated DESC"
