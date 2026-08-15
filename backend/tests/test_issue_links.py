"""
Linking a pull request or branch to an issue through GitHub's Development panel.

The pipeline has always read the issue/PR edge from the pull request side,
which sees only closing keywords. These tests pin the two cases that side
cannot see: a pull request attached through the sidebar with no keyword in its
body, and a branch that exists before any pull request does.

The stage rules matter as much as the parsing. A linked branch is the earliest
evidence work has started, but it stays linked forever -- so the test that a
reviewed task does not walk backwards to "branch created" is the one guarding
against a card that reports progress in reverse on every refresh.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models, schemas
from app.services import issue_links, task_board

REPO, OWNER = "acme/widget", 1
KEY = f"{REPO}#42"


@pytest.fixture
def db(tmp_path):
    from app.database import Base

    engine = create_engine(
        f"sqlite:///{tmp_path}/t.db", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _issue(key=KEY, *, repo=REPO, number=42):
    return schemas.AssignedItem(
        source=schemas.TaskSource.github,
        key=key,
        title="Retry the gate",
        url=f"https://github.com/{repo}/issues/{number}",
        repo=repo,
        number=number,
    )


def _review(db, *, pr, state, tickets=None, hours_ago=1.0):
    review = models.PRReview(
        repo=REPO, pr_number=pr, pr_title=f"PR {pr}", author="junior-dev",
        state=state, round_number=1, ticket_keys=tickets,
        last_reviewer="senior-dev", owner_id=OWNER,
    )
    db.add(review)
    db.commit()
    review.created_at = datetime.now(UTC) - timedelta(hours=hours_ago)
    review.updated_at = review.created_at
    db.commit()
    return review


def _response(*, branches=(), pulls=(), alias="i0"):
    """A GraphQL payload shaped like GitHub's, for one issue."""
    return {
        "data": {
            alias: {
                "issue": {
                    "number": 42,
                    "linkedBranches": {
                        "nodes": [
                            {"ref": {"name": name,
                                     "repository": {"nameWithOwner": REPO}}}
                            for name in branches
                        ]
                    },
                    "closedByPullRequestsReferences": {
                        "nodes": [
                            {
                                "number": n, "title": f"PR {n}",
                                "state": "OPEN", "url": f"https://x/pull/{n}",
                                "isDraft": False, "merged": False,
                                "repository": {"nameWithOwner": REPO},
                            }
                            for n in pulls
                        ]
                    },
                }
            }
        }
    }


# --- Parsing ------------------------------------------------------------


def test_sidebar_linked_pr_is_found_without_a_closing_keyword():
    """
    The case the PR-side read cannot see.

    `closingIssuesReferences` reports what a PR's *body* says it closes. A
    sidebar link writes no keyword, so the edge exists only on the issue.
    """
    parsed = issue_links._parse_alias(
        _response(pulls=[7])["data"]["i0"]
    )
    assert [p.pr_number for p in parsed.pull_requests] == [7]
    assert parsed.pull_requests[0].repo == REPO


def test_linked_branch_is_found_before_any_pull_request_exists():
    parsed = issue_links._parse_alias(
        _response(branches=["42-retry-the-gate"])["data"]["i0"]
    )
    assert [b.name for b in parsed.branches] == ["42-retry-the-gate"]
    assert not parsed.pull_requests


def test_explicit_nulls_do_not_crash_the_parse():
    """
    GitHub returns an explicit null for a repo the token cannot see, so
    `.get(key, default)` does not save you -- the key is present and null.
    """
    assert issue_links._parse_alias(None) is None
    assert issue_links._parse_alias({"issue": None}) is None
    assert issue_links._parse_alias(
        {"issue": {"linkedBranches": None,
                   "closedByPullRequestsReferences": None}}
    ) == schemas.IssueLinks()


def test_repo_name_is_escaped_into_the_query():
    """A repository name cannot break out of its string literal."""
    query = issue_links._build_query([_issue(repo='acme/we"ird', number=7)])
    assert '"acme"' in query
    assert '\\"' in query
    assert query.count('name: "we\\"ird"') == 1


@pytest.mark.asyncio
async def test_fetch_returns_empty_without_a_token():
    assert await issue_links.fetch("", [_issue()]) == {}


@pytest.mark.asyncio
async def test_fetch_ignores_jira_items():
    """Only GitHub issues have a Development panel to read."""
    jira = schemas.AssignedItem(
        source=schemas.TaskSource.jira, key="LOC-1", title="t", url="u"
    )
    assert await issue_links.fetch("tok", [jira]) == {}


@pytest.mark.asyncio
async def test_fetch_falls_back_when_the_field_is_unknown(monkeypatch):
    """
    An older GitHub rejects `closedByPullRequestsReferences`. Branches alone
    are still worth showing, so the query is retried without it rather than
    costing the whole board.
    """
    calls: list[str] = []

    async def fake_post(token, query):
        calls.append(query)
        if "closedByPullRequestsReferences" in query:
            return None, True
        return _response(branches=["42-fix"]), False

    monkeypatch.setattr(issue_links, "_post", fake_post)

    links = await issue_links.fetch("tok", [_issue()])
    assert len(calls) == 2
    assert [b.name for b in links[KEY].branches] == ["42-fix"]


@pytest.mark.asyncio
async def test_fetch_returns_empty_on_failure(monkeypatch):
    """A links failure must cost the links, never the board."""
    async def fake_post(token, query):
        return None, False

    monkeypatch.setattr(issue_links, "_post", fake_post)
    assert await issue_links.fetch("tok", [_issue()]) == {}


# --- Stage derivation ---------------------------------------------------


def test_branch_alone_reports_work_started():
    """
    The gap this closes: a branch exists, no PR yet, and the card used to read
    `assigned` -- as though nobody had picked the work up.
    """
    stage, _ = task_board._derive_stage([], None, False, has_pr=False, has_branch=True)
    assert stage is schemas.TaskStage.branch_created


def test_a_pull_request_outranks_its_own_branch():
    """
    The branch stays linked after the PR opens. If it won, every refresh would
    walk the card backwards from "pull request opened" to "branch created".
    """
    stage, _ = task_board._derive_stage([], None, False, has_pr=True, has_branch=True)
    assert stage is schemas.TaskStage.in_progress


def test_a_reviewed_task_is_not_dragged_back_by_its_branch():
    review = models.PRReview(
        repo=REPO, pr_number=7, state=schemas.ReviewState.approved.value,
        round_number=1, owner_id=OWNER,
    )
    stage, _ = task_board._derive_stage(
        [review], None, True, has_pr=True, has_branch=True
    )
    assert stage is schemas.TaskStage.approved


def test_branch_stage_is_absent_when_no_branch_is_linked():
    """
    A greyed-out "Branch created" on a Jira ticket would imply a step that
    never existed for it -- the same rule that keeps `changes_requested` off a
    task that never round-tripped.
    """
    stages = task_board._build_stages(
        schemas.TaskStage.in_review, False, [], branches=[]
    )
    assert schemas.TaskStage.branch_created not in [s.stage for s in stages]


def test_branch_stage_renders_with_its_name():
    stages = task_board._build_stages(
        schemas.TaskStage.branch_created, False, [],
        branches=[schemas.LinkedBranch(name="42-retry")],
    )
    step = next(s for s in stages if s.stage is schemas.TaskStage.branch_created)
    assert step.state is schemas.StageState.running
    assert step.detail == "42-retry"


def test_extra_branches_are_counted_not_listed():
    stages = task_board._build_stages(
        schemas.TaskStage.branch_created, False, [],
        branches=[schemas.LinkedBranch(name="a"), schemas.LinkedBranch(name="b")],
    )
    step = next(s for s in stages if s.stage is schemas.TaskStage.branch_created)
    assert step.detail == "a +1"


# --- The join -----------------------------------------------------------


def test_linked_pr_joins_an_issue_whose_analysis_never_recorded_the_key(db):
    """
    The Development-panel case end to end: the review row carries no ticket
    key, because no keyword was ever written for the analysis to read.
    """
    review = _review(db, pr=7, state=schemas.ReviewState.awaiting_review.value)
    links = schemas.IssueLinks(
        pull_requests=[schemas.LinkedPullRequest(repo=REPO, pr_number=7)]
    )

    matched = task_board._matching_reviews([review], KEY, _issue(), links)
    assert [r.pr_number for r in matched] == [7]


def test_recorded_keys_and_linked_prs_are_unioned(db):
    """
    A task with several PRs may have one attached in the panel and another
    found from a keyword. Either list alone is incomplete.
    """
    keyworded = _review(db, pr=7, state=schemas.ReviewState.approved.value,
                        tickets=KEY)
    sidebar = _review(db, pr=9, state=schemas.ReviewState.awaiting_review.value)
    links = schemas.IssueLinks(
        pull_requests=[schemas.LinkedPullRequest(repo=REPO, pr_number=9)]
    )

    matched = task_board._matching_reviews([keyworded, sidebar], KEY, _issue(), links)
    assert [r.pr_number for r in matched] == [7, 9]


def test_an_unrelated_pull_request_is_not_joined(db):
    other = _review(db, pr=11, state=schemas.ReviewState.awaiting_review.value)
    links = schemas.IssueLinks(
        pull_requests=[schemas.LinkedPullRequest(repo=REPO, pr_number=7)]
    )
    assert task_board._matching_reviews([other], KEY, _issue(), links) == []


# --- Persistence --------------------------------------------------------


def test_a_discovered_link_is_recorded_on_the_review(db):
    """
    Written so the PR is findable as a sibling of the work item, and so the
    board stops depending on the links call having succeeded.
    """
    review = _review(db, pr=7, state=schemas.ReviewState.awaiting_review.value)
    links = schemas.IssueLinks(
        pull_requests=[schemas.LinkedPullRequest(repo=REPO, pr_number=7)]
    )

    task_board._persist_links(
        db, owner_id=OWNER, item=_issue(), links=links, reviews=[review]
    )

    db.refresh(review)
    assert review.ticket_keys == KEY


def test_recording_a_link_never_drops_an_existing_key(db):
    """
    A PR belongs to several work items routinely. Replacing the keys would
    drop the Jira key an analysis read off the branch -- the exact context
    this pipeline exists to carry forward.
    """
    review = _review(db, pr=7, state=schemas.ReviewState.awaiting_review.value,
                     tickets="LOC-431")
    links = schemas.IssueLinks(
        pull_requests=[schemas.LinkedPullRequest(repo=REPO, pr_number=7)]
    )

    task_board._persist_links(
        db, owner_id=OWNER, item=_issue(), links=links, reviews=[review]
    )

    db.refresh(review)
    assert review.ticket_keys.splitlines() == ["LOC-431", KEY]


def test_recording_is_idempotent(db):
    review = _review(db, pr=7, state=schemas.ReviewState.awaiting_review.value,
                     tickets=KEY)
    links = schemas.IssueLinks(
        pull_requests=[schemas.LinkedPullRequest(repo=REPO, pr_number=7)]
    )

    for _ in range(3):
        task_board._persist_links(
            db, owner_id=OWNER, item=_issue(), links=links, reviews=[review]
        )

    db.refresh(review)
    assert review.ticket_keys == KEY


# --- End to end through build() -----------------------------------------


@pytest.mark.asyncio
async def test_board_shows_a_branch_only_issue_as_started(db, monkeypatch):
    """
    The whole point, end to end: an issue with a linked branch and no pull
    request reports that work has begun.
    """
    async def fake_assigned(configs):
        return [_issue()], []

    async def fake_links(token, items):
        return {KEY: schemas.IssueLinks(
            branches=[schemas.LinkedBranch(name="42-retry", repo=REPO)]
        )}

    monkeypatch.setattr(task_board, "fetch_assigned", fake_assigned)
    monkeypatch.setattr(issue_links, "fetch", fake_links)

    board = await task_board.build(
        db, owner_id=OWNER,
        integration_configs={"github": {"api_key": "tok"}},
    )

    card = (board.needs_you + board.in_flight)[0]
    assert card.stage is schemas.TaskStage.branch_created
    assert [b.name for b in card.linked_branches] == ["42-retry"]


@pytest.mark.asyncio
async def test_board_renders_a_linked_pr_locus_has_never_analyzed(db, monkeypatch):
    """A PR attached in the panel moments ago still belongs on the card."""
    async def fake_assigned(configs):
        return [_issue()], []

    async def fake_links(token, items):
        return {KEY: schemas.IssueLinks(pull_requests=[
            schemas.LinkedPullRequest(
                repo=REPO, pr_number=7, title="Fix the gate",
                url="https://github.com/acme/widget/pull/7",
            )
        ])}

    monkeypatch.setattr(task_board, "fetch_assigned", fake_assigned)
    monkeypatch.setattr(issue_links, "fetch", fake_links)

    board = await task_board.build(
        db, owner_id=OWNER,
        integration_configs={"github": {"api_key": "tok"}},
    )

    card = (board.needs_you + board.in_flight)[0]
    assert card.stage is schemas.TaskStage.in_progress
    assert [(p.pr_number, p.title) for p in card.pull_requests] == [
        (7, "Fix the gate")
    ]


@pytest.mark.asyncio
async def test_a_links_failure_does_not_blank_the_board(db, monkeypatch):
    """
    A board that blanks because one call failed is the one wrong answer -- the
    same rule `assigned.py` follows.
    """
    async def fake_assigned(configs):
        return [_issue()], []

    async def fake_links(token, items):
        return {}

    monkeypatch.setattr(task_board, "fetch_assigned", fake_assigned)
    monkeypatch.setattr(issue_links, "fetch", fake_links)

    board = await task_board.build(
        db, owner_id=OWNER,
        integration_configs={"github": {"api_key": "tok"}},
    )

    assert board.total == 1
    card = (board.needs_you + board.in_flight)[0]
    assert card.stage is schemas.TaskStage.assigned
