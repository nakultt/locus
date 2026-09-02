"""
Webhook body decoding across GitHub's two content types.

A repo can have several hooks configured differently. The "Content type"
setting picks between raw JSON and a form post carrying the JSON in a
`payload` field; the form variant was returning 400 Malformed JSON.
"""

import json
from urllib.parse import urlencode

from app.routers.webhooks import _parse_webhook_body

PAYLOAD = {"action": "closed", "repository": {"full_name": "shadowyay/joyyy"}}


class TestParseWebhookBody:
    def test_plain_json(self):
        raw = json.dumps(PAYLOAD).encode()
        assert _parse_webhook_body(raw, "application/json") == PAYLOAD

    def test_form_encoded(self):
        """What GitHub sends when the hook is set to form content type."""
        raw = urlencode({"payload": json.dumps(PAYLOAD)}).encode()

        assert _parse_webhook_body(raw, "application/x-www-form-urlencoded") == PAYLOAD

    def test_form_encoded_with_charset_suffix(self):
        raw = urlencode({"payload": json.dumps(PAYLOAD)}).encode()
        parsed = _parse_webhook_body(
            raw, "application/x-www-form-urlencoded; charset=utf-8"
        )

        assert parsed == PAYLOAD

    def test_form_encoded_without_a_payload_field(self):
        assert _parse_webhook_body(b"other=1", "application/x-www-form-urlencoded") is None

    def test_malformed_json_still_rejected(self):
        assert _parse_webhook_body(b"{not json", "application/json") is None

    def test_json_array_is_rejected(self):
        """A list parses fine but has no .get; it must not reach the handler."""
        assert _parse_webhook_body(b"[1, 2]", "application/json") is None

    def test_undecodable_bytes(self):
        assert _parse_webhook_body(b"\xff\xfe\x00", "application/json") is None


class TestEndToEnd:
    def test_form_encoded_merge_is_accepted(self, tmp_path):
        """
        The reported failure: a merge delivered as a form post returned 400.
        Signature still covers the raw bytes, so nothing is trusted extra.
        """
        import hashlib
        import hmac

        from fastapi.testclient import TestClient
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from app import main, models
        from app.core import security
        from app.core.database import Base, get_db

        engine = create_engine(
            f"sqlite:///{tmp_path}/wh.db", connect_args={"check_same_thread": False}
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
        secret = "s3cret"

        with TestClient(main.app) as client:
            client.post(
                "/auth/signup", json={"email": "w@x.com", "password": "secret123"}
            )

            db = TestSession()
            owner_id = db.query(models.User).filter(
                models.User.email == "w@x.com"
            ).one().id
            db.add(models.RepoWebhook(
                repo="shadowyay/joyyy",
                encrypted_secret=security.encrypt_token(secret),
                enabled=1,
                owner_id=owner_id,
            ))
            db.commit()
            db.close()

            payload = {
                "action": "closed",
                "repository": {"full_name": "shadowyay/joyyy"},
                "pull_request": {
                    "number": 1, "merged": True, "draft": False,
                    "head": {"sha": "abc123"},
                },
            }
            body = urlencode({"payload": json.dumps(payload)}).encode()
            signature = "sha256=" + hmac.new(
                secret.encode(), body, hashlib.sha256
            ).hexdigest()

            response = client.post("/webhooks/github", content=body, headers={
                "X-GitHub-Event": "pull_request",
                "X-Hub-Signature-256": signature,
                "Content-Type": "application/x-www-form-urlencoded",
            })

        main.app.dependency_overrides.clear()

        assert response.status_code == 202, response.text
        assert "job_id" in response.json()

    def test_form_encoded_with_a_bad_signature_is_still_rejected(self, tmp_path):
        """Accepting the encoding must not weaken verification."""
        from fastapi.testclient import TestClient
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from app import main, models
        from app.core import security
        from app.core.database import Base, get_db

        engine = create_engine(
            f"sqlite:///{tmp_path}/wh2.db", connect_args={"check_same_thread": False}
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

        with TestClient(main.app) as client:
            client.post(
                "/auth/signup", json={"email": "w2@x.com", "password": "secret123"}
            )

            db = TestSession()
            owner_id = db.query(models.User).filter(
                models.User.email == "w2@x.com"
            ).one().id
            db.add(models.RepoWebhook(
                repo="shadowyay/joyyy",
                encrypted_secret=security.encrypt_token("real-secret"),
                enabled=1,
                owner_id=owner_id,
            ))
            db.commit()
            db.close()

            body = urlencode({"payload": json.dumps(PAYLOAD)}).encode()
            response = client.post("/webhooks/github", content=body, headers={
                "X-GitHub-Event": "pull_request",
                "X-Hub-Signature-256": "sha256=" + "0" * 64,
                "Content-Type": "application/x-www-form-urlencoded",
            })

        main.app.dependency_overrides.clear()
        assert response.status_code == 401
