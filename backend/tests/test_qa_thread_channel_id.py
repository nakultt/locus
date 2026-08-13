"""
Matching a Slack reply back to its QA thread.

An inbound Slack event identifies its channel by id ("C09AB..."), never by the
"#web" name a user types at registration. Storing the name meant the lookup
could never match and a tester's reply was silently dropped.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.merge_actions import post_qa_thread


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def fake_client(payload: dict):
    """Stand in for httpx.AsyncClient used as a context manager."""
    client = AsyncMock()
    client.post.return_value = FakeResponse(payload)
    ctx = AsyncMock()
    ctx.__aenter__.return_value = client
    return ctx


@pytest.fixture
def result():
    from app.schemas import PRAnalysisResult, PRContext

    return PRAnalysisResult(context=PRContext(
        repo="shadowyay/joyyy", pr_number=2, title="Revert",
        author="shadowyay", url="https://github.com/x",
        files_changed=1, additions=1, deletions=1,
    ))


class TestPostQaThread:
    @pytest.mark.asyncio
    async def test_returns_the_resolved_channel_id(self, result):
        """
        The post is addressed to "#web" but Slack answers with the id. That id
        is what later replies will carry, so it is what must be stored.
        """
        config = {"credentials": {"bot_token": "xoxb-x"}}
        payload = {"ok": True, "ts": "1786638974.393459", "channel": "C09WEB123"}

        with patch("app.services.merge_actions.httpx.AsyncClient",
                   return_value=fake_client(payload)):
            ts, channel_id = await post_qa_thread(config, "#web", result, "brief")

        assert ts == "1786638974.393459"
        assert channel_id == "C09WEB123"

    @pytest.mark.asyncio
    async def test_failure_returns_a_pair(self, result):
        """Callers unpack two values; a failure must not raise on unpack."""
        config = {"credentials": {"bot_token": "xoxb-x"}}

        with patch("app.services.merge_actions.httpx.AsyncClient",
                   return_value=fake_client({"ok": False, "error": "not_in_channel"})):
            assert await post_qa_thread(config, "#web", result, "b") == (None, None)

    @pytest.mark.asyncio
    async def test_missing_token_returns_a_pair(self, result):
        assert await post_qa_thread({}, "#web", result, "b") == (None, None)


class TestReplyMatching:
    """The lookup in the events router, including the legacy-row path."""

    def setup_db(self, tmp_path, channel: str):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from app import models
        from app.database import Base

        engine = create_engine(
            f"sqlite:///{tmp_path}/qa.db", connect_args={"check_same_thread": False}
        )
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)

        db = Session()
        db.add(models.QAThread(
            repo="shadowyay/joyyy", pr_number=2,
            pr_url="https://github.com/x",
            slack_channel=channel,
            slack_thread_ts="1786638974.393459",
            ticket_keys_json="[]", issue_numbers_json="[]",
            owner_id=1,
        ))
        db.commit()
        return db

    def lookup(self, db, thread_ts: str, channel: str):
        """Mirror of the router's matching logic."""
        from app import models

        candidates = db.query(models.QAThread).filter(
            models.QAThread.slack_thread_ts == thread_ts,
        ).all()
        thread = next(
            (t for t in candidates if t.slack_channel == channel),
            candidates[0] if candidates else None,
        )
        if thread and thread.slack_channel != channel:
            thread.slack_channel = channel
            db.commit()
        return thread

    def test_matches_when_the_id_was_stored(self, tmp_path):
        db = self.setup_db(tmp_path, "C09WEB123")

        thread = self.lookup(db, "1786638974.393459", "C09WEB123")

        assert thread is not None and thread.pr_number == 2
        db.close()

    def test_matches_a_legacy_row_holding_the_channel_name(self, tmp_path):
        """
        The reported case: the row was written with "#web" before the id was
        captured. The reply must still be attributed.
        """
        db = self.setup_db(tmp_path, "#web")

        thread = self.lookup(db, "1786638974.393459", "C09WEB123")

        assert thread is not None and thread.pr_number == 2
        # And the id is backfilled so later replies match exactly.
        assert thread.slack_channel == "C09WEB123"
        db.close()

    def test_unknown_timestamp_matches_nothing(self, tmp_path):
        db = self.setup_db(tmp_path, "C09WEB123")

        assert self.lookup(db, "9999999999.000000", "C09WEB123") is None
        db.close()
