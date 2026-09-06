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
from app.services.pipeline import comms_log, context_brief

REPO, OWNER = "acme/widget", 1
TICKET = "LOC-42"


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


class TestCachedSearch:
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

    def test_a_cached_search_returns_its_matches_and_a_watermark(self, db):
        """
        Reusing the matches matters, not merely skipping the call. Skipping
        alone would hand the reviewer empty context, which is worse than the
        redundant search. The watermark is what makes the next search
        incremental instead of a full re-fetch.
        """
        self._searched(db, hours_ago=1)

        searched_at, matches = comms_log.cached_search(
            db, owner_id=OWNER, repo=REPO, pr_number=42, ticket_key=TICKET,
        )

        assert searched_at is not None
        assert [m["text"] for m in matches] == ["cap retries at 3"]
        assert matches[0]["participant"] == "priya"

    def test_an_old_search_is_still_reused(self, db):
        """
        There is no freshness window. A requirement debated two days ago is
        still the requirement, and the incremental search from the watermark
        is what picks up anything said since -- a window would instead hide
        new discussion until it expired.
        """
        self._searched(db, hours_ago=48)

        searched_at, matches = comms_log.cached_search(
            db, owner_id=OWNER, repo=REPO, pr_number=42, ticket_key=TICKET,
        )

        assert searched_at is not None
        assert [m["text"] for m in matches] == ["cap retries at 3"]

    def test_never_searched_has_no_watermark(self, db):
        """No watermark means a full search: an incremental one from an
        unknown point would silently skip whatever fell before it."""
        searched_at, matches = comms_log.cached_search(
            db, owner_id=OWNER, repo=REPO, pr_number=42, ticket_key=TICKET,
        )

        assert searched_at is None
        assert matches == []

    def test_a_second_pr_on_the_ticket_reuses_the_first_search(self, db):
        """This is what the ticket key buys: PR #57 inherits the discussion."""
        self._searched(db, hours_ago=1)

        searched_at, matches = comms_log.cached_search(
            db, owner_id=OWNER, repo=REPO, pr_number=57,  # different PR
            ticket_key=TICKET,
        )

        assert searched_at is not None
        assert len(matches) == 1

    def test_a_message_recorded_twice_is_returned_once(self, db):
        """The cache accumulates over rounds; the same message recorded by two
        rounds' searches would otherwise read as two people saying it."""
        self._searched(db, hours_ago=2)
        for _ in range(2):
            comms_log.record(
                db, owner_id=OWNER, repo=REPO, pr_number=42, ticket_key=TICKET,
                loop="context", direction="received", channel="slack",
                participant="priya", target="eng", body="cap retries at 3",
                permalink="https://slack.example/p1",
            )

        _, matches = comms_log.cached_search(
            db, owner_id=OWNER, repo=REPO, pr_number=42, ticket_key=TICKET,
        )

        links = [m["permalink"] for m in matches if m["permalink"]]
        assert links == ["https://slack.example/p1"]


class TestIncrementalSlackSearch:
    """
    The watermark is what replaces the freshness window. A run reuses the
    cache and asks Slack only for what was said since -- so new discussion is
    picked up on the next run rather than waiting for a window to expire.
    """

    @staticmethod
    def _payload(*messages: dict) -> dict:
        return {"ok": True, "messages": {"matches": list(messages)}}

    @staticmethod
    def _message(ts: float, text: str) -> dict:
        return {
            "ts": str(ts),
            "text": text,
            "permalink": f"https://slack.example/{ts}",
            "channel": {"name": "eng"},
            "username": "priya",
        }

    @pytest.mark.asyncio
    async def test_messages_at_or_before_the_watermark_are_dropped(self, monkeypatch):
        """
        `after:` narrows only to the day, so the day's earlier messages come
        back too. They are already cached; recording them again would
        duplicate the timeline.
        """
        from app.services.pipeline import pr_agent

        since = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)
        captured: list[str] = []

        class _Response:
            @staticmethod
            def json() -> dict:
                return TestIncrementalSlackSearch._payload(
                    TestIncrementalSlackSearch._message(
                        since.timestamp() - 60, "older, already cached"
                    ),
                    TestIncrementalSlackSearch._message(
                        since.timestamp() + 60, "newer, not yet seen"
                    ),
                )

        class _Client:
            async def __aenter__(self): return self
            async def __aexit__(self, *_): return False
            async def get(self, _url, **kwargs):
                captured.append(kwargs["params"]["query"])
                return _Response()

        monkeypatch.setattr(pr_agent.httpx, "AsyncClient", lambda **_: _Client())

        matches: list[dict] = []
        threads = await pr_agent.search_slack_threads(
            [TICKET], REPO, 42,
            {"credentials": {"user_token": "xoxp-test"}},
            title="Add retry logic", matches=matches, since=since,
        )

        assert [t.summary for t in threads] == ["newer, not yet seen"]
        assert [m["text"] for m in matches] == ["newer, not yet seen"]
        # Narrowed server-side, a day early because `after:` excludes its day.
        assert all("after:2026-08-13" in q for q in captured)

    @pytest.mark.asyncio
    async def test_without_a_watermark_nothing_is_filtered(self, monkeypatch):
        """A work item never searched gets a full search, not an incremental
        one from an unknown point."""
        from app.services.pipeline import pr_agent

        captured: list[str] = []

        class _Response:
            @staticmethod
            def json() -> dict:
                return TestIncrementalSlackSearch._payload(
                    TestIncrementalSlackSearch._message(1_700_000_000, "old"),
                    TestIncrementalSlackSearch._message(1_800_000_000, "new"),
                )

        class _Client:
            async def __aenter__(self): return self
            async def __aexit__(self, *_): return False
            async def get(self, _url, **kwargs):
                captured.append(kwargs["params"]["query"])
                return _Response()

        monkeypatch.setattr(pr_agent.httpx, "AsyncClient", lambda **_: _Client())

        threads = await pr_agent.search_slack_threads(
            [TICKET], REPO, 42,
            {"credentials": {"user_token": "xoxp-test"}}, title="Add retry logic",
        )

        assert {t.summary for t in threads} == {"old", "new"}
        assert all("after:" not in q for q in captured)


class TestOwnPostsAreNotSearchResults:
    """
    The search runs on the *user's* token and sees the whole channel,
    including everything Locus posted into it -- and those posts name the repo
    and the ticket, so they match better than the human discussion the search
    exists to find.
    """

    @pytest.mark.asyncio
    async def test_a_bot_post_is_not_cached_as_discussion(self, monkeypatch):
        """
        `bot_id` is the discriminator, the same one the QA loop already uses
        to tell a tester's reply from its own post. Filtering at the source
        stops new ones; `comms_log.cached_search` covers what is already
        stored, because the Slack cache is deliberately permanent.
        """
        from app.services.pipeline import pr_agent

        human = TestIncrementalSlackSearch._message(1_800_000_000, "cap retries at 3")
        own = TestIncrementalSlackSearch._message(
            1_800_000_001,
            ":eyes: Review requested on <https://gh/pr/8|acme/api#8> — @jo",
        )
        own["bot_id"] = "B12345"
        own["username"] = "Locus"

        class _Response:
            @staticmethod
            def json() -> dict:
                return TestIncrementalSlackSearch._payload(human, own)

        class _Client:
            async def __aenter__(self): return self
            async def __aexit__(self, *_): return False
            async def get(self, _url, **kwargs): return _Response()

        monkeypatch.setattr(pr_agent.httpx, "AsyncClient", lambda **_: _Client())

        matches: list[dict] = []
        threads = await pr_agent.search_slack_threads(
            [TICKET], REPO, 42,
            {"credentials": {"user_token": "xoxp-test"}},
            title="Add retry logic", matches=matches,
        )

        assert [t.summary for t in threads] == ["cap retries at 3"]
        assert [m["text"] for m in matches] == ["cap retries at 3"]


class TestTimelineInheritance:
    """
    The reviewer is given the ticket's cached Slack discussion every round.
    A timeline showing only rows stamped with this PR's number would omit
    context the run demonstrably used.
    """

    def test_sibling_pr_discussion_appears_marked(self, db):
        comms_log.record(
            db, owner_id=OWNER, repo=REPO, pr_number=42, ticket_key=TICKET,
            loop="context", direction="received", channel="slack",
            participant="priya", body="cap retries at 3",
            permalink="https://slack.example/p1",
        )
        comms_log.record(
            db, owner_id=OWNER, repo=REPO, pr_number=57, ticket_key=TICKET,
            loop="review", direction="sent", channel="slack",
            body="round 2 submitted",
        )

        events = comms_log.timeline(
            db, owner_id=OWNER, repo=REPO, pr_number=57, ticket_key=TICKET,
        )

        by_body = {e.body: e for e in events}
        assert by_body["cap retries at 3"].inherited is True
        assert by_body["round 2 submitted"].inherited is False

    def test_without_a_ticket_only_this_prs_own_rows_show(self, db):
        comms_log.record(
            db, owner_id=OWNER, repo=REPO, pr_number=42, ticket_key=TICKET,
            loop="context", direction="received", channel="slack",
            body="cap retries at 3", permalink="https://slack.example/p1",
        )
        comms_log.record(
            db, owner_id=OWNER, repo=REPO, pr_number=57, ticket_key=TICKET,
            loop="review", direction="sent", channel="slack", body="mine",
        )

        events = comms_log.timeline(db, owner_id=OWNER, repo=REPO, pr_number=57)
        assert [e.body for e in events] == ["mine"]

    def test_a_message_on_both_prs_is_not_shown_twice(self, db):
        for pr in (42, 57):
            comms_log.record(
                db, owner_id=OWNER, repo=REPO, pr_number=pr, ticket_key=TICKET,
                loop="context", direction="received", channel="slack",
                body="cap retries at 3", permalink="https://slack.example/p1",
            )

        events = comms_log.timeline(
            db, owner_id=OWNER, repo=REPO, pr_number=57, ticket_key=TICKET,
        )
        assert [e.body for e in events] == ["cap retries at 3"]


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

    def test_locus_own_slack_posts_are_not_prior_discussion(self, db):
        """
        Every consumer of this brief is a model -- the authoring driver and
        the code reviewer -- so a cached notification here is not noise, it is
        an instruction. A rework asked only to create a folder produced
        compatibility aliases instead, which is what the QA brief Locus had
        written for an unrelated pull request asked a *tester* to verify.
        """
        self._review(db)
        for body in (
            "cap retries at 3",
            ":test_tube: *Ready to test* - <https://gh/pr/9|acme/api#9>\n"
            "*What to test*\nVerify that reserve takes stock first.",
        ):
            comms_log.record(
                db, owner_id=OWNER, repo=REPO, pr_number=42, ticket_key=TICKET,
                loop="context", direction="received", channel="slack",
                participant="Locus", target="web", body=body,
            )

        brief = context_brief.build(
            db, owner_id=OWNER, repo=REPO, pr_number=42, ticket_key=TICKET
        )

        assert "cap retries at 3" in brief
        assert "Ready to test" not in brief
        assert "Verify that reserve takes stock first" not in brief

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
