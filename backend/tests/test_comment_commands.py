"""
`@locus` commands over the webhook, end to end.

The comment body is written by anyone who can comment on the pull request. This
runs the real signed path -- HMAC over the raw body, event routing, the stored
analysis lookup -- to check that what a comment can actually cause is bounded.

The case worth naming: Locus's own comment ends with an `@locus ignore` hint,
so a handler that read its own output would be instructing itself. That is the
confused-deputy shape the untrusted-text rules exist to prevent, and it is not
hypothetical here -- the bot posts that text on every analysis.
"""

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models, schemas


@pytest.fixture
def client(tmp_path):
    from app import main
    from app.core.database import Base, get_db

    engine = create_engine(
        f"sqlite:///{tmp_path}/cmd.db", connect_args={"check_same_thread": False}
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
            "/auth/signup", json={"email": "c@x.com", "password": "secret123"}
        ).json()
        c.headers["Authorization"] = f"Bearer {signup['token']}"
        c.session_factory = TestSession  # type: ignore[attr-defined]
        yield c

    main.app.dependency_overrides.clear()


@pytest.fixture
def registered(client):
    return client.post("/webhooks/repos", json={
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


@pytest.fixture
def analyzed(client):
    """A completed analysis for PR 42, so there are findings to dismiss."""
    result = schemas.PRAnalysisResult(
        context=schemas.PRContext(
            repo="acme/widget", pr_number=42, title="t", author="a",
            url="u", branch="b", files_changed=1, additions=1, deletions=0,
        ),
        review_findings=[
            schemas.ReviewFinding(
                priority=schemas.ReviewPriority.p2, category="quality",
                title="Unused import", file_path="api/users.py", line=3,
                description="d",
            ),
        ],
    )

    db = client.session_factory()
    try:
        db.add(models.PRJob(
            repo="acme/widget", pr_number=42, action="opened",
            status=schemas.PRJobStatus.completed.value,
            result_json=result.model_dump_json(), owner_id=1,
        ))
        db.commit()
    finally:
        db.close()


def _send(client, secret, payload, event="issue_comment"):
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


def _comment(body, login="senior-dev", action="created", is_pr=True):
    issue = {"number": 42}
    if is_pr:
        issue["pull_request"] = {"url": "https://api.github.com/x"}
    return {
        "action": action,
        "repository": {"full_name": "acme/widget"},
        "issue": issue,
        "comment": {"body": body, "user": {"login": login}},
    }


def suppressions(client) -> list[models.SuppressedFinding]:
    db = client.session_factory()
    try:
        return db.query(models.SuppressedFinding).all()
    finally:
        db.close()


class TestCommandHandling:
    def test_ignore_records_a_suppression(self, client, registered, analyzed):
        response = _send(
            client, registered["webhook_secret"], _comment("@locus ignore Unused import")
        )

        assert response.status_code == 202
        assert response.json()["suppressed"] == ["Unused import"]

        rows = suppressions(client)
        assert len(rows) == 1
        assert rows[0].suppressed_by == "senior-dev"
        assert rows[0].pr_number == 42

    def test_an_ordinary_comment_changes_nothing(
        self, client, registered, analyzed
    ):
        response = _send(client, registered["webhook_secret"], _comment("LGTM, merging"))

        assert response.json()["message"] == "No command found"
        assert suppressions(client) == []

    def test_an_unmatched_target_is_reported_not_guessed(
        self, client, registered, analyzed
    ):
        """Silencing the wrong finding is invisible; saying nothing matched is not."""
        response = _send(
            client, registered["webhook_secret"],
            _comment("@locus ignore something nobody reported"),
        )

        assert response.json()["unmatched"] == ["something nobody reported"]
        assert suppressions(client) == []


class TestUntrustedInput:
    def test_locus_does_not_obey_its_own_comment(
        self, client, registered, analyzed
    ):
        """
        The posted comment ends with an `@locus ignore` hint. Acting on it
        would make the bot instruct itself into hiding its own findings.
        """
        from app.services.integrations import github_pr

        body = (
            f"{github_pr.COMMENT_MARKER}\n"
            "## Locus PR Context\n"
            "@locus ignore Unused import\n"
        )
        response = _send(client, registered["webhook_secret"], _comment(body))

        assert response.json()["message"] == "Ignoring own comment"
        assert suppressions(client) == []

    def test_an_inline_suggestion_comment_is_also_ignored(
        self, client, registered, analyzed
    ):
        from app.services.integrations import github_pr

        body = f"{github_pr.INLINE_MARKER}\n@locus ignore Unused import"
        response = _send(client, registered["webhook_secret"], _comment(body))

        assert response.json()["message"] == "Ignoring own comment"
        assert suppressions(client) == []

    def test_an_unsigned_comment_is_rejected(self, client, registered, analyzed):
        """The command path is behind the same signature check as everything else."""
        response = client.post(
            "/webhooks/github",
            content=json.dumps(_comment("@locus ignore Unused import")).encode(),
            headers={
                "X-GitHub-Event": "issue_comment",
                "X-Hub-Signature-256": "sha256=deadbeef",
                "Content-Type": "application/json",
            },
        )

        assert response.status_code == 401
        assert suppressions(client) == []

    def test_a_comment_on_a_plain_issue_is_ignored(
        self, client, registered, analyzed
    ):
        """An issue has no findings; only pull request comments carry commands."""
        response = _send(
            client, registered["webhook_secret"],
            _comment("@locus ignore Unused import", is_pr=False),
        )

        assert "non-PR issue" in response.json()["message"]
        assert suppressions(client) == []

    def test_an_edited_comment_is_not_a_fresh_instruction(
        self, client, registered, analyzed
    ):
        response = _send(
            client, registered["webhook_secret"],
            _comment("@locus ignore Unused import", action="edited"),
        )

        assert "Ignoring comment action" in response.json()["message"]
        assert suppressions(client) == []

    def test_a_command_before_any_analysis_does_nothing(self, client, registered):
        """There are no findings to refer to yet."""
        response = _send(
            client, registered["webhook_secret"], _comment("@locus ignore Unused import")
        )

        assert "No analysis" in response.json()["message"]
        assert suppressions(client) == []
