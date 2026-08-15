"""
The senior-dev review loop.

The pipeline covered "PR opened" and "PR merged" but nothing in between, which
is where the time actually goes: a senior dev asks for changes, the author
pushes, the senior dev looks again. GitHub emits each of those as an isolated
event and remembers nothing between them, so the round count and the current
state are only correct if this module accumulates them properly.

These tests pin the state machine, the round arithmetic, and the two places a
naive implementation gets it wrong: counting pushes that are not resubmissions,
and letting a drive-by comment inflate the round count.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models, schemas
from app.services import review_flow


@pytest.fixture
def db(tmp_path):
    from app.database import Base

    engine = create_engine(
        f"sqlite:///{tmp_path}/review.db", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    try:
        yield session
    finally:
        session.close()


REPO = "acme/widget"
PR = 42
OWNER = 1


async def _changes_requested(db, body="Please add a test.", reviewer="senior-dev"):
    """Submit a changes-requested review with the summarizer stubbed out."""
    return await review_flow.record_review_submitted(
        db,
        owner_id=OWNER,
        repo=REPO,
        pr_number=PR,
        review_state="changes_requested",
        reviewer=reviewer,
        body=body,
        author="junior-dev",
    )


@pytest.fixture(autouse=True)
def no_model(monkeypatch):
    """
    Never call a model in these tests.

    summarize_asks already degrades to [] when the model is unreachable, so an
    un-stubbed test would pass for the wrong reason -- it would exercise the
    failure path while looking like it exercised the success path.
    """
    async def fake(body: str) -> list[str]:
        return ["Add a test"] if body else []

    monkeypatch.setattr(review_flow, "summarize_asks", fake)


class TestStateMachine:
    @pytest.mark.asyncio
    async def test_changes_requested_blocks_and_records_asks(self, db):
        review = await _changes_requested(db)

        assert review.state == schemas.ReviewState.changes_requested.value
        assert review.round_number == 1
        assert review.last_reviewer == "senior-dev"
        assert review.pending_asks == "Add a test"

    @pytest.mark.asyncio
    async def test_approval_clears_the_gate_and_the_asks(self, db):
        await _changes_requested(db)

        review = await review_flow.record_review_submitted(
            db,
            owner_id=OWNER,
            repo=REPO,
            pr_number=PR,
            review_state="approved",
            reviewer="senior-dev",
            body="",
        )

        assert review.state == schemas.ReviewState.approved.value
        # An approved PR showing a list of unfinished work reads as blocked.
        assert review.pending_asks is None

    @pytest.mark.asyncio
    async def test_commented_review_is_recorded_but_does_not_move_state(self, db):
        await _changes_requested(db)

        review = await review_flow.record_review_submitted(
            db,
            owner_id=OWNER,
            repo=REPO,
            pr_number=PR,
            review_state="commented",
            reviewer="passer-by",
            body="Nice work.",
        )

        # Still blocked: a comment carries no verdict either way.
        assert review.state == schemas.ReviewState.changes_requested.value
        assert review.round_number == 1
        # But it is in the history.
        assert any(
            r.outcome == schemas.ReviewOutcome.commented.value for r in review.rounds
        )

    @pytest.mark.asyncio
    async def test_dismissed_review_is_ignored(self, db):
        """A dismissal revokes a verdict without supplying a new one."""
        result = await review_flow.record_review_submitted(
            db,
            owner_id=OWNER,
            repo=REPO,
            pr_number=PR,
            review_state="dismissed",
            reviewer="senior-dev",
            body="",
        )

        assert result is None


class TestRoundArithmetic:
    @pytest.mark.asyncio
    async def test_push_after_changes_requested_opens_the_next_round(self, db):
        await _changes_requested(db)

        review = review_flow.record_resubmission(
            db, owner_id=OWNER, repo=REPO, pr_number=PR, head_sha="deadbee"
        )

        assert review is not None
        assert review.round_number == 2
        assert review.state == schemas.ReviewState.awaiting_review.value

    def test_push_without_a_prior_review_does_not_count(self, db):
        """
        Ordinary development is not a resubmission.

        Counting every push would make the round number a commit counter, and
        a PR nobody has looked at would show as round nine.
        """
        result = review_flow.record_resubmission(
            db, owner_id=OWNER, repo=REPO, pr_number=PR, head_sha="abc1234"
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_push_while_awaiting_review_does_not_open_a_round(self, db):
        """
        A push before the reviewer has responded goes back to them, but does
        not open a new round: they have not finished this one, and counting
        each push would turn the round number into a commit counter.

        This test previously set up an *approved* review while describing the
        awaiting-review case, and asserted nothing happened -- which is how a
        push over an approval went unnoticed. Both cases are covered
        separately now; see TestPushAfterApproval.
        """
        review_flow.record_review_requested(
            db, owner_id=OWNER, repo=REPO, pr_number=PR, reviewer="senior-dev"
        )

        review = review_flow.record_resubmission(
            db, owner_id=OWNER, repo=REPO, pr_number=PR, head_sha="abc1234"
        )

        # Reported, so the reviewer learns the diff moved under them...
        assert review is not None
        # ...but still round one.
        assert review.round_number == 1
        assert review.state == schemas.ReviewState.awaiting_review.value

    @pytest.mark.asyncio
    async def test_full_loop_accumulates_rounds(self, db):
        """Three trips through the loop, ending approved on round three."""
        await _changes_requested(db, body="Round one asks.")
        review_flow.record_resubmission(db, owner_id=OWNER, repo=REPO, pr_number=PR)

        await _changes_requested(db, body="Round two asks.")
        review_flow.record_resubmission(db, owner_id=OWNER, repo=REPO, pr_number=PR)

        review = await review_flow.record_review_submitted(
            db,
            owner_id=OWNER,
            repo=REPO,
            pr_number=PR,
            review_state="approved",
            reviewer="senior-dev",
            body="",
        )

        assert review.round_number == 3
        assert review.state == schemas.ReviewState.approved.value

        detail = review_flow.to_detail(review)
        outcomes = [r.outcome.value for r in detail.rounds]
        assert outcomes == [
            "changes_requested",
            "resubmitted",
            "changes_requested",
            "resubmitted",
            "approved",
        ]


class TestPushAfterApproval:
    """
    An approval describes a diff. When the diff changes, the approval no
    longer covers it.

    This is the one path that writes to a default branch with nobody in the
    loop: `automerge.sweep_once` re-evaluates the gate every minute, so a
    pull request left `approved` after a push gets merged carrying commits no
    human ever read. Nothing about that is visible afterwards -- the merge
    looks exactly like an approved one.
    """

    @pytest.mark.asyncio
    async def test_a_push_withdraws_the_approval(self, db):
        await review_flow.record_review_submitted(
            db, owner_id=OWNER, repo=REPO, pr_number=PR,
            review_state="approved", reviewer="senior-dev", body="",
        )

        review = review_flow.record_resubmission(
            db, owner_id=OWNER, repo=REPO, pr_number=PR, head_sha="newsha"
        )

        assert review is not None
        assert review.state == schemas.ReviewState.awaiting_review.value

    @pytest.mark.asyncio
    async def test_the_merge_gate_closes_again(self, db):
        """The property that actually matters: unreviewed code cannot merge."""
        await review_flow.record_review_submitted(
            db, owner_id=OWNER, repo=REPO, pr_number=PR,
            review_state="approved", reviewer="senior-dev", body="",
        )

        review = db.query(models.PRReview).one()
        allowed, _ = review_flow.evaluate_merge_gate(
            review, None, "success", [], True
        )
        assert allowed is True

        review_flow.record_resubmission(
            db, owner_id=OWNER, repo=REPO, pr_number=PR, head_sha="newsha"
        )

        db.refresh(review)
        allowed, blockers = review_flow.evaluate_merge_gate(
            review, None, "success", [], True
        )
        assert allowed is False
        assert any("not approved" in b for b in blockers)

    @pytest.mark.asyncio
    async def test_it_opens_a_new_round(self, db):
        """A re-review after approval is a genuine extra trip."""
        await review_flow.record_review_submitted(
            db, owner_id=OWNER, repo=REPO, pr_number=PR,
            review_state="approved", reviewer="senior-dev", body="",
        )

        review = review_flow.record_resubmission(
            db, owner_id=OWNER, repo=REPO, pr_number=PR, head_sha="newsha"
        )

        assert review.round_number == 2

    @pytest.mark.asyncio
    async def test_re_approving_lets_it_merge_again(self, db):
        """The withdrawal is not permanent; it just has to be earned again."""
        await review_flow.record_review_submitted(
            db, owner_id=OWNER, repo=REPO, pr_number=PR,
            review_state="approved", reviewer="senior-dev", body="",
        )
        review_flow.record_resubmission(
            db, owner_id=OWNER, repo=REPO, pr_number=PR, head_sha="newsha"
        )
        await review_flow.record_review_submitted(
            db, owner_id=OWNER, repo=REPO, pr_number=PR,
            review_state="approved", reviewer="senior-dev", body="",
        )

        review = db.query(models.PRReview).one()
        allowed, _ = review_flow.evaluate_merge_gate(
            review, None, "success", [], True
        )
        assert allowed is True

    @pytest.mark.asyncio
    async def test_a_push_after_merge_changes_nothing(self, db):
        """
        A merged pull request is terminal. A push to its branch afterwards
        belongs to whatever comes next, not to a review that is over.
        """
        await review_flow.record_review_submitted(
            db, owner_id=OWNER, repo=REPO, pr_number=PR,
            review_state="approved", reviewer="senior-dev", body="",
        )
        review_flow.record_merged(db, owner_id=OWNER, repo=REPO, pr_number=PR)

        assert review_flow.record_resubmission(
            db, owner_id=OWNER, repo=REPO, pr_number=PR, head_sha="newsha"
        ) is None

        review = db.query(models.PRReview).one()
        assert review.state == schemas.ReviewState.merged.value


class TestResubmissionMessaging:
    """
    A withdrawn approval reads very differently from "round 3 is ready".
    Reporting both the same way buries the one that needs attention on a pull
    request the reviewer thought was finished.
    """

    def test_a_revoked_approval_says_so(self, db):
        review = models.PRReview(
            repo=REPO, pr_number=PR, pr_title="Add retry logic",
            state=schemas.ReviewState.awaiting_review.value,
            round_number=2, owner_id=OWNER,
        )
        text = review_flow.format_review_notification(
            review, schemas.ReviewOutcome.resubmitted, "senior-dev", [],
            ["senior-dev"], resubmit_reason="approval_revoked",
        )

        assert "after approval" in text.lower()
        assert "withdrawn" in text.lower()

    def test_an_update_mid_review_says_so(self, db):
        review = models.PRReview(
            repo=REPO, pr_number=PR, state=schemas.ReviewState.awaiting_review.value,
            round_number=1, owner_id=OWNER,
        )
        text = review_flow.format_review_notification(
            review, schemas.ReviewOutcome.resubmitted, "senior-dev", [],
            ["senior-dev"], resubmit_reason="updated_during_review",
        )

        assert "updated while you were reviewing" in text.lower()

    def test_an_ordinary_round_is_unchanged(self, db):
        review = models.PRReview(
            repo=REPO, pr_number=PR, state=schemas.ReviewState.awaiting_review.value,
            round_number=3, owner_id=OWNER,
        )
        text = review_flow.format_review_notification(
            review, schemas.ReviewOutcome.resubmitted, "senior-dev", [],
            ["senior-dev"],
        )

        assert "ready for round 3" in text.lower()


class TestReviewRequested:
    def test_request_on_a_blocked_pr_returns_it_to_awaiting(self, db):
        review = review_flow.record_review_requested(
            db, owner_id=OWNER, repo=REPO, pr_number=PR, reviewer="senior-dev"
        )

        assert review.state == schemas.ReviewState.awaiting_review.value

    @pytest.mark.asyncio
    async def test_request_does_not_silently_unapprove(self, db):
        """
        Asking for a second opinion is normal.

        Dropping the approval as a side effect would make a merge-ready PR
        look blocked because someone wanted another pair of eyes.
        """
        await review_flow.record_review_submitted(
            db,
            owner_id=OWNER,
            repo=REPO,
            pr_number=PR,
            review_state="approved",
            reviewer="senior-dev",
            body="",
        )

        review = review_flow.record_review_requested(
            db, owner_id=OWNER, repo=REPO, pr_number=PR, reviewer="other-dev"
        )

        assert review.state == schemas.ReviewState.approved.value


class TestMergeClosesTheLoop:
    @pytest.mark.asyncio
    async def test_merge_is_terminal(self, db):
        await _changes_requested(db)

        review = review_flow.record_merged(
            db, owner_id=OWNER, repo=REPO, pr_number=PR
        )

        assert review.state == schemas.ReviewState.merged.value
        assert review.pending_asks is None

    def test_merge_without_a_review_invents_nothing(self, db):
        assert review_flow.record_merged(
            db, owner_id=OWNER, repo=REPO, pr_number=PR
        ) is None


class TestIsolation:
    @pytest.mark.asyncio
    async def test_another_users_review_is_not_visible(self, db):
        """
        Rows are scoped by owner.

        Two accounts watching the same public repo must not share review
        state -- the second one's lookup would otherwise return the first's.
        """
        await _changes_requested(db)

        other = review_flow.record_merged(
            db, owner_id=OWNER + 1, repo=REPO, pr_number=PR
        )

        assert other is None
        mine = db.query(models.PRReview).filter(
            models.PRReview.owner_id == OWNER
        ).one()
        assert mine.state == schemas.ReviewState.changes_requested.value


class TestAsksSummary:
    @pytest.mark.asyncio
    async def test_unavailable_model_yields_no_asks_rather_than_invented_ones(
        self, db, monkeypatch
    ):
        """
        An empty checklist reads as "see the review". A fabricated one does not.
        """
        monkeypatch.undo()  # restore the real summarize_asks

        def boom(*_args, **_kwargs):
            raise RuntimeError("model server is down")

        monkeypatch.setattr(review_flow, "get_llm", boom)

        assert await review_flow.summarize_asks("Please fix the retry logic.") == []

    @pytest.mark.asyncio
    async def test_empty_body_is_not_sent_to_the_model(self, db, monkeypatch):
        monkeypatch.undo()

        def boom(*_args, **_kwargs):
            raise AssertionError("should not call the model for an empty body")

        monkeypatch.setattr(review_flow, "get_llm", boom)

        assert await review_flow.summarize_asks("   ") == []


class TestNotificationText:
    @pytest.mark.asyncio
    async def test_changes_requested_addresses_the_author(self, db):
        review = await _changes_requested(db)

        text = review_flow.format_review_notification(
            review,
            schemas.ReviewOutcome.changes_requested,
            "senior-dev",
            ["Add a test"],
            ["senior-dev"],
        )

        assert "@senior-dev" in text
        assert "@junior-dev" in text  # the ball is with the author
        assert "round 1" in text
        assert "Add a test" in text


class TestAsksForQA:
    """
    What the reviewer asked for has to reach the testing team.

    The QA brief used to be built from the diff, the ticket and the security
    findings alone, so a change the reviewer asked for in plain English -- the
    most concrete statement of what the PR had to do -- never reached QA.
    """

    @pytest.mark.asyncio
    async def test_changes_requested_bodies_are_returned(self, db):
        await _changes_requested(db, body='add word "orange" too')

        asks = review_flow.asks_for_qa(
            db, owner_id=OWNER, repo=REPO, pr_number=PR
        )

        assert asks == ['add word "orange" too']

    @pytest.mark.asyncio
    async def test_asks_survive_the_merge(self, db):
        """
        record_merged clears pending_asks, and runs before the QA brief.

        Reading the append-only rounds rather than that field is what makes
        the asks still available at the moment QA is notified.
        """
        await _changes_requested(db, body='add word "orange" too')
        review_flow.record_merged(
            db, owner_id=OWNER, repo=REPO, pr_number=PR
        )

        asks = review_flow.asks_for_qa(
            db, owner_id=OWNER, repo=REPO, pr_number=PR
        )

        assert asks == ['add word "orange" too']

    @pytest.mark.asyncio
    async def test_every_round_is_carried_not_only_the_last(self, db):
        """
        A request satisfied in round two is still something QA verifies.
        """
        await _changes_requested(db, body="add orange")
        await _changes_requested(db, body="rename the heading")

        asks = review_flow.asks_for_qa(
            db, owner_id=OWNER, repo=REPO, pr_number=PR
        )

        assert asks == ["add orange", "rename the heading"]

    @pytest.mark.asyncio
    async def test_a_restated_request_is_listed_once(self, db):
        await _changes_requested(db, body="add orange")
        await _changes_requested(db, body="Add Orange")

        asks = review_flow.asks_for_qa(
            db, owner_id=OWNER, repo=REPO, pr_number=PR
        )

        assert asks == ["add orange"]

    @pytest.mark.asyncio
    async def test_an_approval_contributes_nothing(self, db):
        """Only requested changes are asks; an approval requests nothing."""
        await review_flow.record_review_submitted(
            db, owner_id=OWNER, repo=REPO, pr_number=PR,
            review_state="approved", reviewer="senior-dev", body="LGTM",
        )

        assert review_flow.asks_for_qa(
            db, owner_id=OWNER, repo=REPO, pr_number=PR
        ) == []

    def test_an_unreviewed_pr_has_no_asks(self, db):
        assert review_flow.asks_for_qa(
            db, owner_id=OWNER, repo=REPO, pr_number=999
        ) == []
