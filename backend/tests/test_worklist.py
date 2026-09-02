"""
Phase 6: the worklist.

The dashboard answers "what happened on PR #42". This answers "across
everything open, what is waiting on me" -- which meant expanding six pull
requests to find the two that needed action.

The tests that matter are the ordering ones. A worklist that shows things not
actually needing you is ignored within a week, and one that ranks a fresh
first-round comment above a task stuck on round five for days has lost the
signal it exists to surface.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models, schemas
from app.services.pipeline import comms_log, worklist

REPO, OWNER = "acme/widget", 1


@pytest.fixture
def db(tmp_path):
    from app.core.database import Base

    engine = create_engine(
        f"sqlite:///{tmp_path}/w.db", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _review(db, *, pr, state, tickets=None, rounds=1, asks=None,
            hours_ago=1.0, reviewer="senior-dev", body=None):
    review = models.PRReview(
        repo=REPO, pr_number=pr, pr_title=f"PR {pr}", author="junior-dev",
        state=state, round_number=rounds, pending_asks=asks,
        ticket_keys=tickets, last_reviewer=reviewer, owner_id=OWNER,
    )
    db.add(review)
    db.flush()
    if body:
        db.add(models.PRReviewRound(
            review_id=review.id, round_number=rounds,
            outcome="changes_requested", reviewer=reviewer, body=body,
        ))
    db.commit()
    review.created_at = datetime.now(UTC) - timedelta(hours=hours_ago)
    review.updated_at = review.created_at
    db.commit()
    return review


class TestGrouping:
    def test_pull_requests_on_one_ticket_become_one_task(self, db):
        """
        A ticket spanning three PRs is one thing that has been running for
        weeks, not three unrelated young items.
        """
        _review(db, pr=42, state="changes_requested", tickets="LOC-42", asks="fix it")
        _review(db, pr=57, state="changes_requested", tickets="LOC-42", asks="again")

        result = worklist.build(db, owner_id=OWNER)

        assert len(result.needs_you) == 1
        task = result.needs_you[0]
        assert task.key == "LOC-42"
        assert sorted(task.pull_requests) == [42, 57]
        assert len(task.items) == 2

    def test_a_pr_without_a_ticket_still_appears(self, db):
        """
        Dropping untracked work would hide real work rather than tidy the
        list. It falls back to identifying itself by PR.
        """
        _review(db, pr=9, state="changes_requested", tickets=None, asks="x")

        result = worklist.build(db, owner_id=OWNER)

        assert result.needs_you[0].key == f"{REPO}#9"

    def test_merged_reviews_drop_out(self, db):
        _review(db, pr=1, state="merged", tickets="LOC-1")

        result = worklist.build(db, owner_id=OWNER)

        assert result.needs_you == []
        assert result.waiting_on_others == []


class TestBlockedOnWho:
    def test_changes_requested_needs_you(self, db):
        _review(db, pr=42, state="changes_requested", asks="add a test")

        result = worklist.build(db, owner_id=OWNER)

        assert result.needs_you
        assert result.needs_you[0].items[0].kind == schemas.WorklistKind.changes_requested

    def test_awaiting_review_is_waiting_on_someone_else(self, db):
        """
        Visible, but not competing for attention with things you can act on.
        """
        _review(db, pr=42, state="awaiting_review")

        result = worklist.build(db, owner_id=OWNER)

        assert result.needs_you == []
        assert len(result.waiting_on_others) == 1

    def test_approved_but_unmerged_needs_you(self, db):
        """Either auto-merge is off, or the gate is holding on something."""
        _review(db, pr=42, state="approved")

        result = worklist.build(db, owner_id=OWNER)

        assert result.needs_you[0].items[0].kind == (
            schemas.WorklistKind.approved_not_merged
        )

    def test_qa_rejection_needs_you_even_after_merge(self, db):
        """
        The review row is merged and gone from the queue, but a tester saying
        it is broken is squarely the author's problem.
        """
        comms_log.record(
            db, owner_id=OWNER, repo=REPO, pr_number=42, ticket_key="LOC-42",
            loop="qa", direction="received", channel="slack",
            participant="tester-sam", body="hammers the API on 500s",
            outcome="broken",
        )

        result = worklist.build(db, owner_id=OWNER)

        item = result.needs_you[0].items[0]
        assert item.kind == schemas.WorklistKind.qa_rejected
        assert item.quotes == ["hammers the API on 500s"]

    def test_a_failed_send_needs_you(self, db):
        comms_log.record(
            db, owner_id=OWNER, repo=REPO, pr_number=42,
            loop="qa", direction="sent", channel="email",
            body="Ready to test", succeeded=False,
        )

        result = worklist.build(db, owner_id=OWNER)

        assert result.needs_you[0].items[0].kind == (
            schemas.WorklistKind.delivery_failed
        )

    def test_a_delivered_message_is_not_an_item(self, db):
        """Precision: a list showing things that do not need you is ignored."""
        comms_log.record(
            db, owner_id=OWNER, repo=REPO, pr_number=42,
            loop="qa", direction="sent", channel="email",
            body="Ready to test", succeeded=True,
        )

        result = worklist.build(db, owner_id=OWNER)

        assert result.needs_you == []


class TestOrdering:
    def test_staleness_outranks_recency(self, db):
        """
        A task on round five for three days is a conversation that is not
        converging. That is the signal the per-PR views cannot show, so it
        must sort above something that arrived an hour ago.
        """
        _review(db, pr=1, state="changes_requested", tickets="LOC-NEW",
                asks="x", rounds=1, hours_ago=1)
        _review(db, pr=2, state="changes_requested", tickets="LOC-OLD",
                asks="y", rounds=5, hours_ago=72)

        result = worklist.build(db, owner_id=OWNER)

        assert [t.key for t in result.needs_you] == ["LOC-OLD", "LOC-NEW"]

    def test_humans_rank_above_machines_within_a_task(self, db):
        """
        "@senior-dev: add a test" and "a message failed to send" are not the
        same weight. A person asked; the other is our own plumbing.
        """
        _review(db, pr=42, state="changes_requested", tickets="LOC-42",
                asks="add a test", hours_ago=1)
        comms_log.record(
            db, owner_id=OWNER, repo=REPO, pr_number=42, ticket_key="LOC-42",
            loop="qa", direction="sent", channel="email",
            body="failed one", succeeded=False,
        )

        result = worklist.build(db, owner_id=OWNER)

        kinds = [i.kind for i in result.needs_you[0].items]
        assert kinds[0] == schemas.WorklistKind.changes_requested

    def test_needs_you_always_precedes_waiting(self, db):
        _review(db, pr=1, state="awaiting_review", tickets="LOC-WAIT",
                hours_ago=100)
        _review(db, pr=2, state="changes_requested", tickets="LOC-ACT",
                asks="x", hours_ago=1)

        result = worklist.build(db, owner_id=OWNER)

        # Even though the waiting one is far older.
        assert [t.key for t in result.needs_you] == ["LOC-ACT"]
        assert [t.key for t in result.waiting_on_others] == ["LOC-WAIT"]


class TestActionableContent:
    def test_an_item_carries_the_askers_own_words(self, db):
        """
        The checklist is for scanning; the quote is what someone acts on.
        """
        _review(db, pr=42, state="changes_requested", asks="Add a test",
                body="Needs a test for the retry path, and cap the backoff.")

        result = worklist.build(db, owner_id=OWNER)
        item = result.needs_you[0].items[0]

        assert item.detail == ["Add a test"]
        assert "cap the backoff" in item.quotes[0]


class TestIsolation:
    def test_another_users_work_is_not_listed(self, db):
        _review(db, pr=42, state="changes_requested", asks="mine")
        other = models.PRReview(
            repo=REPO, pr_number=99, state="changes_requested",
            round_number=1, pending_asks="theirs", owner_id=OWNER + 1,
        )
        db.add(other)
        db.commit()

        result = worklist.build(db, owner_id=OWNER)

        assert len(result.needs_you) == 1
        assert result.needs_you[0].items[0].pr_number == 42


def _qa_thread(db, *, pr, days_ago, resolved=0, ticket=None):
    """A QA notification posted `days_ago`, optionally already answered."""
    thread = models.QAThread(
        repo=REPO, pr_number=pr,
        pr_url=f"https://github.com/{REPO}/pull/{pr}",
        slack_channel="C1", slack_thread_ts=f"{pr}.0",
        ticket_keys_json=f'["{ticket}"]' if ticket else "[]",
        issue_numbers_json="[]",
        resolved=resolved, owner_id=OWNER,
        created_at=datetime.now(UTC) - timedelta(days=days_ago),
    )
    db.add(thread)
    db.commit()
    return thread


def _all_items(result):
    """Every item across both sections of the worklist."""
    return [
        i
        for t in result.needs_you + result.waiting_on_others
        for i in t.items
    ]


class TestUnansweredTestingThread:
    """
    The safety net for closing on sign-off rather than at merge.

    A work item now stays open until a tester replies, so a thread nobody
    answers would leave it open forever with nothing chasing it -- trading a
    ticket that closed too early for one that never closes.
    """

    def test_a_silent_thread_becomes_something_waiting_on_you(self, db):
        _qa_thread(db, pr=7, days_ago=5)

        result = worklist.build(db, owner_id=OWNER)

        items = _all_items(result)
        assert any(
            i.kind == schemas.WorklistKind.qa_unanswered for i in items
        )
        assert any(i.blocked_on_you for i in items)

    def test_a_fresh_thread_is_left_alone(self, db):
        """QA replying next morning is ordinary, not a problem to report."""
        _qa_thread(db, pr=7, days_ago=1)

        result = worklist.build(db, owner_id=OWNER)

        items = _all_items(result)
        assert not any(
            i.kind == schemas.WorklistKind.qa_unanswered for i in items
        )

    def test_an_answered_thread_is_not_reported(self, db):
        """Resolved means a tester signed off; there is nothing to chase."""
        _qa_thread(db, pr=7, days_ago=10, resolved=1)

        result = worklist.build(db, owner_id=OWNER)

        items = _all_items(result)
        assert not any(
            i.kind == schemas.WorklistKind.qa_unanswered for i in items
        )

    def test_a_rejection_is_not_also_reported_as_silence(self, db):
        """
        A thread answered "broken" is already a rejection item. Listing it
        again as unanswered would show one conversation as two problems.
        """
        _qa_thread(db, pr=7, days_ago=6)
        comms_log.record(
            db, owner_id=OWNER, repo=REPO, pr_number=7,
            loop="qa", direction="received", channel="slack",
            participant="tester", body="the heading is gone",
            outcome="broken",
        )

        result = worklist.build(db, owner_id=OWNER)

        items = _all_items(result)
        kinds = [i.kind for i in items]
        assert schemas.WorklistKind.qa_rejected in kinds
        assert schemas.WorklistKind.qa_unanswered not in kinds

    def test_it_groups_onto_the_ticket_not_a_second_card(self, db):
        """
        A thread carries no ticket key of its own. Without the lookup the
        board would show one piece of work as two separate tasks.
        """
        _review(db, pr=7, state="merged", tickets="LOC-1")
        _qa_thread(db, pr=7, days_ago=5, ticket="LOC-1")

        result = worklist.build(db, owner_id=OWNER)

        keys = [t.key for t in result.needs_you + result.waiting_on_others]
        assert keys == ["LOC-1"]
