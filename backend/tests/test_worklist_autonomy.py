"""
Work the agent is handling is not work that needs you.

`blocked_on_you` was unconditionally true for a reviewer's changes-requested
and for a QA rejection. In autonomous mode with the matching auto-start trigger
on, neither is blocked on anyone -- the agent picks it up within seconds of the
webhook, and the card read "Needs you" while the agent was already writing the
fix.

That is the failure `worklist`'s own docstring names: "a list that shows things
which do not actually need you is ignored within a week, and once ignored it is
very hard to win back". Crying wolf on the one kind of item the pipeline exists
to handle automatically is the fastest route there.

The tests below matter in both directions. Every reason the agent might *not*
pick it up has to leave the item on you, because the opposite failure -- a queue
that quietly hides work nobody is doing -- is the worse one.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models, schemas
from app.services.authoring import agent_runtime
from app.services.pipeline import worklist

OWNER = 1
REPO = "acme/api"
KEY = "acme/api#7"


@pytest.fixture
def db(tmp_path):
    from app.core.database import Base

    engine = create_engine(
        f"sqlite:///{tmp_path}/w.db", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def a_real_driver(monkeypatch):
    """
    A driver is configured. Without one nothing is automated and every item is
    correctly yours, which would make every test below pass for the wrong
    reason.
    """
    monkeypatch.setenv("LOCUS_AUTHORING_DRIVER", "opencode")
    agent_runtime.clear()
    yield
    agent_runtime.clear()


def _setup(db, *, mode="autonomous", rounds=3, attempts=0, handed_back=False, **flags):
    db.add(models.RepoWebhook(
        repo=REPO, encrypted_secret="x", enabled=1, owner_id=OWNER,
        authoring_mode=mode, autonomous_max_rounds=rounds,
    ))
    db.add(models.PRAgentDefaults(
        owner_id=OWNER,
        auto_start_on_review=1 if flags.get("review", True) else 0,
        auto_start_on_qa=1 if flags.get("qa", True) else 0,
    ))
    if handed_back:
        db.add(models.WorkItemSettings(
            owner_id=OWNER, ticket_key=KEY, authoring_mode=mode,
            handed_back_at=datetime(2026, 9, 1, tzinfo=UTC),
            handed_back_reason="out of tries",
        ))
    for n in range(attempts):
        db.add(models.AuthoringAttempt(
            owner_id=OWNER, ticket_key=KEY, repo=REPO,
            attempt=n + 1, trigger="qa_rejected",
        ))
    db.commit()


def handles(db, trigger="qa"):
    return worklist._agent_handles(
        db, owner_id=OWNER, repo=REPO, ticket_key=KEY, trigger=trigger, cache={}
    )


class TestTheAgentIsHandlingIt:
    def test_a_qa_rejection_in_autonomous_mode_is_not_yours(self, db):
        """The reported bug: the card said Needs you mid-rework."""
        _setup(db)
        assert handles(db) is True

    def test_a_changes_requested_review_is_not_yours_either(self, db):
        """Same shape, one loop earlier."""
        _setup(db)
        assert handles(db, trigger="review") is True


class TestEveryReasonItIsStillYours:
    """
    The other direction, and the one that must not regress. A queue that hides
    work nobody is doing is worse than one that over-reports.
    """

    def test_assisted_mode_is_yours(self, db):
        _setup(db, mode="assisted")
        assert handles(db) is False

    def test_the_trigger_being_off_is_yours(self, db):
        """
        The mode says the agent *may* write it; the trigger says nobody has to
        press the button. With the trigger off a person still starts it.
        """
        _setup(db, qa=False)
        assert handles(db) is False

    def test_a_spent_bound_is_yours(self, db):
        """
        The case that made this hard to see on a real card: the mode and the
        trigger are both on, and the agent still cannot act.
        """
        _setup(db, rounds=2, attempts=3)
        assert handles(db) is False

    def test_a_handed_back_item_is_yours(self, db):
        _setup(db, handed_back=True)
        assert handles(db) is False

    def test_no_driver_configured_is_yours(self, db, monkeypatch):
        monkeypatch.setenv("LOCUS_AUTHORING_DRIVER", "none")
        agent_runtime.clear()
        _setup(db)
        assert handles(db) is False

    def test_a_work_item_with_no_key_is_yours(self, db):
        """
        `maybe_retry` refuses a missing key rather than guessing one, so the
        agent cannot be handed this even in principle.
        """
        _setup(db)
        assert worklist._agent_handles(
            db, owner_id=OWNER, repo=REPO, ticket_key=None,
            trigger="qa", cache={},
        ) is False

    def test_a_failure_to_decide_is_yours(self, db, monkeypatch):
        """
        If we cannot tell, say it needs you. Failing towards the visible
        outcome is the whole point.
        """
        def boom(*_a, **_kw):
            raise RuntimeError("settings unavailable")

        monkeypatch.setattr(
            "app.services.pipeline.agent_settings.resolve_settings", boom
        )
        _setup(db)
        assert handles(db) is False


class TestTheDecisionIsCachedPerWorkItem:
    def test_the_cache_is_consulted(self, db):
        """
        The board renders every assigned item and this resolves settings and
        counts attempts for each, so the same work item must be decided once.
        """
        _setup(db)
        cache: dict = {}

        first = worklist._agent_handles(
            db, owner_id=OWNER, repo=REPO, ticket_key=KEY,
            trigger="qa", cache=cache,
        )

        # Poison the underlying resolution: a second call that reached it would
        # now raise and be swallowed into False.
        cache[(REPO, KEY, "qa")] = first
        assert worklist._agent_handles(
            db, owner_id=OWNER, repo=REPO, ticket_key=KEY,
            trigger="qa", cache=cache,
        ) is first

    def test_review_and_qa_are_cached_separately(self, db):
        """
        They resolve different settings and different `continuing` semantics,
        so one must not answer for the other.
        """
        _setup(db, qa=False, review=True)
        cache: dict = {}

        assert worklist._agent_handles(
            db, owner_id=OWNER, repo=REPO, ticket_key=KEY,
            trigger="qa", cache=cache,
        ) is False
        assert worklist._agent_handles(
            db, owner_id=OWNER, repo=REPO, ticket_key=KEY,
            trigger="review", cache=cache,
        ) is True


class TestARejectionAnsweredByAMergeIsHistory:
    """
    The fourth cause of a false "Needs you", found on a real card once the
    other three were fixed. The tester said it did not work, the agent wrote
    the fix, and it merged -- and the original rejection was still reported,
    so a work item that had completed its whole round trip read as needing a
    person.

    Keyed on the merge being *newer* than the rejection, not merely existing:
    the pull request the tester rejected is older than their reply, and
    treating that as the answer would silence every rejection ever made.
    """

    def _rejection(self, db, when):
        db.add(models.CommunicationEvent(
            owner_id=OWNER, repo=REPO, pr_number=8, ticket_key=KEY,
            loop="qa", direction="received", channel="slack",
            outcome="broken", body="didnt work", created_at=when,
        ))

    def _merged_pr(self, db, pr_number, when):
        db.add(models.PRReview(
            owner_id=OWNER, repo=REPO, pr_number=pr_number,
            state="merged", round_number=1, ticket_keys=KEY,
            created_at=when, updated_at=when,
        ))

    def _has_rejection(self, db) -> bool:
        """
        Whether a `qa_rejected` item exists for this work item at all.

        The item's presence rather than `needs_you`, deliberately: with the
        agent handling it the item is present but not blocked on you, and this
        class is about whether the rejection is still *reported* -- a different
        question from whose desk it lands on.
        """
        board = worklist.build(db, owner_id=OWNER)
        return any(
            item.kind is schemas.WorklistKind.qa_rejected
            for task in [*board.needs_you, *board.waiting_on_others]
            if task.key == KEY
            for item in task.items
        )

    def test_a_later_merge_answers_the_rejection(self, db):
        _setup(db)
        self._rejection(db, datetime(2026, 9, 6, 12, 0, tzinfo=UTC))
        self._merged_pr(db, 10, datetime(2026, 9, 6, 12, 30, tzinfo=UTC))
        db.commit()

        assert self._has_rejection(db) is False

    def test_the_merge_the_tester_rejected_does_not_answer_it(self, db):
        """
        The case that makes this a *later* merge rather than any merge. The
        rejected pull request merged before the tester replied; treating it as
        the answer would hide every rejection there has ever been.
        """
        _setup(db)
        self._merged_pr(db, 8, datetime(2026, 9, 6, 11, 0, tzinfo=UTC))
        self._rejection(db, datetime(2026, 9, 6, 12, 0, tzinfo=UTC))
        db.commit()

        assert self._has_rejection(db) is True

    def test_a_merge_on_a_different_work_item_does_not_answer_it(self, db):
        _setup(db)
        self._rejection(db, datetime(2026, 9, 6, 12, 0, tzinfo=UTC))
        db.add(models.PRReview(
            owner_id=OWNER, repo=REPO, pr_number=99, state="merged",
            round_number=1, ticket_keys="acme/api#999",
            created_at=datetime(2026, 9, 6, 12, 30, tzinfo=UTC),
            updated_at=datetime(2026, 9, 6, 12, 30, tzinfo=UTC),
        ))
        db.commit()

        assert self._has_rejection(db) is True

    def test_a_merge_by_another_account_does_not_answer_it(self, db):
        """
        Scoped to the owner like every other lookup, after nine of these were
        found falling back past it.
        """
        _setup(db)
        self._rejection(db, datetime(2026, 9, 6, 12, 0, tzinfo=UTC))
        db.add(models.PRReview(
            owner_id=OWNER + 1, repo=REPO, pr_number=10, state="merged",
            round_number=1, ticket_keys=KEY,
            created_at=datetime(2026, 9, 6, 12, 30, tzinfo=UTC),
            updated_at=datetime(2026, 9, 6, 12, 30, tzinfo=UTC),
        ))
        db.commit()

        assert self._has_rejection(db) is True
