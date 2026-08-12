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
from app.services.qa_feedback import Verdict, handle_qa_reply

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
                "app.services.qa_feedback.classify_reply", fake
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

        monkeypatch.setattr("app.services.qa_feedback.notify_pr_author", fake_notify)
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

        monkeypatch.setattr("app.services.qa_feedback.reopen_jira_ticket", fake_jira)
        monkeypatch.setattr("app.services.qa_feedback.reopen_github_issue", fake_gh)
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
