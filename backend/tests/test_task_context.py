"""
Phase 5: context that accumulates instead of being re-gathered.

Two properties carry the phase. Context must follow the *work item* rather
than the pull request, because a ticket spans several PRs and the second one
should not start from nothing. And the reuse must never extend to anything
derived from the diff -- reusing a brief across a review round would resubmit
round two carrying round one's findings against round two's code.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models, schemas
from app.services import comms_log, context_brief

REPO, OWNER = "acme/widget", 1
TICKET = "LOC-42"


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


class TestTicketScoping:
    def test_context_follows_the_ticket_across_pull_requests(self, db):
        """
        The second PR on a ticket should open with the first one's history --
        including the QA rejection that caused it to exist.
        """
        comms_log.record(
            db, owner_id=OWNER, repo=REPO, pr_number=42, ticket_key=TICKET,
            loop="context", direction="received", channel="slack",
            participant="priya", target="eng",
            body="we agreed retries cap at 3",
        )
        comms_log.record(
            db, owner_id=OWNER, repo=REPO, pr_number=42, ticket_key=TICKET,
            loop="qa", direction="received", channel="slack",
            participant="sam", body="it hammers the API on 500s",
            outcome="broken",
        )

        # PR #57 is the fix. Nothing was ever recorded against it directly.
        events = comms_log.ticket_timeline(db, owner_id=OWNER, ticket_key=TICKET)

        assert [e.body for e in events] == [
            "we agreed retries cap at 3",
            "it hammers the API on 500s",
        ]

    def test_a_different_ticket_is_not_returned(self, db):
        comms_log.record(
            db, owner_id=OWNER, repo=REPO, pr_number=1, ticket_key="LOC-1",
            loop="context", direction="received", channel="slack", body="mine",
        )
        comms_log.record(
            db, owner_id=OWNER, repo=REPO, pr_number=2, ticket_key="LOC-2",
            loop="context", direction="received", channel="slack", body="other",
        )

        events = comms_log.ticket_timeline(db, owner_id=OWNER, ticket_key="LOC-1")
        assert [e.body for e in events] == ["mine"]


class TestFreshnessWindow:
    def _searched(self, db, *, hours_ago: float, ticket=TICKET):
        comms_log.record(
            db, owner_id=OWNER, repo=REPO, pr_number=42, ticket_key=ticket,
            loop="context", direction="searched", channel="slack",
            query='"LOC-42"',
        )
        comms_log.record(
            db, owner_id=OWNER, repo=REPO, pr_number=42, ticket_key=ticket,
            loop="context", direction="received", channel="slack",
            participant="priya", target="eng", body="cap retries at 3",
        )
        stamp = datetime.now(UTC) - timedelta(hours=hours_ago)
        for event in db.query(models.CommunicationEvent).all():
            event.created_at = stamp
        db.commit()

    def test_a_recent_search_is_reused_with_its_matches(self, db):
        """
        Reusing the matches matters, not merely skipping the call. Skipping
        alone would hand the reviewer empty context, which is worse than the
        redundant search.
        """
        self._searched(db, hours_ago=1)

        fresh, matches = comms_log.recent_search(
            db, owner_id=OWNER, repo=REPO, pr_number=42,
            ticket_key=TICKET, within_hours=12,
        )

        assert fresh
        assert [m["text"] for m in matches] == ["cap retries at 3"]
        assert matches[0]["participant"] == "priya"

    def test_a_stale_search_is_not_reused(self, db):
        self._searched(db, hours_ago=48)

        fresh, _ = comms_log.recent_search(
            db, owner_id=OWNER, repo=REPO, pr_number=42,
            ticket_key=TICKET, within_hours=12,
        )

        assert not fresh

    def test_never_searched_is_not_fresh(self, db):
        fresh, matches = comms_log.recent_search(
            db, owner_id=OWNER, repo=REPO, pr_number=42,
            ticket_key=TICKET, within_hours=12,
        )

        assert not fresh
        assert matches == []

    def test_a_second_pr_on_the_ticket_reuses_the_first_search(self, db):
        """This is what the ticket key buys: PR #57 does not search again."""
        self._searched(db, hours_ago=1)

        fresh, matches = comms_log.recent_search(
            db, owner_id=OWNER, repo=REPO, pr_number=57,  # different PR
            ticket_key=TICKET, within_hours=12,
        )

        assert fresh
        assert len(matches) == 1


class TestContextBrief:
    def _review(self, db, *, state="changes_requested", asks="Add a test"):
        review = models.PRReview(
            repo=REPO, pr_number=42, pr_title="Add retry logic",
            author="junior-dev", state=state, round_number=2,
            pending_asks=asks, ticket_keys=TICKET, owner_id=OWNER,
        )
        db.add(review)
        db.flush()
        db.add(models.PRReviewRound(
            review_id=review.id, round_number=1,
            outcome="changes_requested", reviewer="senior-dev",
            body="Needs a test for the retry path.",
        ))
        db.commit()
        return review

    def test_the_brief_carries_what_humans_said(self, db):
        self._review(db)
        comms_log.record(
            db, owner_id=OWNER, repo=REPO, pr_number=42, ticket_key=TICKET,
            loop="context", direction="received", channel="slack",
            participant="priya", target="eng", body="cap retries at 3",
        )

        brief = context_brief.build(
            db, owner_id=OWNER, repo=REPO, pr_number=42, ticket_key=TICKET
        )

        assert "Add retry logic" in brief
        assert "cap retries at 3" in brief
        assert "Needs a test for the retry path." in brief
        assert "Add a test" in brief  # outstanding asks

    def test_findings_come_from_this_run_not_from_storage(self, db):
        """
        The whole point of 5.0. Findings are derived from the diff, and the
        diff is what changed; a brief that carried stored findings would
        report round one's scan against round two's code.
        """
        self._review(db)

        analysis = schemas.PRAnalysisResult(
            context=schemas.PRContext(
                repo=REPO, pr_number=42, title="t",
                url="https://example.invalid", author="junior-dev", branch="b",
            ),
            confirmed_findings=[schemas.SecurityFinding(
                source=schemas.FindingSource.semgrep,
                severity=schemas.SecuritySeverity.high,
                title="SQL injection", file_path="db.py", description="d",
            )],
        )

        with_findings = context_brief.build(
            db, owner_id=OWNER, repo=REPO, pr_number=42,
            ticket_key=TICKET, analysis=analysis,
        )
        without = context_brief.build(
            db, owner_id=OWNER, repo=REPO, pr_number=42, ticket_key=TICKET
        )

        assert "SQL injection" in with_findings
        # No analysis passed means no findings section at all -- not a stale one.
        assert "SQL injection" not in without
        assert "Current findings" not in without

    def test_requirement_context_excludes_findings(self, db):
        """
        The code reviewer must not be shown its own previous output; it would
        invite agreeing with itself.
        """
        self._review(db)

        text = context_brief.requirement_context(
            db, owner_id=OWNER, repo=REPO, pr_number=42, ticket_key=TICKET
        )

        assert "Current findings" not in text

    def test_empty_sections_are_omitted_not_rendered_as_none(self, db):
        """Absence should read as absence, not as a heading with nothing under it."""
        brief = context_brief.build(db, owner_id=OWNER, repo=REPO, pr_number=99)

        assert "Prior discussion" not in brief
        assert "Testing feedback" not in brief
