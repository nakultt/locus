"""
An issue's own view of what is being done about it.

Everything else in the pipeline discovers the issue/pull-request edge from the
pull request side: `github_pr.get_linked_issues` reads `closingIssuesReferences`
while a PR is being analyzed, and `pr_agent` records the result as a ticket key.
That covers the common case and nothing else, because it has two blind spots
that are exactly where a task board is asked to look.

**A link made in the Development panel carries no keyword.** Attaching a pull
request through an issue's sidebar creates a real edge in GitHub's graph, but
`closingIssuesReferences` is the *PR's* list of what it closes, and a sidebar
link does not put "Closes #42" in the body. The issue records it on
`closedByPullRequestsReferences` instead, which nothing queried.

**A branch exists before its pull request does.** "Create a branch for this
issue" is the first thing that happens after a ticket is picked up, and until
the PR opens there is no pull request to analyze -- so the board showed the
work as `assigned`, i.e. as though nobody had started, for as long as someone
was actually writing the code. `Issue.linkedBranches` holds exactly these and
deliberately nothing else: it returns branches affirmatively linked through the
mutation or the UI button, never PRs linked by mention.

The two fields are complementary and neither subsumes the other, so both are
read in one query per issue.

**Nothing here guesses.** Every edge returned came from GitHub's own link
graph, which is what makes it safe to write into `PRReview.ticket_keys` --
the rule in `work_item` is that a work item is never *inferred* from a similar
title, not that it must be typed by hand.

**The batch degrades per issue, and as a whole.** One malformed alias must not
cost the other issues on the board, and a total failure returns empty rather
than raising: the board's rule is that a source which did not answer is
reported, never rendered as an empty queue.
"""

import logging

import httpx

from app import schemas
from app.services.integrations.github_pr import GITHUB_GRAPHQL, build_headers

logger = logging.getLogger(__name__)

# GraphQL aliases are emitted one per issue, so a board full of issues costs a
# single request. Kept well under GitHub's node limit -- the board caps assigned
# items at 50, and each alias here fans out to 2 * LINKS_PER_ISSUE child nodes.
MAX_ISSUES_PER_QUERY = 25

# Both connections are small by nature: an issue with more than ten linked
# branches or pull requests has a problem the board cannot solve.
LINKS_PER_ISSUE = 10

# `closedByPullRequestsReferences` takes `includeClosedPrs`. Closed and merged
# pull requests are included deliberately -- a merged PR is the reason a task
# sits at "merged" rather than "in progress", and excluding them would make an
# issue whose work is finished read as untouched.
_ALIAS_FRAGMENT = """
  {alias}: repository(owner: {owner}, name: {name}) {{
    issue(number: {number}) {{
      number
      linkedBranches(first: {limit}) {{
        nodes {{ ref {{ name repository {{ nameWithOwner }} }} }}
      }}
      closedByPullRequestsReferences(first: {limit}, includeClosedPrs: true) {{
        nodes {{
          number
          title
          state
          url
          isDraft
          merged
          repository {{ nameWithOwner }}
        }}
      }}
    }}
  }}
"""

# Older GitHub Enterprise Server versions predate
# `closedByPullRequestsReferences`. Rather than fail the whole board there, the
# query is retried without that connection -- linked branches alone are still
# worth showing, and the PR half is already covered from the analysis side.
_ALIAS_FRAGMENT_NO_CLOSED_BY = """
  {alias}: repository(owner: {owner}, name: {name}) {{
    issue(number: {number}) {{
      number
      linkedBranches(first: {limit}) {{
        nodes {{ ref {{ name repository {{ nameWithOwner }} }} }}
      }}
    }}
  }}
"""


def _gql_string(value: str) -> str:
    """
    A GraphQL string literal.

    Repository names are interpolated into the query rather than passed as
    variables, because each alias needs its own pair and a variable set keyed
    per alias is harder to read than an escaped literal. Escaping is therefore
    not optional: a repository name is attacker-influenceable in the sense that
    nothing stops someone naming a fork with a quote in it.
    """
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _alias_for(index: int) -> str:
    """
    A GraphQL alias for one issue.

    Positional rather than derived from the repository name: an alias must
    match /[_A-Za-z][_0-9A-Za-z]*/ and a repo name may contain dots and
    hyphens, so deriving one would need escaping that positions do not.
    """
    return f"i{index}"


def _build_query(
    items: list[schemas.AssignedItem], *, include_closed_by: bool = True
) -> str:
    """Assemble one query covering every issue in the batch."""
    fragment = _ALIAS_FRAGMENT if include_closed_by else _ALIAS_FRAGMENT_NO_CLOSED_BY
    parts = [
        fragment.format(
            alias=_alias_for(index),
            owner=_gql_string(item.repo.split("/", 1)[0]),
            name=_gql_string(item.repo.split("/", 1)[1]),
            number=item.number,
            limit=LINKS_PER_ISSUE,
        )
        for index, item in enumerate(items)
    ]
    return "query {\n" + "".join(parts) + "}\n"


def _parse_alias(node: dict | None) -> schemas.IssueLinks | None:
    """
    One issue's links, from its alias in the response.

    GitHub returns an explicit `null` for a repository the token cannot see and
    for an issue that does not exist, so every level is guarded by value rather
    than by key presence -- `.get(key, default)` does not fire when the key is
    present and null.
    """
    if not isinstance(node, dict):
        return None
    issue = node.get("issue")
    if not isinstance(issue, dict):
        return None

    branches: list[schemas.LinkedBranch] = []
    linked = issue.get("linkedBranches") or {}
    for branch_node in linked.get("nodes") or []:
        if not isinstance(branch_node, dict):
            continue
        ref = branch_node.get("ref") or {}
        name = ref.get("name")
        if not name:
            continue
        repository = ref.get("repository") or {}
        branches.append(schemas.LinkedBranch(
            name=name,
            repo=repository.get("nameWithOwner"),
        ))

    pull_requests: list[schemas.LinkedPullRequest] = []
    closed_by = issue.get("closedByPullRequestsReferences") or {}
    for pr_node in closed_by.get("nodes") or []:
        if not isinstance(pr_node, dict):
            continue
        number = pr_node.get("number")
        repository = pr_node.get("repository") or {}
        repo = repository.get("nameWithOwner")
        if number is None or not repo:
            continue
        pull_requests.append(schemas.LinkedPullRequest(
            repo=repo,
            pr_number=number,
            title=pr_node.get("title"),
            url=pr_node.get("url"),
            state=(pr_node.get("state") or "").lower() or None,
            is_draft=bool(pr_node.get("isDraft")),
            merged=bool(pr_node.get("merged")),
        ))

    return schemas.IssueLinks(branches=branches, pull_requests=pull_requests)


async def _post(token: str, query: str) -> tuple[dict | None, bool]:
    """
    Run one GraphQL query.

    Returns `(payload, schema_rejected)`. The second value distinguishes "this
    GitHub does not have that field" -- which a reduced query can still answer
    -- from an ordinary failure, which retrying would not help.
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                GITHUB_GRAPHQL,
                headers=build_headers(token),
                json={"query": query},
            )
    except Exception as e:
        logger.debug("Issue links request failed: %s", e)
        return None, False

    if response.status_code != 200:
        logger.debug("Issue links returned %s", response.status_code)
        return None, False

    try:
        payload = response.json()
    except ValueError:
        return None, False

    # GraphQL reports an unknown field as a 200 carrying errors. Partial data
    # is normal and kept -- an error on one alias (a repo the token cannot see)
    # leaves the others populated.
    errors = payload.get("errors") or []
    if errors and not payload.get("data"):
        messages = " ".join(str(e.get("message", "")) for e in errors)
        rejected = (
            "closedByPullRequestsReferences" in messages
            or "includeClosedPrs" in messages
        )
        logger.debug("Issue links query errors: %s", messages[:300])
        return None, rejected

    return payload, False


async def fetch(
    token: str, items: list[schemas.AssignedItem]
) -> dict[str, schemas.IssueLinks]:
    """
    Linked branches and pull requests for every assigned GitHub issue.

    Keyed by the item's own `owner/name#N` key, so the caller joins on the key
    it already has rather than reconstructing one.

    Returns an empty mapping on any failure. The board reports GitHub as
    unavailable from the assigned lookup, which shares this token -- a links
    call that fails while the assigned call succeeded costs the extra context,
    never the board.
    """
    if not token:
        return {}

    issues = [
        item for item in items
        if item.source is schemas.TaskSource.github
        and item.repo and "/" in item.repo and item.number is not None
    ]
    if not issues:
        return {}

    links: dict[str, schemas.IssueLinks] = {}

    for start in range(0, len(issues), MAX_ISSUES_PER_QUERY):
        batch = issues[start:start + MAX_ISSUES_PER_QUERY]

        payload, rejected = await _post(token, _build_query(batch))
        if payload is None and rejected:
            # This GitHub predates the closed-by connection; branches alone are
            # still worth having.
            payload, _ = await _post(
                token, _build_query(batch, include_closed_by=False)
            )
        if payload is None:
            continue

        data = payload.get("data") or {}
        for index, item in enumerate(batch):
            parsed = _parse_alias(data.get(_alias_for(index)))
            if parsed is not None and (parsed.branches or parsed.pull_requests):
                links[item.key] = parsed

    return links
