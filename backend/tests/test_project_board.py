"""
Moving a GitHub Projects card to match the pipeline stage.

The board is the surface a team actually watches, and until this existed it
could only ever say "open" or "closed" -- GitHub's stock project workflow has
one trigger, so a ticket whose branch, review round trip and QA thread had all
completed still sat in `Todo` until somebody dragged it.

The rules worth pinning are the ones about *not* moving. A card only advances,
because the derived stage can legitimately regress -- a push after approval
revokes it -- and a board that walks backwards on a refresh is worse than one
that never moved. An unmapped stage moves nothing, which is what makes a
partial map safe to write. And a QA rejection is the single exception in both
directions: a tester saying the change is broken is the one statement strong
enough to pull a card back.
"""

import pytest

from app.services.integrations import project_board
from app.services.pipeline import agent_settings

REPO = "acme/widget"
TOKEN = "gho_test"

# The three columns GitHub creates on a new board, in board order.
TODO = {"id": "opt_todo", "name": "Todo"}
DOING = {"id": "opt_doing", "name": "In progress"}
DONE = {"id": "opt_done", "name": "Done"}


def _board(*, current="Todo", columns=(TODO, DOING, DONE), field_id="fld_1",
           item_id="item_1", title="Sprint board"):
    """
    A full GraphQL response shaped like GitHub's, for one issue.

    Wrapped in the `data` envelope the real endpoint sends, since that is what
    `_post` unwraps -- a fixture returning the bare payload would test a
    response shape GitHub never produces.
    """
    field = None
    if field_id is not None:
        field = {"id": field_id, "options": list(columns)}
    return {"data": {
        "repository": {
            "issue": {
                "projectItems": {
                    "nodes": [
                        {
                            "id": item_id,
                            "project": {
                                "id": "proj_1",
                                "number": 1,
                                "title": title,
                                "field": field,
                            },
                            "fieldValueByName": (
                                {"name": current} if current else None
                            ),
                        }
                    ]
                }
            }
        }
    }}


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class _Recorder:
    """
    Stands in for the GraphQL endpoint, recording every request.

    The mutation and the query go to the same URL, so they are told apart by
    the presence of `variables` -- only the mutation sends any.
    """

    def __init__(self, *responses):
        self._responses = list(responses)
        self.requests: list[dict] = []

    async def __call__(self, url, headers=None, json=None):
        self.requests.append(json or {})
        if self._responses:
            payload = self._responses.pop(0)
        else:
            payload = {"data": {"updateProjectV2ItemFieldValue": {
                "projectV2Item": {"id": "item_1"}}}}
        if isinstance(payload, _FakeResponse):
            return payload
        return _FakeResponse(payload)

    @property
    def mutations(self) -> list[dict]:
        return [r for r in self.requests if r.get("variables")]


@pytest.fixture
def graphql(monkeypatch):
    """Patch the httpx client used by project_board, returning the recorder."""

    def _install(*responses):
        recorder = _Recorder(*responses)

        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def post(self, url, headers=None, json=None):
                return await recorder(url, headers=headers, json=json)

        monkeypatch.setattr(
            project_board.httpx, "AsyncClient", lambda **kw: _Client()
        )
        return recorder

    return _install


# --- The default map ----------------------------------------------------


def test_merged_is_not_done():
    """
    The distinction the whole pipeline is built on.

    "Merged" and "done" are different claims, and a card in Done says the work
    is verified when nobody has verified it. Only a QA sign-off reaches Done.
    """
    assert project_board.resolve_column("merged", None) == "In progress"
    assert project_board.resolve_column("testing", None) == "In progress"
    assert project_board.resolve_column("done", None) == "Done"


def test_every_derived_stage_has_a_default_column():
    """
    A stage with no entry silently moves nothing, which on the default map
    would read as the feature being broken rather than unconfigured.
    """
    from app import schemas

    for stage in schemas.TaskStage:
        assert project_board.resolve_column(stage.value, None), stage


def test_a_configured_map_replaces_the_default_rather_than_merging():
    """
    Merging would hand back the default for any stage a team deliberately
    dropped, and leaving a card alone is the entire point of omitting one.
    """
    partial = {"done": "Shipped"}
    assert project_board.resolve_column("done", partial) == "Shipped"
    assert project_board.resolve_column("merged", partial) is None


# --- Discovery ----------------------------------------------------------


@pytest.mark.asyncio
async def test_columns_are_discovered_from_the_board(graphql):
    """Nothing is configured: the project, field and options are all read."""
    graphql(_board())

    items, error = await project_board.describe_board(TOKEN, REPO, 8)

    assert error is None
    assert [c.name for c in items[0].columns] == ["Todo", "In progress", "Done"]
    assert items[0].field_id == "fld_1"
    assert items[0].current_column == "Todo"


@pytest.mark.asyncio
async def test_a_missing_project_scope_is_reported_not_raised(graphql):
    """
    `repo` does not imply `project`, so every user connected before this
    shipped hits this path. It must read as a skipped board, not a failure.
    """
    graphql({"errors": [{"message":
                         "Your token has not been granted the required scopes "
                         "to execute this query. INSUFFICIENT_SCOPES"}]})

    items, error = await project_board.describe_board(TOKEN, REPO, 8)

    assert items == []
    assert "project" in error and "reconnect" in error.lower()


@pytest.mark.asyncio
async def test_explicit_nulls_do_not_crash_the_parse(graphql):
    """
    GitHub returns a present-but-null key for an issue the token cannot see,
    so `.get(key, default)` never fires. Guard the value, not the key.
    """
    assert project_board._parse_items(None) == []
    assert project_board._parse_items({"repository": None}) == []
    assert project_board._parse_items({"repository": {"issue": None}}) == []
    assert project_board._parse_items(
        {"repository": {"issue": {"projectItems": None}}}
    ) == []


@pytest.mark.asyncio
async def test_an_issue_on_no_board_is_not_an_error(graphql):
    graphql({"repository": {"issue": {"projectItems": {"nodes": []}}}})

    result = await project_board.move_card(TOKEN, REPO, 8, "done")

    assert not result.moved
    assert result.error is None
    assert "not on a project board" in result.detail


# --- Moving -------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_card_moves_to_the_mapped_column(graphql):
    recorder = graphql(_board(current="Todo"))

    result = await project_board.move_card(TOKEN, REPO, 8, "done")

    assert result.moved
    assert recorder.mutations[0]["variables"] == {
        "project": "proj_1",
        "item": "item_1",
        "field": "fld_1",
        "option": "opt_done",
    }


@pytest.mark.asyncio
async def test_a_card_already_in_place_issues_no_mutation(graphql):
    """
    The sweeps and webhooks fire several times per stage, so this is the
    common path, not an edge case.
    """
    recorder = graphql(_board(current="Done"))

    result = await project_board.move_card(TOKEN, REPO, 8, "done")

    assert not result.moved
    assert recorder.mutations == []
    assert "already in Done" in result.detail


@pytest.mark.asyncio
async def test_the_card_never_walks_backwards(graphql):
    """
    The derived stage can legitimately regress -- a push after approval
    revokes it -- and a card a human dragged forward must survive a refresh.
    """
    recorder = graphql(_board(current="Done"))

    result = await project_board.move_card(TOKEN, REPO, 8, "in_progress")

    assert not result.moved
    assert recorder.mutations == []
    assert "backwards" in result.detail


@pytest.mark.asyncio
async def test_a_qa_rejection_may_move_the_card_back(graphql):
    """
    The one exception. A tester saying the change is broken reopens the
    ticket, and a card left in Done would contradict it.
    """
    recorder = graphql(_board(current="Done"))

    result = await project_board.move_card(
        TOKEN, REPO, 8, "in_progress", allow_backwards=True
    )

    assert result.moved
    assert recorder.mutations[0]["variables"]["option"] == "opt_doing"


@pytest.mark.asyncio
async def test_an_unmapped_stage_queries_nothing(graphql):
    """Cheap as well as safe: no map entry means no request at all."""
    recorder = graphql(_board())

    result = await project_board.move_card(
        TOKEN, REPO, 8, "merged", column_map={"done": "Done"}
    )

    assert not result.moved
    assert recorder.requests == []
    assert "not mapped" in result.detail


@pytest.mark.asyncio
async def test_column_names_match_case_insensitively(graphql):
    """
    A map written "in progress" against a column named "In progress" would
    otherwise never match, and the silence looks exactly like the feature
    being switched off.
    """
    recorder = graphql(_board(current="Todo"))

    result = await project_board.move_card(
        TOKEN, REPO, 8, "merged", column_map={"merged": "IN PROGRESS"}
    )

    assert result.moved
    assert recorder.mutations[0]["variables"]["option"] == "opt_doing"


@pytest.mark.asyncio
async def test_a_column_the_board_does_not_have_is_skipped_not_failed(graphql):
    recorder = graphql(_board(current="Todo"))

    result = await project_board.move_card(
        TOKEN, REPO, 8, "testing", column_map={"testing": "QA"}
    )

    assert not result.moved
    assert result.error is None
    assert "no column named 'QA'" in result.detail
    assert recorder.mutations == []


@pytest.mark.asyncio
async def test_a_board_without_a_status_field_is_skipped(graphql):
    """A project whose Status is not a single select has no columns to move to."""
    graphql(_board(field_id=None))

    result = await project_board.move_card(TOKEN, REPO, 8, "done")

    assert not result.moved
    assert result.error is None
    assert "no single-select" in result.detail


# --- The lifecycle ------------------------------------------------------


def test_the_card_walks_the_board_once_across_a_full_round_trip():
    """
    The sequence a team actually sees, on the three columns GitHub creates.

    Pinned as a whole because each step is only correct relative to the last:
    the interesting property is that the card advances exactly twice and is
    pulled back exactly once, rather than jittering on every event.
    """
    item = project_board.BoardItem(
        project_id="p", project_title="board", project_number=1,
        item_id="i", field_id="f", current_column="Todo",
        columns=[project_board.BoardColumn(o["id"], o["name"])
                 for o in (TODO, DOING, DONE)],
    )

    # (event, stage, is the rejection path)
    lifecycle = [
        ("pr opened", "in_progress", False),
        ("changes requested", "changes_requested", False),
        ("approved", "approved", False),
        ("merged, QA deferred", "testing", False),
        ("QA says broken", "in_progress", True),
        ("fix pr opened", "in_progress", False),
        ("merged again", "testing", False),
        ("QA signs off", "done", False),
    ]

    seen = []
    for _, stage, rejection in lifecycle:
        target = project_board.resolve_column(stage, None)
        moves = rejection or project_board.is_forward_move(item, target)
        if moves:
            item.current_column = target
        seen.append(item.current_column)

    assert seen == [
        "In progress",   # the PR opening is the visible start of work
        "In progress",   # review churn does not shuffle the card
        "In progress",
        "In progress",   # merged is NOT done
        "In progress",   # the rejection lands where the work resumes
        "In progress",
        "In progress",
        "Done",          # only the sign-off
    ]


def test_only_the_rejection_can_pull_a_card_out_of_done():
    """
    Everything else refuses, so no other path can produce this move even by
    passing the same stage.
    """
    item = project_board.BoardItem(
        project_id="p", project_title="board", project_number=1,
        item_id="i", field_id="f", current_column="Done",
        columns=[project_board.BoardColumn(o["id"], o["name"])
                 for o in (TODO, DOING, DONE)],
    )
    assert not project_board.is_forward_move(item, "In progress")


# --- Failure is contained ------------------------------------------------


@pytest.mark.asyncio
async def test_sync_issues_never_raises(graphql, monkeypatch):
    """
    The merge that this decorates has already happened. A board update that
    throws must not turn a completed merge into a reported failure.
    """
    async def _boom(*a, **kw):
        raise RuntimeError("network gone")

    monkeypatch.setattr(project_board, "move_card", _boom)

    lines = await project_board.sync_issues(TOKEN, REPO, [8, 9], "done")

    assert len(lines) == 2
    assert all("board update failed" in line for line in lines)


@pytest.mark.asyncio
async def test_one_failing_issue_does_not_cost_the_others(graphql):
    recorder = graphql(
        _FakeResponse({"errors": [{"message": "nope"}]}, status_code=500),
        _board(current="Todo"),
    )

    lines = await project_board.sync_issues(TOKEN, REPO, [8, 9], "done")

    assert any("500" in line for line in lines)
    assert recorder.mutations, "the second issue still moved"


@pytest.mark.asyncio
async def test_an_unmoved_card_is_silent_in_the_log(graphql):
    """
    A line per push saying "already in In progress" trains people to skip the
    log. Only real movement and real failures are reported.
    """
    graphql(_board(current="Done"), _board(current="Done"))

    assert await project_board.sync_issues(TOKEN, REPO, [8, 9], "done") == []


# --- The query GitHub actually accepts -----------------------------------


def test_the_options_field_is_not_paginated():
    """
    `ProjectV2SingleSelectField.options` takes no `first:` argument.

    Pinned as a string check because every other test here mocks the endpoint
    and so asserts this module's *assumption* about the schema rather than the
    schema. The first version shipped `options(first: 50)`, which GitHub
    rejects outright with "Field 'options' doesn't accept argument 'first'" --
    every card would have reported "no single-select Status field" forever,
    and no mocked test could have caught it.
    """
    query = project_board._BOARD_QUERY
    assert "options {" in query
    assert "options(first" not in query


def test_the_query_escapes_repository_names():
    """
    Repo names are interpolated rather than passed as variables, so escaping
    is mandatory -- nothing stops someone naming a fork with a quote in it.
    """
    assert project_board._gql_string('we"ird') == '"we\\"ird"'


# --- Settings -----------------------------------------------------------


def test_the_column_map_is_parsed_from_lines():
    parsed = agent_settings.parse_column_map(
        "in_review: In review\n"
        "done:Done\n"
        "\n"
        "   \n"
    )
    assert parsed == {"in_review": "In review", "done": "Done"}


def test_a_column_name_may_contain_a_colon():
    """Split on the first colon only -- the rest belongs to the column name."""
    assert agent_settings.parse_column_map("done: Done: verified") == {
        "done": "Done: verified"
    }


def test_a_line_without_a_colon_is_ignored():
    assert agent_settings.parse_column_map("just some text") == {}
