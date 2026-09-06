"""
Slack endpoint setup: the url_verification challenge.

Slack will not save an Event Subscription until the endpoint echoes a
challenge, and it sends that challenge before the app is necessarily
configured. Gating the challenge behind the signing secret made the
subscription unsavable -- which blocked every signed event that would have
followed.
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app import main
    from app.core.database import Base, get_db

    engine = create_engine(
        f"sqlite:///{tmp_path}/sl.db", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    main.app.dependency_overrides[get_db] = override
    with TestClient(main.app) as c:
        yield c
    main.app.dependency_overrides.clear()


CHALLENGE = {"type": "url_verification", "challenge": "3eZbrw1aB"}


class TestChallenge:
    def test_echoed_before_the_secret_is_configured(self, client, monkeypatch):
        """
        The reported 503. The challenge carries no data and grants no access,
        so answering it is safe and is the only way to finish setup.
        """
        monkeypatch.delenv("SLACK_SIGNING_SECRET", raising=False)

        response = client.post("/webhooks/slack", json=CHALLENGE)

        assert response.status_code == 200
        assert response.json() == {"challenge": "3eZbrw1aB"}

    def test_echoed_once_the_secret_exists(self, client, monkeypatch):
        monkeypatch.setenv("SLACK_SIGNING_SECRET", "s3cret")

        response = client.post("/webhooks/slack", json=CHALLENGE)

        assert response.status_code == 200
        assert response.json() == {"challenge": "3eZbrw1aB"}

    def test_missing_challenge_field_yields_an_empty_string(self, client, monkeypatch):
        monkeypatch.delenv("SLACK_SIGNING_SECRET", raising=False)

        response = client.post("/webhooks/slack", json={"type": "url_verification"})

        assert response.status_code == 200
        assert response.json() == {"challenge": ""}


class TestRealEventsStayGated:
    """Answering the challenge must not open the endpoint to anything else."""

    EVENT = {
        "type": "event_callback",
        "event": {"type": "message", "text": "changes are still there",
                  "thread_ts": "1786638974.393459", "channel": "C09WEB123"},
    }

    def test_unconfigured_secret_still_refuses_events(self, client, monkeypatch):
        monkeypatch.delenv("SLACK_SIGNING_SECRET", raising=False)

        assert client.post("/webhooks/slack", json=self.EVENT).status_code == 503

    def test_bad_signature_still_refused(self, client, monkeypatch):
        monkeypatch.setenv("SLACK_SIGNING_SECRET", "s3cret")

        response = client.post("/webhooks/slack", json=self.EVENT, headers={
            "X-Slack-Request-Timestamp": "1786638974",
            "X-Slack-Signature": "v0=" + "0" * 64,
        })

        assert response.status_code == 401

    def test_malformed_body_is_a_400(self, client, monkeypatch):
        monkeypatch.setenv("SLACK_SIGNING_SECRET", "s3cret")

        response = client.post(
            "/webhooks/slack", content=b"{not json",
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 400


class TestSecretIsReadPerRequest:
    def test_setting_the_secret_takes_effect_without_a_restart(
        self, client, monkeypatch
    ):
        """
        Setting up the subscription is an edit-env-then-retry loop. A value
        bound at import means the retry keeps failing for no visible reason.
        """
        event = TestRealEventsStayGated.EVENT

        monkeypatch.delenv("SLACK_SIGNING_SECRET", raising=False)
        assert client.post("/webhooks/slack", json=event).status_code == 503

        monkeypatch.setenv("SLACK_SIGNING_SECRET", "s3cret")
        # Now it gets far enough to reject on the signature instead.
        assert client.post("/webhooks/slack", json=event).status_code == 401


class TestRetriesAreNotReprocessed:
    """
    Slack redelivers an event up to three times when the endpoint takes longer
    than three seconds, and the QA path calls a model and then GitHub, Jira and
    Docs inside the request. A tester's single "didn't work" was answered with
    two identical escalation posts in the same minute.
    """

    import hashlib as _hashlib
    import hmac as _hmac
    import json as _json
    import time as _time

    EVENT = {
        "type": "event_callback",
        "event": {"type": "message", "text": "didnt work",
                  "thread_ts": "1786638974.393459", "channel": "C09WEB123"},
    }

    @classmethod
    def _signed(cls, secret: str = "s3cret"):
        body = cls._json.dumps(cls.EVENT).encode()
        ts = str(int(cls._time.time()))
        base = b"v0:" + ts.encode() + b":" + body
        signature = "v0=" + cls._hmac.new(
            secret.encode(), base, cls._hashlib.sha256
        ).hexdigest()
        return body, {
            "X-Slack-Request-Timestamp": ts,
            "X-Slack-Signature": signature,
            "Content-Type": "application/json",
        }

    def test_a_retry_is_acknowledged_and_dropped(self, client, monkeypatch):
        monkeypatch.setenv("SLACK_SIGNING_SECRET", "s3cret")
        body, headers = self._signed()
        headers["X-Slack-Retry-Num"] = "1"
        headers["X-Slack-Retry-Reason"] = "http_timeout"

        response = client.post("/webhooks/slack", content=body, headers=headers)

        assert response.status_code == 200
        assert response.json() == {"ok": True, "ignored": "retry"}

    def test_the_first_delivery_is_still_processed(self, client, monkeypatch):
        """The guard must key on the retry header, not on the event itself."""
        monkeypatch.setenv("SLACK_SIGNING_SECRET", "s3cret")
        body, headers = self._signed()

        response = client.post("/webhooks/slack", content=body, headers=headers)

        assert response.status_code == 200
        assert response.json().get("ignored") is None

    def test_an_unsigned_request_cannot_skip_the_gate_by_claiming_a_retry(
        self, client, monkeypatch
    ):
        """
        The guard sits after the signature check, so a forged retry header is
        refused rather than quietly accepted with a 200.
        """
        monkeypatch.setenv("SLACK_SIGNING_SECRET", "s3cret")

        response = client.post(
            "/webhooks/slack", json=self.EVENT,
            headers={
                "X-Slack-Request-Timestamp": "1786638974",
                "X-Slack-Signature": "v0=" + "0" * 64,
                "X-Slack-Retry-Num": "1",
            },
        )

        assert response.status_code == 401
