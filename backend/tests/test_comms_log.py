"""
The communication log: what was searched, sent, and received.

The dashboard could already say Slack was searched and the test team emailed.
It could not say what was searched for, what came back, or what was actually
sent -- the first questions anyone asks about a surprising run.

Two properties matter more than the storage itself. Logging must never break
the thing it describes, and a search that found nothing must be
distinguishable from a search that never ran.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.services.pipeline import agent_settings, comms_log

REPO, PR, OWNER = "acme/widget", 42, 1


@pytest.fixture
def db(tmp_path):
    from app.core.database import Base

    engine = create_engine(
        f"sqlite:///{tmp_path}/c.db", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


class TestRecording:
    def test_a_sent_message_is_stored_verbatim(self, db):
        body = "📝 @senior-dev requested changes on acme/widget#42\n• Add a test"

        comms_log.record(
            db, owner_id=OWNER, repo=REPO, pr_number=PR,
            loop="review", direction="sent", channel="slack",
            target="#code-review", body=body,
        )

        event = db.query(models.CommunicationEvent).one()
        # Verbatim, not summarized: a truncated record answers the easy
        # questions and none of the hard ones.
        assert event.body == body
        assert event.target == "#code-review"

    def test_a_failed_send_is_recorded_as_failed(self, db):
        """A message that did not go out is the one worth surfacing."""
        comms_log.record(
            db, owner_id=OWNER, repo=REPO, pr_number=PR,
            loop="qa", direction="sent", channel="email",
            body="Ready to test", succeeded=False,
        )

        assert db.query(models.CommunicationEvent).one().succeeded == 0

    def test_an_enormous_body_is_clipped_not_rejected(self, db):
        """One pasted logfile must not be able to fill the table."""
        comms_log.record(
            db, owner_id=OWNER, repo=REPO, pr_number=PR,
            loop="qa", direction="received", channel="slack",
            body="x" * 60_000,
        )

        stored = db.query(models.CommunicationEvent).one().body
        assert len(stored) < 60_000
        assert stored.endswith("(truncated)")

    def test_logging_failure_does_not_raise(self, db, monkeypatch):
        """
        Bookkeeping must never break the thing it describes.

        A Slack message that was genuinely sent must not be reported as failed
        because the record of it could not be written.
        """
        def boom(*_a, **_kw):
            raise RuntimeError("database is gone")

        monkeypatch.setattr(db, "add", boom)

        # No exception escapes.
        comms_log.record(
            db, owner_id=OWNER, repo=REPO, pr_number=PR,
            loop="review", direction="sent", channel="slack", body="hi",
        )


class TestSearchVisibility:
    def test_queries_are_recorded_even_when_nothing_matched(self, db):
        """
        A search that found nothing looks identical to one that never ran.

        Only the query makes the difference visible, which is the whole point
        of storing it.
        """
        comms_log.record_search_matches(
            db, owner_id=OWNER, repo=REPO, pr_number=PR,
            queries=['"LOC-42"', "retry logic"],
            matches=[],
        )

        events = db.query(models.CommunicationEvent).all()
        assert len(events) == 2
        assert {e.query for e in events} == {'"LOC-42"', "retry logic"}
        assert all(e.outcome == "no matches" for e in events)

    def test_matches_store_the_full_message_and_its_query(self, db):
        comms_log.record_search_matches(
            db, owner_id=OWNER, repo=REPO, pr_number=PR,
            queries=['"LOC-42"'],
            matches=[{
                "channel": "eng", "participant": "jane",
                "text": "we agreed retries cap at 3",
                "permalink": "https://slack.com/archives/x",
                "query": '"LOC-42"',
            }],
        )

        received = db.query(models.CommunicationEvent).filter(
            models.CommunicationEvent.direction == "received"
        ).one()

        assert received.body == "we agreed retries cap at 3"
        assert received.participant == "jane"
        # Which query surfaced it, so a noisy match can be traced to the term
        # that found it.
        assert received.query == '"LOC-42"'


class TestOwnNotificationsAreNotDiscussion:
    """
    Locus must not read its own Slack posts back as team discussion.

    `search.messages` runs on the *user's* token and returns the whole
    channel, so every review ping, QA brief and merge announcement Locus wrote
    came back matching the ticket key better than the human conversation the
    search exists to find. Cached as "prior discussion" they reached the
    authoring model as background, and it answered them: a rework asked only
    to create a folder produced compatibility aliases instead, which is what
    the QA brief for an unrelated pull request had asked a *tester* to verify.
    """

    def _cache(self, db, text):
        comms_log.record_search_matches(
            db, owner_id=OWNER, repo=REPO, pr_number=PR,
            queries=['"LOC-42"'],
            matches=[{
                "channel": "web", "participant": "Locus",
                "text": text, "permalink": f"https://slack.com/archives/{hash(text)}",
                "query": '"LOC-42"',
            }],
        )

    def test_the_notifications_locus_actually_sends_are_recognised(self):
        """
        Built by the real formatters rather than typed out here, so a reworded
        notification fails this test instead of silently becoming context.
        """
        from app.services.pipeline.review_flow import is_own_slack_notification

        sent = [
            ":white_check_mark: @jo approved <https://gh/pr/8|acme/api#8> — "
            "ready to merge.",
            ":pencil: @jo requested changes on <https://gh/pr/8|acme/api#8> "
            "(round 1) — over to @sam.",
            ":eyes: Review requested on <https://gh/pr/8|acme/api#8> — @jo",
            ":arrows_counterclockwise: <https://gh/pr/8|acme/api#8> ready for "
            "round 2 — @jo",
            ":rocket: Auto-merged. Post-merge actions are running.",
            ":test_tube: *Ready to test* - <https://gh/pr/8|acme/api#8>",
            "*<https://gh/pr/8|acme/api#8>* — a title\n"
            "by sam · +39/-2 across 4 files\n"
            ":mag: 1 unverified issue(s) flagged for review",
        ]
        for text in sent:
            assert is_own_slack_notification(text), text

    def test_a_human_message_is_not_mistaken_for_one(self):
        from app.services.pipeline.review_flow import is_own_slack_notification

        assert not is_own_slack_notification(
            "we agreed retries cap at 3 — see the thread from Tuesday"
        )
        assert not is_own_slack_notification(None)

    def test_a_cached_notification_is_not_returned_as_context(self, db):
        """
        Filtered on the way out rather than deleted. The row is a true record
        of what the search returned, and the log is the whole record; it is
        only wrong as *context*. The Slack cache is deliberately permanent, so
        there is no expiry to wait out -- without this the rows already stored
        reach every future run on the work item forever.
        """
        self._cache(db, "we agreed retries cap at 3")
        self._cache(db, ":eyes: Review requested on <https://gh/pr/8|acme/api#8> — @jo")

        _, matches = comms_log.cached_search(
            db, owner_id=OWNER, repo=REPO, pr_number=PR, ticket_key=None
        )

        assert [m["text"] for m in matches] == ["we agreed retries cap at 3"]
        # Still recorded: the filter is on the read, not the write.
        assert db.query(models.CommunicationEvent).filter(
            models.CommunicationEvent.direction == "received"
        ).count() == 2


class TestLinkedIssues:
    ISSUES = [
        {
            "number": 7, "title": "Retries hammer the API on 500s",
            "state": "open", "url": "https://github.com/acme/widget/issues/7",
            "author": "priya", "body": "We should cap retries at 3.",
            "relation": "closes",
        },
        {
            "number": 9, "title": "Unrelated flake",
            "state": "open", "url": "https://github.com/acme/widget/issues/9",
            "author": "sam", "body": "", "relation": "mentions",
        },
    ]

    def test_issue_text_and_author_are_recorded(self, db):
        """
        An issue body is context a human wrote about this work.

        It was already fetched and fed to the reviewer; not storing it meant
        the dashboard showed less than the model was given.
        """
        comms_log.record_issues(
            db, owner_id=OWNER, repo=REPO, pr_number=PR, issues=self.ISSUES
        )

        closes = db.query(models.CommunicationEvent).filter(
            models.CommunicationEvent.outcome == "closes"
        ).one()

        assert closes.body == "We should cap retries at 3."
        assert closes.participant == "priya"
        assert closes.subject == "Retries hammer the API on 500s"
        assert closes.permalink.endswith("/issues/7")

    def test_closes_and_mentions_stay_distinguishable(self, db):
        """
        Only a formally closing issue is closed on merge.

        Recording both identically would let the UI overstate what the PR
        claims about a bare #N reference.
        """
        comms_log.record_issues(
            db, owner_id=OWNER, repo=REPO, pr_number=PR, issues=self.ISSUES
        )

        outcomes = {
            e.target: e.outcome
            for e in db.query(models.CommunicationEvent).all()
        }

        assert outcomes == {"issue #7": "closes", "issue #9": "mentions"}

    def test_an_issue_with_no_body_is_still_recorded(self, db):
        """A title-only issue is still context; it just has nothing to expand."""
        comms_log.record_issues(
            db, owner_id=OWNER, repo=REPO, pr_number=PR, issues=self.ISSUES
        )

        mention = db.query(models.CommunicationEvent).filter(
            models.CommunicationEvent.outcome == "mentions"
        ).one()

        assert mention.body is None
        assert mention.subject == "Unrelated flake"


class TestTimeline:
    def test_both_loops_come_back_in_one_ordered_story(self, db):
        for loop, direction, body in [
            ("context", "searched", None),
            ("review", "sent", "review requested"),
            ("review", "received", "please add a test"),
            ("qa", "sent", "ready to test"),
            ("qa", "received", "works fine"),
        ]:
            comms_log.record(
                db, owner_id=OWNER, repo=REPO, pr_number=PR,
                loop=loop, direction=direction, channel="slack", body=body,
            )

        events = comms_log.timeline(db, owner_id=OWNER, repo=REPO, pr_number=PR)

        assert [e.loop for e in events] == [
            "context", "review", "review", "qa", "qa"
        ]

    def test_another_users_messages_are_not_returned(self, db):
        comms_log.record(
            db, owner_id=OWNER, repo=REPO, pr_number=PR,
            loop="review", direction="sent", channel="slack", body="mine",
        )
        comms_log.record(
            db, owner_id=OWNER + 1, repo=REPO, pr_number=PR,
            loop="review", direction="sent", channel="slack", body="theirs",
        )

        events = comms_log.timeline(db, owner_id=OWNER, repo=REPO, pr_number=PR)

        assert [e.body for e in events] == ["mine"]


class TestReviewerContacts:
    def test_slack_and_email_are_recognised_in_any_order(self):
        """
        This is typed by hand, so demanding a strict field order is a cost
        with no benefit. An address is recognised by its shape.
        """
        parsed = agent_settings.parse_contacts(
            "jane, @jane-slack, jane@acme.com\n"
            "bob, bob@acme.com, @bobby"
        )

        assert parsed["jane"] == {"slack": "@jane-slack", "email": "jane@acme.com"}
        assert parsed["bob"] == {"slack": "@bobby", "email": "bob@acme.com"}

    def test_a_bare_handle_gets_its_sigil(self):
        assert agent_settings.parse_contacts("jane, jane-slack") == {
            "jane": {"slack": "@jane-slack"}
        }

    def test_a_login_alone_is_valid(self):
        """Contacts are optional; the loop works without them."""
        assert agent_settings.parse_contacts("jane") == {"jane": {}}

    def test_blank_input_is_empty_not_an_error(self):
        assert agent_settings.parse_contacts(None) == {}
        assert agent_settings.parse_contacts("  \n \n") == {}
