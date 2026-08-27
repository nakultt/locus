"""
Moving a GitHub Projects card to match the pipeline stage.

Everything else Locus writes to GitHub is about an *issue* -- closing it,
commenting on it, reading its links. A Projects v2 board is a different object
with a different shape, and it is the surface a team actually watches: a ticket
whose branch, review and QA round trip all completed still sits in `Todo` if
nobody drags it, because closing an issue only moves the card when the project
happens to have the stock workflow enabled -- and that workflow can express
"closed", nothing else. `in_review` and `testing` have no representation in it
at all.

**A board's columns are not columns.** A Projects v2 board renders the options
of a single-select field, conventionally named `Status`. So there is nothing to
configure per repo: the project, the field and its options are all discoverable
from the issue itself, and `describe_board` resolves them at call time rather
than storing ids that would go stale the moment someone renames a column.

**The mapping is configured, and an unmapped stage moves nothing.** Locus
derives ten stages; a board typically has three columns. Collapsing them is a
judgement about what a team means by "done" -- most boards would call a merged
change done, and the whole argument for `close_on_qa_signoff` is that it is not
done until a tester says so. Guessing would encode one of those silently, so
the map is a setting and a stage absent from it leaves the card alone. That is
also what makes a partial map safe: a team that only wants the `done` transition
writes one line.

**Never backwards, for the same reason Jira is forward-only.** A card a human
dragged forward must not be walked back by a refresh, and the stage is derived
from live state that can legitimately regress -- a push after approval revokes
it, which is correct in the pipeline and would look like the board losing
progress. `is_forward_move` refuses it, using the board's own column order,
which is the only ordering that means anything to the team reading it.

**A failure here costs the card, never the work.** Every entry point swallows
its own exceptions and reports through the return value, the rule `comms_log`
and `integration_health` already follow: a merge that completed must not be
reported as failed because a board update 403'd on a missing scope.

The `project` / `read:project` OAuth scope is separate from `repo` and is not
implied by it. A token without it gets `INSUFFICIENT_SCOPES` on the very first
query, which `describe_board` reports as a disabled board rather than an error,
since the common cause is a user who has simply not re-authorised yet.
"""

import logging
from dataclasses import dataclass, field

import httpx

from app.services.github_pr import GITHUB_GRAPHQL, build_headers

logger = logging.getLogger(__name__)

# The single-select field a board's columns come from. GitHub names it this on
# every project created from a template, and the field is addressed by name
# because its id differs per project.
STATUS_FIELD = "Status"

# An issue belongs to few projects in practice; a board with more than this is
# not something a stage sync should be guessing between.
MAX_PROJECTS_PER_ISSUE = 10

# Note there is no page size for a single-select field's `options`: GitHub
# returns the full list and rejects `first:` on it outright. That is the
# schema's own statement that a board's columns are a small fixed set.

# Stage -> column name, applied when a repo configures no map of its own.
#
# Nothing between `branch_created` and `testing` is distinguished, because the
# default board GitHub creates has exactly three columns and every one of those
# stages means the same thing to it: someone is working on this. `merged` is
# deliberately *not* Done -- "merged" and "done" are different claims, and the
# pipeline exists because a human still confirms the second.
DEFAULT_STAGE_COLUMNS: dict[str, str] = {
    "assigned": "Todo",
    # An agent writing the first draft is somebody working on it, as far as the
    # board is concerned. The distinction between who is writing belongs on the
    # card's own mode chip, not in a status column every teammate reads.
    "authoring": "In progress",
    "branch_created": "In progress",
    "in_progress": "In progress",
    "analyzed": "In progress",
    "in_review": "In progress",
    "changes_requested": "In progress",
    "approved": "In progress",
    "merged": "In progress",
    "testing": "In progress",
    "done": "Done",
}


@dataclass
class BoardColumn:
    """One option of the Status field -- one column on the board."""

    option_id: str
    name: str


@dataclass
class BoardItem:
    """An issue's card on one project board."""

    project_id: str
    project_title: str
    project_number: int
    item_id: str
    field_id: str | None = None
    current_column: str | None = None
    columns: list[BoardColumn] = field(default_factory=list)

    def column_named(self, name: str) -> BoardColumn | None:
        """
        Find a column by name, case-insensitively.

        Case is not meaningful to a person reading a board, and a map
        configured as "in progress" against a column named "In Progress" would
        otherwise silently never match -- a failure that looks exactly like the
        feature being off.
        """
        target = (name or "").strip().casefold()
        if not target:
            return None
        for column in self.columns:
            if column.name.strip().casefold() == target:
                return column
        return None

    def position_of(self, name: str | None) -> int | None:
        """Index of a column in the board's own left-to-right order."""
        if not name:
            return None
        found = self.column_named(name)
        if found is None:
            return None
        return next(
            (i for i, c in enumerate(self.columns) if c.option_id == found.option_id),
            None,
        )


@dataclass
class MoveResult:
    """
    What happened to the card.

    `moved` false with `error` unset is the ordinary case, not a problem: the
    stage is unmapped, the card is already there, or the move would go
    backwards. `detail` is written for the run log and the report document, so
    it says which board and which column rather than only that something moved.
    """

    moved: bool = False
    detail: str | None = None
    error: str | None = None


def _gql_string(value: str) -> str:
    """
    A GraphQL string literal.

    Same rule as `issue_links`: repository names are interpolated rather than
    passed as variables, so escaping is mandatory -- nothing stops someone
    naming a fork with a quote in it.
    """
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


# One query answers all three questions: which boards hold this issue, what
# columns each board has, and where the card currently sits. Splitting it would
# cost three round trips to move one card.
_BOARD_QUERY = """
query {{
  repository(owner: {owner}, name: {name}) {{
    issue(number: {number}) {{
      projectItems(first: {projects}) {{
        nodes {{
          id
          project {{
            id
            number
            title
            field(name: {status_field}) {{
              ... on ProjectV2SingleSelectField {{
                id
                options {{ id name }}
              }}
            }}
          }}
          fieldValueByName(name: {status_field}) {{
            ... on ProjectV2ItemFieldSingleSelectValue {{ name }}
          }}
        }}
      }}
    }}
  }}
}}
"""

_MOVE_MUTATION = """
mutation($project: ID!, $item: ID!, $field: ID!, $option: String!) {
  updateProjectV2ItemFieldValue(input: {
    projectId: $project
    itemId: $item
    fieldId: $field
    value: { singleSelectOptionId: $option }
  }) {
    projectV2Item { id }
  }
}
"""


async def _post(
    token: str, query: str, variables: dict | None = None
) -> tuple[dict | None, str | None]:
    """
    Run one GraphQL request.

    Returns `(data, error)`. A missing `project` scope is reported as an error
    string rather than raised: the caller turns it into a skipped board, since
    the overwhelmingly likely cause is a user who connected GitHub before this
    feature existed and has not re-authorised.
    """
    payload: dict = {"query": query}
    if variables:
        payload["variables"] = variables

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                GITHUB_GRAPHQL, headers=build_headers(token), json=payload
            )
    except Exception as e:
        logger.debug("Project board request failed: %s", e)
        return None, f"request failed: {e}"

    if response.status_code != 200:
        return None, f"GitHub returned {response.status_code}"

    try:
        body = response.json()
    except ValueError:
        return None, "GitHub returned a non-JSON response"

    errors = body.get("errors") or []
    data = body.get("data")

    # GraphQL reports a missing scope as a 200 carrying errors, so the status
    # code alone never reveals it.
    if errors:
        messages = " ".join(str(e.get("message", "")) for e in errors)
        if "INSUFFICIENT_SCOPES" in messages or "read:project" in messages:
            return None, (
                "the stored GitHub token lacks the 'project' scope; "
                "reconnect GitHub to let Locus update the board"
            )
        # Partial data is normal and kept: an error on one board must not cost
        # the others.
        if not data:
            logger.debug("Project board query errors: %s", messages[:300])
            return None, messages[:200] or "GraphQL error"

    return data, None


def _parse_items(data: dict | None) -> list[BoardItem]:
    """
    Every board card for one issue.

    GitHub returns explicit nulls for a project the token cannot see and for an
    issue that does not exist, so each level is guarded by value -- the
    `.get(key, default)` trap the codebase has already been bitten by.
    """
    repository = (data or {}).get("repository")
    if not isinstance(repository, dict):
        return []
    issue = repository.get("issue")
    if not isinstance(issue, dict):
        return []

    items: list[BoardItem] = []
    container = issue.get("projectItems") or {}

    for node in container.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        item_id = node.get("id")
        project = node.get("project")
        if not item_id or not isinstance(project, dict):
            continue
        project_id = project.get("id")
        if not project_id:
            continue

        # A project whose Status field is not a single select -- or which has
        # no Status field at all -- is a board this cannot move a card on. It
        # is still returned, so the caller can say so rather than being silent.
        columns: list[BoardColumn] = []
        field_node = project.get("field")
        field_id = None
        if isinstance(field_node, dict):
            field_id = field_node.get("id")
            options = field_node.get("options") or []
            for option in options:
                if not isinstance(option, dict):
                    continue
                option_id = option.get("id")
                option_name = option.get("name")
                if option_id and option_name:
                    columns.append(BoardColumn(option_id=option_id, name=option_name))

        current = None
        value = node.get("fieldValueByName")
        if isinstance(value, dict):
            current = value.get("name")

        items.append(BoardItem(
            project_id=project_id,
            project_title=project.get("title") or "project",
            project_number=project.get("number") or 0,
            item_id=item_id,
            field_id=field_id,
            current_column=current,
            columns=columns,
        ))

    return items


async def describe_board(
    token: str, repo: str, issue_number: int
) -> tuple[list[BoardItem], str | None]:
    """
    The project cards for one issue, with each board's columns.

    Returns `(items, error)`. An empty list with no error means the issue is on
    no board, which is ordinary and not worth reporting anywhere.
    """
    if not token or not repo or "/" not in repo or issue_number is None:
        return [], None

    owner, name = repo.split("/", 1)
    query = _BOARD_QUERY.format(
        owner=_gql_string(owner),
        name=_gql_string(name),
        number=int(issue_number),
        projects=MAX_PROJECTS_PER_ISSUE,
        status_field=_gql_string(STATUS_FIELD),
    )

    data, error = await _post(token, query)
    if error:
        return [], error
    return _parse_items(data), None


def resolve_column(stage: str, column_map: dict[str, str] | None) -> str | None:
    """
    The column one pipeline stage belongs in.

    A configured map replaces the default outright rather than merging with it.
    Merging would mean a team that deliberately dropped a stage from their map
    silently got the default back, and the point of an unmapped stage is that
    the card is left alone.
    """
    source = column_map if column_map else DEFAULT_STAGE_COLUMNS
    value = (source.get(stage) or "").strip()
    return value or None


def is_forward_move(item: BoardItem, target: str) -> bool:
    """
    Whether moving to `target` advances the card.

    Ordered by the board's own columns, which is the ordering the team reads.
    A card in a column that is not on the board -- renamed since, or set by
    something else -- is treated as movable: refusing would strand it forever.
    """
    target_position = item.position_of(target)
    if target_position is None:
        return False
    current_position = item.position_of(item.current_column)
    if current_position is None:
        return True
    return target_position > current_position


async def move_card(
    token: str,
    repo: str,
    issue_number: int,
    stage: str,
    *,
    column_map: dict[str, str] | None = None,
    allow_backwards: bool = False,
) -> MoveResult:
    """
    Move an issue's card to the column its pipeline stage maps to.

    Safe to call repeatedly: a card already in the target column reports
    `moved=False` and issues no mutation, so the sweeps and webhooks that fire
    several times per stage cost one query each rather than rewriting the same
    value.

    Args:
        stage: A `TaskStage` value, as a string.
        column_map: Stage -> column name. Falls back to DEFAULT_STAGE_COLUMNS.
        allow_backwards: Permit a move to an earlier column. Off by default;
            see the module docstring.
    """
    target = resolve_column(stage, column_map)
    if not target:
        return MoveResult(detail=f"stage {stage!r} is not mapped to a column")

    items, error = await describe_board(token, repo, issue_number)
    if error:
        return MoveResult(error=error)
    if not items:
        return MoveResult(detail=f"{repo}#{issue_number} is not on a project board")

    moved: list[str] = []
    skipped: list[str] = []
    failures: list[str] = []

    for item in items:
        label = f"{item.project_title}"

        if not item.field_id or not item.columns:
            skipped.append(f"{label}: no single-select {STATUS_FIELD} field")
            continue

        column = item.column_named(target)
        if column is None:
            skipped.append(f"{label}: no column named {target!r}")
            continue

        if (item.current_column or "").strip().casefold() == column.name.strip().casefold():
            skipped.append(f"{label}: already in {column.name}")
            continue

        if not allow_backwards and not is_forward_move(item, target):
            skipped.append(
                f"{label}: {item.current_column} -> {column.name} would move backwards"
            )
            continue

        _, move_error = await _post(
            token,
            _MOVE_MUTATION,
            {
                "project": item.project_id,
                "item": item.item_id,
                "field": item.field_id,
                "option": column.option_id,
            },
        )
        if move_error:
            failures.append(f"{label}: {move_error}")
            continue

        moved.append(f"{label}: {item.current_column or 'unset'} -> {column.name}")

    if failures and not moved:
        return MoveResult(error="; ".join(failures))

    return MoveResult(
        moved=bool(moved),
        detail="; ".join(moved + skipped) or None,
        error="; ".join(failures) or None,
    )


async def sync_issues(
    token: str,
    repo: str,
    issue_numbers: list[int],
    stage: str,
    *,
    column_map: dict[str, str] | None = None,
) -> list[str]:
    """
    Move every linked issue's card to one stage's column.

    Returns human-readable lines for the run log -- one per issue that moved or
    failed, and nothing for an issue that was already in place. Never raises:
    the merge or review this decorates is worth completing either way.
    """
    lines: list[str] = []

    for number in issue_numbers:
        try:
            result = await move_card(
                token, repo, number, stage, column_map=column_map
            )
        except Exception as e:
            logger.debug("Board sync failed for %s#%s: %s", repo, number, e)
            lines.append(f"#{number}: board update failed: {e}")
            continue

        if result.error:
            lines.append(f"#{number}: {result.error}")
        elif result.moved:
            lines.append(f"#{number}: {result.detail}")

    return lines
