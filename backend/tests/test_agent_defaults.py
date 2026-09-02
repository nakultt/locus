"""
Account-wide defaults, and how they combine with per-repo settings.

The reported symptom: a merge run skipped "Write report to Google Docs" and
"Post summary to Slack" because the repo had no registration row at all, and
every setting lived only on that row. Defaults exist so an unregistered repo
still behaves the way the account is configured.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.services.pipeline.agent_settings import resolve_settings


@pytest.fixture
def db(tmp_path):
    from app.core.database import Base

    engine = create_engine(
        f"sqlite:///{tmp_path}/d.db", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def defaults(db, **kwargs):
    row = models.PRAgentDefaults(owner_id=1, **kwargs)
    db.add(row)
    db.commit()
    return row


def registration(**kwargs):
    base = dict(repo="a/b", encrypted_secret="x", enabled=1, owner_id=1)
    base.update(kwargs)
    return models.RepoWebhook(**base)


class TestUnregisteredRepo:
    def test_falls_back_to_the_account_defaults(self, db):
        """The exact reported case: no registration row at all."""
        defaults(
            db, slack_channel="#web", export_to_docs=1,
            qa_emails="nakulnuked@gmail.com",
        )

        resolved = resolve_settings(db, owner_id=1, registration=None)

        assert resolved.slack_channel == "#web"
        assert resolved.export_to_docs is True
        assert resolved.qa_emails == ["nakulnuked@gmail.com"]

    def test_nothing_configured_anywhere_is_still_safe(self, db):
        resolved = resolve_settings(db, owner_id=1, registration=None)

        assert resolved.slack_channel is None
        assert resolved.export_to_docs is False
        assert resolved.qa_emails == []
        assert resolved.jira_done_status == "Done"
        assert resolved.sources["export_to_docs"] == "unset"


class TestRepoWins:
    def test_repo_channel_overrides_the_default(self, db):
        defaults(db, slack_channel="#general")

        resolved = resolve_settings(
            db, 1, registration(slack_channel="#web-team")
        )

        assert resolved.slack_channel == "#web-team"
        assert resolved.sources["slack_channel"] == "repo"

    def test_repo_emails_override(self, db):
        defaults(db, qa_emails="global@x.com")

        resolved = resolve_settings(db, 1, registration(qa_emails="repo@x.com"))

        assert resolved.qa_emails == ["repo@x.com"]

    def test_blank_repo_value_falls_through(self, db):
        """
        A registration made before a setting existed holds a blank, which must
        read as "not configured" rather than overriding with emptiness.
        """
        defaults(db, slack_channel="#web", export_to_docs=1, qa_emails="qa@x.com")

        resolved = resolve_settings(
            db, 1, registration(slack_channel=None, export_to_docs=0, qa_emails=None)
        )

        assert resolved.slack_channel == "#web"
        assert resolved.export_to_docs is True
        assert resolved.qa_emails == ["qa@x.com"]
        assert resolved.sources["slack_channel"] == "defaults"

    def test_close_issues_false_on_the_repo_is_respected(self, db):
        """False is a real choice here, not an absence."""
        defaults(db, close_issues_on_merge=1)

        resolved = resolve_settings(db, 1, registration(close_issues_on_merge=0))

        assert resolved.close_issues_on_merge is False

    def test_context_docs_accumulate_rather_than_override(self, db):
        """
        The one setting that combines instead of overriding.

        The account-level documents are the standards that apply everywhere --
        a style guide, a security policy. A repo that pins its own spec should
        still be reviewed against those, so letting the repo value win would
        silently drop them.
        """
        defaults(db, context_doc_ids="global1\nglobal2")

        resolved = resolve_settings(db, 1, registration(context_doc_ids="repo1"))

        assert resolved.context_doc_ids == ["global1", "global2", "repo1"]
        assert resolved.sources["context_doc_ids"] == "both"

    def test_global_context_docs_reach_an_unregistered_repo(self, db):
        """The case the whole defaults mechanism exists for."""
        defaults(db, context_doc_ids="global1")

        resolved = resolve_settings(db, 1, registration=None)

        assert resolved.context_doc_ids == ["global1"]
        assert resolved.sources["context_doc_ids"] == "defaults"

    def test_a_document_listed_in_both_is_read_once(self, db):
        """The reviewer reads these under a context budget; duplicates cost it."""
        defaults(db, context_doc_ids="shared\nglobal1")

        resolved = resolve_settings(db, 1, registration(context_doc_ids="shared"))

        assert resolved.context_doc_ids == ["shared", "global1"]


class TestIsolation:
    def test_another_users_defaults_do_not_leak(self, db):
        defaults(db, slack_channel="#mine", qa_emails="mine@x.com")

        resolved = resolve_settings(db, owner_id=2, registration=None)

        assert resolved.slack_channel is None
        assert resolved.qa_emails == []


@pytest.fixture
def client(tmp_path):
    from app import main
    from app.core.database import Base, get_db

    engine = create_engine(
        f"sqlite:///{tmp_path}/api.db", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    main.app.dependency_overrides[get_db] = override
    with TestClient(main.app) as c:
        signup = c.post(
            "/auth/signup", json={"email": "d@x.com", "password": "secret123"}
        ).json()
        c.headers["Authorization"] = f"Bearer {signup['token']}"
        yield c
    main.app.dependency_overrides.clear()


class TestApi:
    def test_get_returns_blanks_before_anything_is_saved(self, client):
        body = client.get("/webhooks/defaults").json()

        assert body["export_to_docs"] is False
        assert body["qa_emails"] == []

    def test_save_and_read_back(self, client):
        client.put("/webhooks/defaults", json={
            "slack_channel": "#web",
            "export_to_docs": True,
            "qa_emails": ["nakulnuked@gmail.com"],
            "jira_done_status": "Done",
            "close_issues_on_merge": True,
        })

        body = client.get("/webhooks/defaults").json()
        assert body["slack_channel"] == "#web"
        assert body["export_to_docs"] is True
        assert body["qa_emails"] == ["nakulnuked@gmail.com"]

    def test_saving_twice_updates_rather_than_duplicating(self, client):
        for channel in ("#one", "#two"):
            client.put("/webhooks/defaults", json={
                "slack_channel": channel, "export_to_docs": False,
                "qa_emails": [], "jira_done_status": "Done",
                "close_issues_on_merge": True,
            })

        assert client.get("/webhooks/defaults").json()["slack_channel"] == "#two"

    def test_malformed_addresses_are_dropped_not_rejected(self, client):
        body = client.put("/webhooks/defaults", json={
            "slack_channel": None, "export_to_docs": False,
            "qa_emails": ["good@x.com", "not-an-address", "  "],
            "jira_done_status": "Done", "close_issues_on_merge": True,
        }).json()

        assert body["qa_emails"] == ["good@x.com"]

    def test_requires_authentication(self, client):
        assert client.get(
            "/webhooks/defaults", headers={"Authorization": "Bearer bad"}
        ).status_code == 401
