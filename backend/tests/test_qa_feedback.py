"""
QA feedback handling.

Two things matter here: the Slack signature is the only authentication on the
events endpoint, and an ambiguous reply must never silently change state.
"""

import hashlib
import hmac
import time

import pytest

from app.routers.slack_events import verify_slack_signature
from app.services.pipeline.qa_feedback import Verdict, handle_qa_reply

SECRET = "s3cret"
BODY = b'{"type":"event_callback"}'


def sign(body: bytes, timestamp: str, secret: str = SECRET) -> str:
    base = b"v0:" + timestamp.encode() + b":" + body
    return "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()


class TestSlackSignature:
    def test_accepts_valid_recent_signature(self):
        ts = str(int(time.time()))
        assert verify_slack_signature(BODY, ts, sign(BODY, ts), SECRET) is True

    def test_rejects_tampered_body(self):
        ts = str(int(time.time()))
        signature = sign(BODY, ts)
        assert verify_slack_signature(b'{"type":"evil"}', ts, signature, SECRET) is False

    def test_rejects_wrong_secret(self):
        ts = str(int(time.time()))
        assert verify_slack_signature(BODY, ts, sign(BODY, ts, "other"), SECRET) is False

    def test_rejects_stale_timestamp(self):
        """A captured request must not be replayable later."""
        old = str(int(time.time()) - 600)
        assert verify_slack_signature(BODY, old, sign(BODY, old), SECRET) is False

    def test_rejects_missing_parts(self):
        ts = str(int(time.time()))
        assert verify_slack_signature(BODY, ts, "", SECRET) is False
        assert verify_slack_signature(BODY, "", sign(BODY, ts), SECRET) is False
        assert verify_slack_signature(BODY, ts, sign(BODY, ts), "") is False

    def test_rejects_non_numeric_timestamp(self):
        assert verify_slack_signature(BODY, "not-a-number", "v0=abc", SECRET) is False


class TestReplyRouting:
    """
    Verdict -> action. The classifier itself needs a model, so these stub it
    and check that each verdict causes the right state change.
    """

    @pytest.fixture
    def stub_classifier(self, monkeypatch):
        def _stub(verdict: Verdict, reason: str = "test"):
            async def fake(_text):
                return verdict, reason
            monkeypatch.setattr(
                "app.services.pipeline.qa_feedback.classify_reply", fake
            )
        return _stub

    @pytest.mark.asyncio
    async def test_works_verdict_changes_nothing(self, stub_classifier):
        stub_classifier(Verdict.WORKS)
        outcome = await handle_qa_reply(
            "looks good", {}, "acme/api", "url", ["LOC-1"], [5],
        )
        assert outcome["verdict"] == "works"
        assert outcome["reopened_tickets"] == []
        assert outcome["reopened_issues"] == []

    @pytest.mark.asyncio
    async def test_chatter_changes_nothing(self, stub_classifier):
        stub_classifier(Verdict.NOT_FEEDBACK)
        outcome = await handle_qa_reply(
            "thanks!", {}, "acme/api", "url", ["LOC-1"], [5],
        )
        assert outcome["reopened_tickets"] == []
        assert outcome["author_notified"] is False

    @pytest.mark.asyncio
    async def test_unclear_notifies_and_changes_nothing(self, stub_classifier, monkeypatch):
        """
        The decision that matters: a wrong reopen reverses a merge, so an
        ambiguous reply escalates to a human instead of guessing.
        """
        notified = {}

        async def fake_notify(_cfg, channel, _ts, _url, _text, _reason):
            notified["channel"] = channel
            return True

        monkeypatch.setattr("app.services.pipeline.qa_feedback.notify_pr_author", fake_notify)
        stub_classifier(Verdict.UNCLEAR, "mixed signals")

        outcome = await handle_qa_reply(
            "retry works but timeout is 30s now?",
            {"slack": {"api_key": "xoxb-x"}},
            "acme/api", "url", ["LOC-1"], [5],
            slack_channel="C123",
        )

        assert outcome["verdict"] == "unclear"
        assert outcome["author_notified"] is True
        assert notified["channel"] == "C123"
        # Nothing was reopened.
        assert outcome["reopened_tickets"] == []
        assert outcome["reopened_issues"] == []

    @pytest.mark.asyncio
    async def test_broken_reopens_ticket_and_issue(self, stub_classifier, monkeypatch):
        async def fake_jira(_cfg, key, _reason, _status):
            return True, f"{key} reopened"

        async def fake_gh(_token, _repo, number, _reason):
            return True, f"Reopened #{number}"

        monkeypatch.setattr("app.services.pipeline.qa_feedback.reopen_jira_ticket", fake_jira)
        monkeypatch.setattr("app.services.pipeline.qa_feedback.reopen_github_issue", fake_gh)
        stub_classifier(Verdict.BROKEN, "timeout still occurs")

        outcome = await handle_qa_reply(
            "still broken on staging",
            {
                "jira": {"api_key": "t", "credentials": {"url": "u", "email": "e"}},
                "github": {"api_key": "ghp_x"},
            },
            "acme/api", "url", ["LOC-1"], [5],
        )

        assert outcome["verdict"] == "broken"
        assert outcome["reopened_tickets"] == ["LOC-1 reopened"]
        assert outcome["reopened_issues"] == ["Reopened #5"]


class TestCloseOnSignoff:
    """
    A pass closes the work item, when the merge deferred closing to here.

    Closing at merge asserts the change is done before anyone has checked. It
    is right whenever QA passes and wrong in both cases that need attention --
    a rejection, and a thread nobody answers -- and a ticket closed while a bug
    is live drops off the board, which is where someone would look for it.
    """

    @pytest.fixture
    def stub_classifier(self, monkeypatch):
        def _stub(verdict: Verdict, reason: str = "test"):
            async def fake(_text):
                return verdict, reason
            monkeypatch.setattr(
                "app.services.pipeline.qa_feedback.classify_reply", fake
            )
        return _stub

    @pytest.fixture
    def spy_closers(self, monkeypatch):
        calls = {"jira": [], "github": []}

        async def fake_jira(config, key, status):
            calls["jira"].append((key, status))
            return True, f"{key} -> {status}"

        async def fake_gh(token, repo, number, pr_number):
            calls["github"].append((repo, number, pr_number))
            return True, f"Closed #{number}"

        monkeypatch.setattr(
            "app.services.pipeline.qa_feedback.transition_jira_ticket", fake_jira
        )
        monkeypatch.setattr(
            "app.services.pipeline.qa_feedback.close_github_issue", fake_gh
        )
        return calls

    @pytest.mark.asyncio
    async def test_signoff_closes_ticket_and_issue(
        self, stub_classifier, spy_closers
    ):
        stub_classifier(Verdict.WORKS)

        outcome = await handle_qa_reply(
            "everything worked, testing success",
            {"jira": {"api_key": "k"}, "github": {"api_key": "t"}},
            "acme/api", "url", ["LOC-1"], [5],
            done_status="Done", pr_number=7, close_on_signoff=True,
        )

        assert spy_closers["jira"] == [("LOC-1", "Done")]
        assert spy_closers["github"] == [("acme/api", 5, 7)]
        assert outcome["closed_tickets"] == ["LOC-1 -> Done"]
        assert outcome["closed_issues"] == ["Closed #5"]

    @pytest.mark.asyncio
    async def test_nothing_closes_when_the_merge_already_did(
        self, stub_classifier, spy_closers
    ):
        """
        The work item was closed at merge. Re-closing it would at best no-op
        and at worst undo a reopen someone did deliberately.
        """
        stub_classifier(Verdict.WORKS)

        outcome = await handle_qa_reply(
            "works fine",
            {"jira": {"api_key": "k"}, "github": {"api_key": "t"}},
            "acme/api", "url", ["LOC-1"], [5],
            close_on_signoff=False,
        )

        assert spy_closers["jira"] == []
        assert spy_closers["github"] == []
        assert outcome["closed_tickets"] == []

    @pytest.mark.asyncio
    async def test_a_failure_still_reopens_and_closes_nothing(
        self, stub_classifier, spy_closers, monkeypatch
    ):
        reopened = []

        async def fake_reopen_jira(config, key, reason, status):
            reopened.append(key)
            return True, f"{key} reopened"

        monkeypatch.setattr(
            "app.services.pipeline.qa_feedback.reopen_jira_ticket", fake_reopen_jira
        )
        stub_classifier(Verdict.BROKEN)

        outcome = await handle_qa_reply(
            "the heading is gone",
            {"jira": {"api_key": "k"}},
            "acme/api", "url", ["LOC-1"], [],
            close_on_signoff=True,
        )

        assert reopened == ["LOC-1"]
        assert spy_closers["jira"] == []
        assert outcome["closed_tickets"] == []

    @pytest.mark.asyncio
    async def test_chatter_closes_nothing(self, stub_classifier, spy_closers):
        """"thanks!" is not a sign-off."""
        stub_classifier(Verdict.NOT_FEEDBACK)

        await handle_qa_reply(
            "thanks!", {"jira": {"api_key": "k"}}, "acme/api", "url",
            ["LOC-1"], [5], close_on_signoff=True,
        )

        assert spy_closers["jira"] == []
        assert spy_closers["github"] == []

    @pytest.mark.asyncio
    async def test_a_failing_close_is_reported_not_raised(
        self, stub_classifier, monkeypatch
    ):
        async def boom(config, key, status):
            raise RuntimeError("Jira is down")

        monkeypatch.setattr(
            "app.services.pipeline.qa_feedback.transition_jira_ticket", boom
        )
        stub_classifier(Verdict.WORKS)

        outcome = await handle_qa_reply(
            "works", {"jira": {"api_key": "k"}}, "acme/api", "url",
            ["LOC-1"], [], close_on_signoff=True,
        )

        assert outcome["closed_tickets"] == []
        assert any("Jira is down" in e for e in outcome["errors"])
