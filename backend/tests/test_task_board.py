"""
The task board: assigned work joined to what Locus knows about it.

The board exists because the pipeline starts before a pull request does. The
tests that matter are the join and the stage derivation -- a card that fails
to find its own pull requests shows a ticket sitting at "assigned" while three
review rounds have already happened, which is worse than showing nothing.

Ordering deliberately mirrors the worklist's: needs-you first, then staleness.
The board reuses `worklist.build` rather than recomputing so the two cannot
disagree, and the last test here pins that reuse.
"""

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models, schemas
from app.services.pipeline import task_board

REPO, OWNER = "acme/widget", 1


@pytest.fixture
def db(tmp_path):
    from app.core.database import Base

    engine = create_engine(
        f"sqlite:///{tmp_path}/t.db", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _review(db, *, pr, state, tickets=None, rounds=1, hours_ago=1.0, owner=OWNER):
    review = models.PRReview(
        repo=REPO, pr_number=pr, pr_title=f"PR {pr}", author="junior-dev",
        state=state, round_number=rounds, ticket_keys=tickets,
        last_reviewer="senior-dev", owner_id=owner,
    )
    db.add(review)
    db.commit()
    review.created_at = datetime.now(UTC) - timedelta(hours=hours_ago)
    review.updated_at = review.created_at
    db.commit()
    return review


def _item(key, *, source=schemas.TaskSource.jira, title="Retry the gate"):
    return schemas.AssignedItem(
        source=source, key=key, title=title,
        url=f"https://acme.atlassian.net/browse/{key}",
    )


async def _build(db, items, *, owner=OWNER, monkeypatch=None):
    """Build a board with the assigned lookup stubbed out."""
    async def fake_fetch(configs, *, done=False):
        # The completed-work query is a second call to the same function.
        # These cases are about the open board, so it answers with nothing.
        return ([], []) if done else (items, [])

    monkeypatch.setattr(task_board, "fetch_assigned", fake_fetch)
    return await task_board.build(db, owner_id=owner, integration_configs={})


class TestJoining:
    @pytest.mark.asyncio
    async def test_ticket_finds_its_pull_requests(self, db, monkeypatch):
        """The key recorded by the analysis is the join. Nothing new is derived."""
        _review(db, pr=1, state="awaiting_review", tickets="LOC-431")
        _review(db, pr=2, state="changes_requested", tickets="LOC-431")

        board = await _build(db, [_item("LOC-431")], monkeypatch=monkeypatch)
        card = (board.needs_you + board.in_flight)[0]

        assert [pr.pr_number for pr in card.pull_requests] == [1, 2]

    @pytest.mark.asyncio
    async def test_ticket_with_no_pull_request_still_appears(self, db, monkeypatch):
        """Work assigned but not started is exactly what the board adds."""
        board = await _build(db, [_item("LOC-9")], monkeypatch=monkeypatch)
        card = (board.needs_you + board.in_flight)[0]

        assert card.stage is schemas.TaskStage.assigned
        assert card.pull_requests == []

    @pytest.mark.asyncio
    async def test_another_users_reviews_are_never_joined(self, db, monkeypatch):
        _review(db, pr=1, state="approved", tickets="LOC-431", owner=99)

        board = await _build(db, [_item("LOC-431")], monkeypatch=monkeypatch)
        card = (board.needs_you + board.in_flight)[0]

        assert card.pull_requests == []
        assert card.stage is schemas.TaskStage.assigned


class TestWorkItemKeyShape:
    """
    A GitHub issue's work-item key must carry its repository.

    The pipeline once recorded a linked issue as a bare "#5". The task board
    identifies the same issue as "owner/name#5" -- the shape
    `worklist._task_key` already falls back to -- so the two never matched and
    a card found neither its pull requests nor its messages. A bare "#5" is
    also ambiguous across repositories.
    """

    @pytest.mark.asyncio
    async def test_bare_issue_key_does_not_join(self, db, monkeypatch):
        """The regression, stated directly: this is what used to be stored."""
        db.add(models.CommunicationEvent(
            repo=REPO, pr_number=6, ticket_key="#5",
            loop="context", direction="received", channel="github",
            owner_id=OWNER,
        ))
        db.commit()

        board = await _build(
            db,
            [_item("acme/widget#5", source=schemas.TaskSource.github)],
            monkeypatch=monkeypatch,
        )
        card = (board.needs_you + board.in_flight)[0]

        assert card.pull_requests == []
        assert card.stage is schemas.TaskStage.assigned

    @pytest.mark.asyncio
    async def test_repo_qualified_key_joins(self, db, monkeypatch):
        db.add(models.CommunicationEvent(
            repo=REPO, pr_number=6, ticket_key="acme/widget#5",
            loop="context", direction="received", channel="github",
            owner_id=OWNER,
        ))
        db.commit()

        board = await _build(
            db,
            [_item("acme/widget#5", source=schemas.TaskSource.github)],
            monkeypatch=monkeypatch,
        )
        card = (board.needs_you + board.in_flight)[0]

        assert [pr.pr_number for pr in card.pull_requests] == [6]


class TestStageDerivation:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("state", "expected"),
        [
            ("awaiting_review", schemas.TaskStage.in_review),
            ("changes_requested", schemas.TaskStage.changes_requested),
            ("approved", schemas.TaskStage.approved),
            ("merged", schemas.TaskStage.merged),
        ],
    )
    async def test_review_state_maps_to_a_stage(
        self, db, monkeypatch, state, expected
    ):
        _review(db, pr=1, state=state, tickets="LOC-1")

        board = await _build(db, [_item("LOC-1")], monkeypatch=monkeypatch)
        card = (board.needs_you + board.in_flight)[0]

        assert card.stage is expected

    @pytest.mark.asyncio
    async def test_takes_the_furthest_pull_request(self, db, monkeypatch):
        """One ticket spans several PRs; the task is as far as its furthest."""
        _review(db, pr=1, state="awaiting_review", tickets="LOC-1")
        _review(db, pr=2, state="approved", tickets="LOC-1")

        board = await _build(db, [_item("LOC-1")], monkeypatch=monkeypatch)
        card = (board.needs_you + board.in_flight)[0]

        assert card.stage is schemas.TaskStage.approved

    @pytest.mark.asyncio
    async def test_qa_thread_moves_it_to_testing(self, db, monkeypatch):
        _review(db, pr=1, state="merged", tickets="LOC-1")
        db.add(models.QAThread(
            repo=REPO, pr_number=1, pr_url="u", resolved=0,
            ticket_keys_json=json.dumps(["LOC-1"]), owner_id=OWNER,
        ))
        db.commit()

        board = await _build(db, [_item("LOC-1")], monkeypatch=monkeypatch)
        card = (board.needs_you + board.in_flight)[0]

        assert card.stage is schemas.TaskStage.testing

    @pytest.mark.asyncio
    async def test_resolved_qa_is_done(self, db, monkeypatch):
        _review(db, pr=1, state="merged", tickets="LOC-1")
        db.add(models.QAThread(
            repo=REPO, pr_number=1, pr_url="u", resolved=1,
            ticket_keys_json=json.dumps(["LOC-1"]), owner_id=OWNER,
        ))
        db.commit()

        board = await _build(db, [_item("LOC-1")], monkeypatch=monkeypatch)
        card = (board.needs_you + board.in_flight)[0]

        assert card.stage is schemas.TaskStage.done


class TestTheRetryAfterQARejectedIt:
    """
    The round trip this pipeline exists to automate: a change merges, the
    testing team says it is broken, the ticket reopens, and the fix arrives as
    a fresh pull request that has to go back through the senior dev.

    The board used to read that whole second review round as "with the testing
    team" -- the rejected QA thread stays unresolved by design, and it was
    consulted before the reviews -- or as "merged", because the first attempt
    outranked the live one. Both say the work is further along than it is, at
    the exact moment someone is looking to find out what to do next.
    """

    @pytest.mark.asyncio
    async def test_the_fix_awaiting_review_is_not_still_in_testing(
        self, db, monkeypatch
    ):
        _review(db, pr=1, state="merged", tickets="LOC-1")
        # Rejected by QA: the thread stays unresolved, deliberately and
        # permanently -- nothing ever sets it back.
        db.add(models.QAThread(
            repo=REPO, pr_number=1, pr_url="u", resolved=0,
            ticket_keys_json=json.dumps(["LOC-1"]), owner_id=OWNER,
        ))
        db.commit()
        _review(db, pr=2, state="awaiting_review", tickets="LOC-1")

        board = await _build(db, [_item("LOC-1")], monkeypatch=monkeypatch)
        card = (board.needs_you + board.in_flight)[0]

        assert card.stage is schemas.TaskStage.in_review

    @pytest.mark.asyncio
    async def test_the_fix_is_not_reported_as_merged(self, db, monkeypatch):
        """
        Without a QA thread the first attempt still outranked the second: the
        stage was the furthest state any pull request had ever reached, so a
        merged first attempt beat a live second one.
        """
        _review(db, pr=1, state="merged", tickets="LOC-1")
        _review(db, pr=2, state="changes_requested", tickets="LOC-1")

        board = await _build(db, [_item("LOC-1")], monkeypatch=monkeypatch)
        card = (board.needs_you + board.in_flight)[0]

        assert card.stage is schemas.TaskStage.changes_requested

    @pytest.mark.asyncio
    async def test_the_round_trip_on_the_first_attempt_is_still_shown(
        self, db, monkeypatch
    ):
        """
        `changes_requested` is a conditional stage -- rendered only when it
        actually happened. It happened on the first attempt, so the stepper
        must still show it even though the current attempt has not been
        through a round yet.
        """
        first = _review(db, pr=1, state="merged", tickets="LOC-1")
        first.rounds.append(models.PRReviewRound(
            round_number=1,
            outcome=schemas.ReviewOutcome.changes_requested.value,
        ))
        db.commit()
        _review(db, pr=2, state="awaiting_review", tickets="LOC-1")

        board = await _build(db, [_item("LOC-1")], monkeypatch=monkeypatch)
        card = (board.needs_you + board.in_flight)[0]

        assert schemas.TaskStage.changes_requested in {s.stage for s in card.stages}

    @pytest.mark.asyncio
    async def test_once_the_fix_merges_it_goes_back_to_testing(
        self, db, monkeypatch
    ):
        """
        The other direction has to keep working: with nothing in flight, the
        QA thread decides again.
        """
        _review(db, pr=1, state="merged", tickets="LOC-1")
        _review(db, pr=2, state="merged", tickets="LOC-1")
        db.add(models.QAThread(
            repo=REPO, pr_number=2, pr_url="u", resolved=0,
            ticket_keys_json=json.dumps(["LOC-1"]), owner_id=OWNER,
        ))
        db.commit()

        board = await _build(db, [_item("LOC-1")], monkeypatch=monkeypatch)
        card = (board.needs_you + board.in_flight)[0]

        assert card.stage is schemas.TaskStage.testing


class TestPullRequestsBeforeReview:
    """
    A `PRReview` row appears only when someone requests a review. Everything
    before that -- the PR opened, the analysis run, the bot's comment -- is
    recorded against the work item in the message log instead. A board that
    joined only on review rows showed an open, analyzed pull request as
    "assigned", as though nobody had started.
    """

    @pytest.mark.asyncio
    async def test_open_pr_with_no_review_is_in_progress(self, db, monkeypatch):
        db.add(models.CommunicationEvent(
            repo=REPO, pr_number=6, ticket_key="acme/widget#5",
            loop="context", direction="received", channel="github",
            owner_id=OWNER,
        ))
        db.commit()

        board = await _build(
            db,
            [_item("acme/widget#5", source=schemas.TaskSource.github)],
            monkeypatch=monkeypatch,
        )
        card = (board.needs_you + board.in_flight)[0]

        assert card.stage is schemas.TaskStage.in_progress
        assert [pr.pr_number for pr in card.pull_requests] == [6]

    @pytest.mark.asyncio
    async def test_analyzed_pr_with_no_review_is_analyzed(self, db, monkeypatch):
        db.add(models.CommunicationEvent(
            repo=REPO, pr_number=6, ticket_key="acme/widget#5",
            loop="context", direction="received", channel="github",
            owner_id=OWNER,
        ))
        db.add(models.PRJob(
            repo=REPO, pr_number=6, action="opened",
            status=schemas.PRJobStatus.completed.value, owner_id=OWNER,
        ))
        db.commit()

        board = await _build(
            db,
            [_item("acme/widget#5", source=schemas.TaskSource.github)],
            monkeypatch=monkeypatch,
        )
        card = (board.needs_you + board.in_flight)[0]

        assert card.stage is schemas.TaskStage.analyzed

    @pytest.mark.asyncio
    async def test_a_reviewed_pr_is_not_listed_twice(self, db, monkeypatch):
        """The review row and the log describe the same pull request."""
        _review(db, pr=6, state="awaiting_review", tickets="acme/widget#5")
        db.add(models.CommunicationEvent(
            repo=REPO, pr_number=6, ticket_key="acme/widget#5",
            loop="context", direction="received", channel="github",
            owner_id=OWNER,
        ))
        db.commit()

        board = await _build(
            db,
            [_item("acme/widget#5", source=schemas.TaskSource.github)],
            monkeypatch=monkeypatch,
        )
        card = (board.needs_you + board.in_flight)[0]

        assert [pr.pr_number for pr in card.pull_requests] == [6]
        assert card.pull_requests[0].review_state is not None


class TestStepper:
    @pytest.mark.asyncio
    async def test_renders_every_stage_including_unreached(self, db, monkeypatch):
        """The card shows the whole pipeline, not only what has happened."""
        _review(db, pr=1, state="awaiting_review", tickets="LOC-1")

        board = await _build(db, [_item("LOC-1")], monkeypatch=monkeypatch)
        card = (board.needs_you + board.in_flight)[0]

        assert [s.stage for s in card.stages][-1] is schemas.TaskStage.done
        assert any(s.state == schemas.StageState.running for s in card.stages)
        assert any(s.state == schemas.StageState.pending for s in card.stages)

    @pytest.mark.asyncio
    async def test_omits_changes_requested_when_it_never_happened(
        self, db, monkeypatch
    ):
        """A greyed-out step implies a round trip that did not occur."""
        _review(db, pr=1, state="approved", tickets="LOC-1")

        board = await _build(db, [_item("LOC-1")], monkeypatch=monkeypatch)
        card = (board.needs_you + board.in_flight)[0]

        assert schemas.TaskStage.changes_requested not in [
            s.stage for s in card.stages
        ]

    @pytest.mark.asyncio
    async def test_includes_changes_requested_once_it_has(self, db, monkeypatch):
        _review(db, pr=1, state="changes_requested", tickets="LOC-1")

        board = await _build(db, [_item("LOC-1")], monkeypatch=monkeypatch)
        card = (board.needs_you + board.in_flight)[0]

        assert schemas.TaskStage.changes_requested in [s.stage for s in card.stages]


class TestAttention:
    @pytest.mark.asyncio
    async def test_changes_requested_needs_you(self, db, monkeypatch):
        """Reused from worklist.build, so the two cannot disagree."""
        _review(db, pr=1, state="changes_requested", tickets="LOC-1")

        board = await _build(db, [_item("LOC-1")], monkeypatch=monkeypatch)

        assert [c.key for c in board.needs_you] == ["LOC-1"]
        assert board.needs_you[0].blocked_reason

    @pytest.mark.asyncio
    async def test_awaiting_review_waits_on_someone_else(self, db, monkeypatch):
        _review(db, pr=1, state="awaiting_review", tickets="LOC-1")

        board = await _build(db, [_item("LOC-1")], monkeypatch=monkeypatch)

        assert [c.key for c in board.in_flight] == ["LOC-1"]

    @pytest.mark.asyncio
    async def test_stalest_blocked_task_ranks_first(self, db, monkeypatch):
        """Staleness ranks conversations; a week-old round trip is the signal."""
        _review(db, pr=1, state="changes_requested", tickets="LOC-NEW", hours_ago=2)
        _review(db, pr=2, state="changes_requested", tickets="LOC-OLD", hours_ago=200)

        board = await _build(
            db, [_item("LOC-NEW"), _item("LOC-OLD")], monkeypatch=monkeypatch
        )

        assert [c.key for c in board.needs_you] == ["LOC-OLD", "LOC-NEW"]


class TestSourceDegradation:
    @pytest.mark.asyncio
    async def test_a_dead_source_is_reported_not_hidden(self, db, monkeypatch):
        """"Nothing assigned" and "Jira is down" must not look identical."""
        async def fake_fetch(configs, *, done=False):
            return ([], []) if done else ([_item("LOC-1")], ["jira"])

        monkeypatch.setattr(task_board, "fetch_assigned", fake_fetch)
        board = await task_board.build(
            db, owner_id=OWNER, integration_configs={}
        )

        assert board.jira_available is False
        assert board.github_available is True
        assert board.unavailable == ["jira"]


class TestAuthoringStage:
    """
    The `authoring` step, and where it ranks.

    Rendered only when the resolved mode is autonomous -- the same rule
    `changes_requested` follows, because a greyed-out step implies a step that
    was skipped where in fact it was never available.
    """

    def test_the_step_is_absent_on_an_assisted_task(self, db):
        from app.services.pipeline.task_board import _build_stages

        stages = _build_stages(
            schemas.TaskStage.assigned, False, [], [], autonomous=False
        )

        assert not any(s.stage is schemas.TaskStage.authoring for s in stages)

    def test_the_step_is_rendered_on_an_autonomous_task(self, db):
        from app.services.pipeline.task_board import _build_stages

        stages = _build_stages(
            schemas.TaskStage.assigned, False, [], [], autonomous=True
        )

        assert any(s.stage is schemas.TaskStage.authoring for s in stages)

    def test_the_stepper_can_never_omit_its_own_current_stage(self, db):
        """
        Deriving the step from the current stage as well is what makes this
        impossible, rather than merely unlikely.
        """
        from app.services.pipeline.task_board import _build_stages

        stages = _build_stages(
            schemas.TaskStage.authoring, False, [], [], autonomous=False
        )

        assert any(s.stage is schemas.TaskStage.authoring for s in stages)

    def test_an_attempt_ranks_below_a_linked_branch(self, db):
        """
        The attempt row is append-only and stays behind forever, so a rule
        letting it win would walk a reviewed card back to "Locus is writing it"
        on every refresh.
        """
        from app.services.pipeline.task_board import _derive_stage

        stage, _ = _derive_stage(
            [], None, False, has_pr=False, has_branch=True, has_attempt=True
        )

        assert stage is schemas.TaskStage.branch_created

    def test_an_attempt_ranks_below_every_pull_request_stage(self, db):
        from app.services.pipeline.task_board import _derive_stage

        stage, _ = _derive_stage(
            [], None, False, has_pr=True, has_branch=False, has_attempt=True
        )

        assert stage is schemas.TaskStage.in_progress

    def test_an_attempt_alone_beats_assigned(self, db):
        """
        A ticket the agent is actively writing has not "not started", which is
        what `assigned` claims.
        """
        from app.services.pipeline.task_board import _derive_stage

        stage, _ = _derive_stage(
            [], None, False, has_pr=False, has_branch=False, has_attempt=True
        )

        assert stage is schemas.TaskStage.authoring

    def test_the_step_counts_the_attempts(self, db):
        from app.services.pipeline.task_board import _build_stages

        stages = _build_stages(
            schemas.TaskStage.authoring, False, [], [], autonomous=True,
            attempts=3,
        )

        step = next(s for s in stages if s.stage is schemas.TaskStage.authoring)
        assert step.detail == "3 attempts"
