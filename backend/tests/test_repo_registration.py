"""
Repo registration for the PR Context Agent.

Registration mints the webhook secret that authenticates inbound GitHub
deliveries, so these tests check the secret works exactly once and is never
handed back afterwards.
"""

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path):
    """
    App wired to a throwaway SQLite file via dependency override, rather than
    reloading modules -- reloading re-registers the SQLAlchemy models and
    corrupts the mapper registry.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import main
    from app.database import Base, get_db
    from app.routers import webhooks

    engine = create_engine(
        f"sqlite:///{tmp_path}/t.db", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    main.app.dependency_overrides[get_db] = override_get_db
    webhooks.PUBLIC_BASE_URL = "https://demo.example.com"

    with TestClient(main.app) as c:
        c.post("/auth/signup", json={"email": "r@r.com", "password": "secret123"})
        yield c

    main.app.dependency_overrides.clear()


def sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_registration_returns_usable_webhook_secret(client):
    r = client.post("/webhooks/repos", json={
        "user_id": 1, "repo": "acme/api", "slack_channel": "#dev",
    })
    assert r.status_code == 201
    reg = r.json()
    assert reg["webhook_url"].endswith("/webhooks/github")
    assert len(reg["webhook_secret"]) > 30

    # The minted secret must authenticate a real delivery.
    body = json.dumps({
        "action": "opened",
        "repository": {"full_name": "acme/api"},
        "pull_request": {"number": 7, "draft": False, "head": {"sha": "abc"}},
    }).encode()

    r = client.post("/webhooks/github", content=body, headers={
        "X-GitHub-Event": "pull_request",
        "X-Hub-Signature-256": sign(body, reg["webhook_secret"]),
        "Content-Type": "application/json",
    })
    assert r.status_code == 202
    assert "job_id" in r.json()


def test_secret_is_not_returned_when_listing(client):
    client.post("/webhooks/repos", json={"user_id": 1, "repo": "acme/api"})
    listing = client.get("/webhooks/repos/1").json()

    assert listing["total"] == 1
    assert listing["repos"][0]["webhook_secret"] is None


def test_reregistering_rotates_the_secret(client):
    first = client.post("/webhooks/repos", json={
        "user_id": 1, "repo": "acme/api"}).json()["webhook_secret"]
    second = client.post("/webhooks/repos", json={
        "user_id": 1, "repo": "acme/api"}).json()["webhook_secret"]

    assert first != second

    # The old secret must stop working.
    body = json.dumps({
        "action": "opened",
        "repository": {"full_name": "acme/api"},
        "pull_request": {"number": 1, "draft": False, "head": {"sha": "x"}},
    }).encode()
    r = client.post("/webhooks/github", content=body, headers={
        "X-GitHub-Event": "pull_request",
        "X-Hub-Signature-256": sign(body, first),
        "Content-Type": "application/json",
    })
    assert r.status_code == 401


def test_malformed_repo_slug_is_rejected(client):
    r = client.post("/webhooks/repos", json={"user_id": 1, "repo": "notaslug"})
    assert r.status_code == 422


def test_unknown_user_is_rejected(client):
    r = client.post("/webhooks/repos", json={"user_id": 999, "repo": "acme/api"})
    assert r.status_code == 404


def test_manual_trigger_queues_a_job(client):
    r = client.post("/webhooks/analyze/1/acme/api/42")
    assert r.status_code == 202
    assert r.json()["pr_number"] == 42
    assert r.json()["status"] == "queued"


def test_unregistering_revokes_the_secret(client):
    secret = client.post("/webhooks/repos", json={
        "user_id": 1, "repo": "acme/api"}).json()["webhook_secret"]

    assert client.delete("/webhooks/repos/1/acme/api").status_code == 204

    body = json.dumps({
        "action": "opened",
        "repository": {"full_name": "acme/api"},
        "pull_request": {"number": 1, "draft": False, "head": {"sha": "x"}},
    }).encode()
    r = client.post("/webhooks/github", content=body, headers={
        "X-GitHub-Event": "pull_request",
        "X-Hub-Signature-256": sign(body, secret),
        "Content-Type": "application/json",
    })
    assert r.status_code == 401
