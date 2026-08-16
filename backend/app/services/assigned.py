"""
What is assigned to the user, from the systems that hold the assignment.

The PR agent's dashboard has always started at a pull request, but the loop it
automates starts earlier: a ticket lands on someone, and only then does code
get written. A ticket assigned but not yet started is invisible to every
per-PR view, which is exactly the work someone most needs reminding of.

Identity is derived from the stored credentials rather than configured. The
token *is* the identity -- GitHub's `filter=assigned` and Jira's
`currentUser()` both resolve against whoever the credential belongs to -- so
there is nothing for a user to set up, and nothing that can drift out of sync
with the account actually connected.

Each source degrades on its own. A Jira outage must leave the GitHub half
rendering: a board that blanks because one of two integrations is down is
worse than a board that says so and shows the rest.
"""

import logging
from datetime import datetime

import httpx

from app import schemas
from app.services.github_pr import GITHUB_API_BASE, build_headers

logger = logging.getLogger(__name__)

# Enough to fill a board without paginating. Someone with more than this
# assigned has a prioritisation problem the dashboard cannot solve.
MAX_ITEMS = 50

# Jira deprecated /rest/api/3/search in favour of /rest/api/3/search/jql. Try
# the current one and fall back, so this keeps working on both Cloud instances
# that have migrated and those that have not.
JIRA_SEARCH_PATHS = ("/rest/api/3/search/jql", "/rest/api/3/search")

JIRA_ASSIGNED_JQL = (
    "assignee = currentUser() AND statusCategory != Done ORDER BY updated DESC"
)

JIRA_FIELDS = "summary,status,assignee,updated,priority,issuetype,description"


def _parse_stamp(raw: str | None) -> datetime | None:
    """Parse an ISO timestamp, tolerating the trailing Z GitHub sends."""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


async def github_assigned(token: str) -> list[schemas.AssignedItem]:
    """
    Every open GitHub issue assigned to the token's owner.

    Uses the cross-repo `/issues` endpoint rather than walking registered
    repositories: an issue assigned in a repo nobody registered is still
    assigned, and enumerating repos would both miss those and cost a request
    each.

    Returns an empty list rather than raising -- see the module docstring.
    """
    if not token:
        return []

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{GITHUB_API_BASE}/issues",
                headers=build_headers(token),
                params={
                    "filter": "assigned",
                    "state": "open",
                    "per_page": MAX_ITEMS,
                    "sort": "updated",
                },
            )
            if response.status_code != 200:
                logger.debug("GitHub assigned issues returned %s", response.status_code)
                return []
            rows = response.json()
    except Exception as e:
        logger.debug("GitHub assigned issues failed: %s", e)
        return []

    if not isinstance(rows, list):
        return []

    items: list[schemas.AssignedItem] = []
    for row in rows:
        try:
            # That endpoint returns pull requests alongside issues; a PR is not
            # an assignment of work to start, it is work already underway, and
            # it arrives on the card through the review rows instead.
            if row.get("pull_request"):
                continue

            # `repository` is optional on this endpoint and explicitly null in
            # some responses -- .get with a default does not save you here.
            repository = row.get("repository") or {}
            repo = repository.get("full_name")
            number = row.get("number")
            if not repo or number is None:
                continue

            assignee = row.get("assignee") or {}

            items.append(schemas.AssignedItem(
                source=schemas.TaskSource.github,
                key=f"{repo}#{number}",
                title=row.get("title") or f"Issue #{number}",
                url=row.get("html_url") or "",
                state=row.get("state"),
                status=row.get("state"),
                assignee=assignee.get("login"),
                repo=repo,
                number=number,
                body=row.get("body"),
                updated_at=_parse_stamp(row.get("updated_at")),
            ))
        except Exception:
            # One malformed row must not cost the whole list.
            continue

    return items


def _jira_credentials(jira_config: dict) -> tuple[str, str, str] | None:
    """
    Pull (token, email, base_url) out of a stored Jira config.

    The shape is asymmetric and easy to get backwards: the API token lives in
    `api_key`, while the site URL and account email live under `credentials`.
    """
    api_token = jira_config.get("api_key", "")
    credentials = jira_config.get("credentials", {}) or {}
    email = credentials.get("email", "")
    base_url = (credentials.get("url", "") or "").rstrip("/")

    if not (api_token and email and base_url):
        return None
    return api_token, email, base_url


def jira_text(field: object) -> str | None:
    """
    Flatten a Jira description into plain text.

    Jira Cloud returns Atlassian Document Format -- nested nodes rather than a
    string. Only the text leaves matter here; the card shows a body, not a
    rendered document.
    """
    if isinstance(field, str):
        return field
    if not isinstance(field, dict):
        return None

    parts: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            if node.get("type") == "text" and isinstance(node.get("text"), str):
                parts.append(node["text"])
            for child in node.get("content") or []:
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(field)
    return " ".join(parts).strip() or None


async def jira_assigned(jira_config: dict) -> list[schemas.AssignedItem]:
    """
    Every open Jira ticket assigned to the credential's owner.

    `currentUser()` resolves against the account the API token belongs to, so
    this needs no configured account id and cannot drift from the connected
    integration.
    """
    resolved = _jira_credentials(jira_config)
    if resolved is None:
        return []
    api_token, email, base_url = resolved

    issues: list[dict] = []
    try:
        async with httpx.AsyncClient(timeout=30.0, auth=(email, api_token)) as client:
            for path in JIRA_SEARCH_PATHS:
                response = await client.get(
                    f"{base_url}{path}",
                    params={
                        "jql": JIRA_ASSIGNED_JQL,
                        "maxResults": MAX_ITEMS,
                        "fields": JIRA_FIELDS,
                    },
                    headers={"Accept": "application/json"},
                )
                if response.status_code == 200:
                    issues = response.json().get("issues", []) or []
                    break
                # 404/410 means this instance does not serve that path; any
                # other status is a real failure and retrying the deprecated
                # endpoint would not help.
                if response.status_code not in (404, 410):
                    logger.debug("Jira assigned search returned %s", response.status_code)
                    return []
    except Exception as e:
        logger.debug("Jira assigned search failed: %s", e)
        return []

    items: list[schemas.AssignedItem] = []
    for issue in issues:
        try:
            key = issue.get("key")
            if not key:
                continue

            fields = issue.get("fields", {}) or {}
            assignee = fields.get("assignee") or {}
            status = fields.get("status") or {}
            priority = fields.get("priority") or {}
            issue_type = fields.get("issuetype") or {}

            items.append(schemas.AssignedItem(
                source=schemas.TaskSource.jira,
                key=key,
                title=fields.get("summary") or key,
                url=f"{base_url}/browse/{key}",
                state=status.get("name"),
                status=status.get("name"),
                assignee=assignee.get("displayName"),
                issue_type=issue_type.get("name"),
                priority=priority.get("name"),
                body=jira_text(fields.get("description")),
                updated_at=_parse_stamp(fields.get("updated")),
            ))
        except Exception:
            continue

    return items
