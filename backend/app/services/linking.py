"""
Cross-Tool Linking
Extracts ticket keys from pull request metadata so a PR can be resolved to the
Jira/Linear tickets and Slack threads that discuss the same work.

This is the primitive the whole PR Context Agent rests on. It is deliberately
regex-based rather than semantic: ticket keys in branch names and PR titles are
a near-universal convention, cost nothing to match, and do not hallucinate.
"""

import re

# Ticket keys look like ABC-123. Two to ten uppercase letters, hyphen, digits.
TICKET_KEY_PATTERN = re.compile(r"\b([A-Z][A-Z0-9]{1,9})-(\d{1,6})\b")

# Tokens that match the shape of a ticket key but never are one. Without this
# filter, a PR titled "Fix UTF-8 handling" invents a ticket called UTF-8 and
# the agent goes looking for it.
NOT_TICKET_KEYS: frozenset[str] = frozenset({
    "UTF-8", "UTF-16", "UTF-32",
    "HTTP-2", "HTTP-3",
    "SHA-1", "SHA-256", "SHA-512",
    "MD-5",
    "BASE-64",
    "ISO-8601", "ISO-9001",
    "RFC-2119", "RFC-3339",
    "AES-256", "RSA-2048",
    "IPV-4", "IPV-6",
    "X-509",
    "ES-2015", "ES-2020",
    "PYTHON-3", "VUE-3", "ANGULAR-2",
    "CVE-2021", "CVE-2022", "CVE-2023", "CVE-2024", "CVE-2025",
})


def extract_ticket_keys(*texts: str | None) -> list[str]:
    """
    Extract candidate ticket keys from any number of text fragments.

    Pass PR title, branch name, body, and commit messages. Returns unique keys
    in first-seen order.

    Args:
        *texts: Text fragments to scan; None values are skipped.

    Returns:
        Unique uppercase ticket keys, e.g. ["LOC-431", "OPS-12"].
    """
    seen: dict[str, None] = {}

    for text in texts:
        if not text:
            continue

        # Branch names use slashes and underscores as separators
        # (feature/LOC-431-retry-fix); normalize so \b matches.
        normalized = text.replace("/", " ").replace("_", " ")

        for match in TICKET_KEY_PATTERN.finditer(normalized):
            key = f"{match.group(1)}-{match.group(2)}"
            if key.upper() in NOT_TICKET_KEYS:
                continue
            seen.setdefault(key, None)

    return list(seen)


def extract_from_pr(
    title: str | None = None,
    branch: str | None = None,
    body: str | None = None,
    commit_messages: list[str] | None = None,
) -> list[str]:
    """
    Extract ticket keys from a pull request's metadata.

    Args:
        title: PR title
        branch: Head branch name
        body: PR description
        commit_messages: Commit subjects on the branch

    Returns:
        Unique ticket keys, most-likely first (title and branch before body).
    """
    fragments: list[str | None] = [title, branch, body]
    if commit_messages:
        fragments.extend(commit_messages)

    return extract_ticket_keys(*fragments)


# GitHub PR URLs, for finding PRs referenced in Slack messages.
PR_URL_PATTERN = re.compile(
    r"https?://github\.com/([\w.-]+/[\w.-]+)/pull/(\d+)"
)


def extract_pr_references(text: str | None) -> list[tuple[str, int]]:
    """
    Find GitHub PR links in text.

    Used in reverse: given a Slack message, which PRs is it about?

    Returns:
        List of (repo, pr_number) tuples, e.g. [("acme/api", 892)].
    """
    if not text:
        return []

    seen: dict[tuple[str, int], None] = {}
    for match in PR_URL_PATTERN.finditer(text):
        seen.setdefault((match.group(1), int(match.group(2))), None)

    return list(seen)
