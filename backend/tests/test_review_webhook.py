"""
Review events over the webhook, end to end.

The review loop only exists if GitHub's events actually reach it. These tests
run the real signed-webhook path: HMAC over the raw body, event routing, and
the queued job that carries the reviewer's verdict to the worker.

The verdict travels in the job row rather than being re-fetched later, because
by the time the worker runs, the review that fired the webhook may already have
been superseded by another one.
"""

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def client(tmp_path):
    from app import main
    from app.core.database import Base, get_db

    engine = create_engine(
        f"sqlite:///{tmp_path}/hooks.db", connect_args={"check_same_thread": False}
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
        signup = c.post(
            "/auth/signup", json={"email": "r@x.com", "password": "secret123"}
        ).json()
        c.headers["Authorization"] = f"Bearer {signup['token']}"
        c.session_factory = TestSession  # type: ignore[attr-defined]
        yield c

    main.app.dependency_overrides.clear()


@pytest.fixture
def registered(client):
    """Register a repo and hand back its one-time webhook secret."""
    reg = client.post("/webhooks/repos", json={
        "repo": "acme/widget",
        "slack_channel": "#dev",
        "export_to_docs": False,
        "context_docs": [],
        "qa_emails": [],
        "jira_done_status": "Done",
        "close_issues_on_merge": True,
        "reviewers": ["@senior-dev"],
        "review_slack_channel": "#code-review",
    }).json()
    return reg


def _send(client, secret, event, payload):
    """POST a correctly signed webhook, the way GitHub would."""
    body = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(
        secret.encode(), body, hashlib.sha256
    ).hexdigest()

    return client.post(
        "/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": event,
            "X-Hub-Signature-256": signature,
            "Content-Type": "application/json",
        },
    )


def _pr(number=42, draft=False):
    return {
        "number": number,
        "html_url": f"https://github.com/acme/widget/pull/{number}",
        "title": "Add retry logic",
        "draft": draft,
        "user": {"login": "junior-dev"},
        "head": {"sha": "abc1234"},
    }


class TestRegistrationCarriesReviewers:
    def test_reviewers_survive_a_round_trip(self, client, registered):
        assert registered["reviewers"] == ["senior-dev"]  # the @ is stripped
        assert registered["review_slack_channel"] == "#code-review"

        listed = client.get("/webhooks/repos").json()["repos"][0]
        assert listed["reviewers"] == ["senior-dev"]


class TestEventRouting:
    def test_submitted_review_queues_a_job_carrying_the_verdict(
        self, client, registered
    ):
        response = _send(client, registered["webhook_secret"], "pull_request_review", {
            "action": "submitted",
            "repository": {"full_name": "acme/widget"},
            "pull_request": _pr(),
            "review": {
                "state": "changes_requested",
                "body": "Please add a test.",
                "user": {"login": "senior-dev"},
            },
        })

        assert response.status_code == 202
        assert response.json()["message"] == "Review event queued"

        from app import models
        db = client.session_factory()
        try:
            job = db.query(models.PRJob).one()
            assert job.action == "review_submitted"
            payload = json.loads(job.payload_json)
            # The verdict and the reviewer's words travel with the job.
            assert payload["review_state"] == "changes_requested"
            assert payload["reviewer"] == "senior-dev"
            assert payload["body"] == "Please add a test."
            assert payload["author"] == "junior-dev"
        finally:
            db.close()

    def test_edited_review_is_ignored(self, client, registered):
        """Rewriting a review body is not a fresh decision."""
        response = _send(client, registered["webhook_secret"], "pull_request_review", {
            "action": "edited",
            "repository": {"full_name": "acme/widget"},
            "pull_request": _pr(),
            "review": {"state": "approved", "user": {"login": "senior-dev"}},
        })

        assert "Ignoring review action" in response.json()["message"]

    def test_review_requested_queues_with_the_requested_person(
        self, client, registered
    ):
        response = _send(client, registered["webhook_secret"], "pull_request", {
            "action": "review_requested",
            "repository": {"full_name": "acme/widget"},
            "pull_request": _pr(),
            "requested_reviewer": {"login": "senior-dev"},
        })

        assert response.status_code == 202

        from app import models
        db = client.session_factory()
        try:
            job = db.query(models.PRJob).one()
            assert job.action == "review_requested"
            assert json.loads(job.payload_json)["reviewer"] == "senior-dev"
        finally:
            db.close()

    def test_team_review_request_falls_back_to_the_team_slug(
        self, client, registered
    ):
        """GitHub sends requested_team instead of requested_reviewer for teams."""
        _send(client, registered["webhook_secret"], "pull_request", {
            "action": "review_requested",
            "repository": {"full_name": "acme/widget"},
            "pull_request": _pr(),
            "requested_team": {"slug": "platform"},
        })

        from app import models
        db = client.session_factory()
        try:
            job = db.query(models.PRJob).one()
            assert json.loads(job.payload_json)["reviewer"] == "platform"
        finally:
            db.close()

    def test_ordinary_pr_events_still_analyze(self, client, registered):
        """The review path must not swallow the analysis path."""
        response = _send(client, registered["webhook_secret"], "pull_request", {
            "action": "opened",
            "repository": {"full_name": "acme/widget"},
            "pull_request": _pr(),
        })

        assert response.json()["message"] == "Analysis queued"

    def test_draft_pr_review_is_ignored(self, client, registered):
        response = _send(client, registered["webhook_secret"], "pull_request_review", {
            "action": "submitted",
            "repository": {"full_name": "acme/widget"},
            "pull_request": _pr(draft=True),
            "review": {"state": "approved", "user": {"login": "senior-dev"}},
        })

        assert response.json()["message"] == "Ignoring draft PR"


class TestReviewEventsAreStillAuthenticated:
    def test_bad_signature_on_a_review_is_rejected(self, client, registered):
        """
        The review path must not become an unauthenticated write.

        It reaches the same job table as the analysis path, so a missing
        signature check here would be a way in regardless of the other one.
        """
        body = json.dumps({
            "action": "submitted",
            "repository": {"full_name": "acme/widget"},
            "pull_request": _pr(),
            "review": {"state": "approved", "user": {"login": "attacker"}},
        }).encode()

        response = client.post(
            "/webhooks/github",
            content=body,
            headers={
                "X-GitHub-Event": "pull_request_review",
                "X-Hub-Signature-256": "sha256=" + "0" * 64,
                "Content-Type": "application/json",
            },
        )

        assert response.status_code == 401

        from app import models
        db = client.session_factory()
        try:
            assert db.query(models.PRJob).count() == 0
        finally:
            db.close()


class TestReviewQueryEndpoints:
    def test_empty_queue_is_not_an_error(self, client):
        body = client.get("/webhooks/reviews").json()
        assert body["total"] == 0
        assert body["reviews"] == []

    def test_missing_review_is_404(self, client):
        assert client.get("/webhooks/reviews/acme/widget/999").status_code == 404

    def test_another_users_review_is_404_not_403(self, client, tmp_path):
        """
        A 403 would confirm the review exists, which is enough to enumerate
        other people's repositories.
        """
        from app import models

        db = client.session_factory()
        try:
            db.add(models.PRReview(
                repo="acme/secret",
                pr_number=7,
                state="awaiting_review",
                round_number=1,
                owner_id=9999,  # somebody else
            ))
            db.commit()
        finally:
            db.close()

        assert client.get("/webhooks/reviews/acme/secret/7").status_code == 404

    def test_queue_lists_open_reviews_and_counts_states(self, client):
        from app import models

        db = client.session_factory()
        try:
            me = db.query(models.User).one().id
            db.add_all([
                models.PRReview(
                    repo="acme/widget", pr_number=1, state="awaiting_review",
                    round_number=1, owner_id=me,
                ),
                models.PRReview(
                    repo="acme/widget", pr_number=2, state="changes_requested",
                    round_number=3, owner_id=me,
                ),
                models.PRReview(
                    repo="acme/widget", pr_number=3, state="merged",
                    round_number=2, owner_id=me,
                ),
            ])
            db.commit()
        finally:
            db.close()

        body = client.get("/webhooks/reviews").json()

        # Merged PRs are done; the queue shows what still needs attention.
        assert body["total"] == 2
        assert body["awaiting_review"] == 1
        assert body["changes_requested"] == 1

        with_merged = client.get("/webhooks/reviews?include_merged=true").json()
        assert with_merged["total"] == 3
