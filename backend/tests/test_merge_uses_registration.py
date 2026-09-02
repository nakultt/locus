"""
A merge run must read its settings from the saved registration.

The reported symptom: the setup form showed "export to Google Doc" ticked and
a QA email filled in, but the merge run skipped both. The values had never
been saved -- the form held unsubmitted local state. These tests pin the
backend half, so a saved setting is provably honoured on merge.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def client(tmp_path):
    from app import main
    from app.core.database import Base, get_db

    engine = create_engine(
        f"sqlite:///{tmp_path}/reg.db", connect_args={"check_same_thread": False}
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
            "/auth/signup", json={"email": "m@x.com", "password": "secret123"}
        ).json()
        c.headers["Authorization"] = f"Bearer {signup['token']}"
        c.session_factory = TestSession  # type: ignore[attr-defined]
        yield c

    main.app.dependency_overrides.clear()


SETTINGS = {
    "repo": "shadowyay/joyyy",
    "slack_channel": "#web",
    "export_to_docs": True,
    "context_docs": [],
    "qa_emails": ["nakulnuked@gmail.com"],
    "jira_done_status": "Done",
    "close_issues_on_merge": True,
}


class TestPersistence:
    def test_docs_and_emails_survive_a_round_trip(self, client):
        created = client.post("/webhooks/repos", json=SETTINGS).json()

        assert created["export_to_docs"] is True
        assert created["qa_emails"] == ["nakulnuked@gmail.com"]

        listed = client.get("/webhooks/repos").json()["repos"][0]
        assert listed["export_to_docs"] is True
        assert listed["qa_emails"] == ["nakulnuked@gmail.com"]

    def test_re_registering_can_turn_a_setting_off(self, client):
        """Re-submitting is how the form saves; it must apply removals too."""
        client.post("/webhooks/repos", json=SETTINGS)
        client.post("/webhooks/repos", json={
            **SETTINGS, "export_to_docs": False, "qa_emails": [],
        })

        listed = client.get("/webhooks/repos").json()["repos"][0]
        assert listed["export_to_docs"] is False
        assert listed["qa_emails"] == []

    def test_listing_reports_what_a_merge_will_actually_use(self, client):
        """
        The UI compares against this to warn about unsaved changes, so it has
        to reflect stored state rather than echo the request.
        """
        client.post("/webhooks/repos", json={**SETTINGS, "export_to_docs": False})

        assert client.get("/webhooks/repos").json()["repos"][0][
            "export_to_docs"
        ] is False


class TestWorkerReadsRegistration:
    @pytest.mark.asyncio
    async def test_merge_passes_saved_settings_through(self, client, monkeypatch):
        """
        Registration says export + QA email; the merge run must ask for both.
        Captures the arguments rather than running the real pipeline.
        """
        from app import models
        from app.routers import webhooks
        from app.schemas import MergeActionResult, PRAnalysisResult, PRContext

        client.post("/webhooks/repos", json=SETTINGS)

        captured: dict = {}

        async def fake_analyze(**kwargs):
            captured.update(kwargs)
            return PRAnalysisResult(context=PRContext(
                repo=kwargs["repo"], pr_number=kwargs["pr_number"],
                title="T", author="a", url="https://x",
                files_changed=1, additions=1, deletions=1,
            ))

        async def fake_merge(result, configs, **kwargs):
            captured["merge_kwargs"] = kwargs
            return MergeActionResult()

        Session = client.session_factory  # type: ignore[attr-defined]
        monkeypatch.setattr(webhooks, "analyze_pull_request", fake_analyze)
        monkeypatch.setattr(webhooks, "run_merge_actions", fake_merge)
        # run_pr_job opens its own session rather than the request's, so the
        # override on get_db does not reach it.
        monkeypatch.setattr(webhooks, "SessionLocal", Session)
        db = Session()
        owner_id = db.query(models.User).filter(
            models.User.email == "m@x.com"
        ).one().id
        job = models.PRJob(
            repo="shadowyay/joyyy", pr_number=3, action=webhooks.MERGE_ACTION,
            status="queued", owner_id=owner_id,
        )
        db.add(job)
        db.commit()
        job_id = job.id
        db.close()

        await webhooks.run_pr_job(job_id)

        assert captured["export_to_docs"] is True, "saved export setting was dropped"
        assert captured["merge_kwargs"]["qa_recipients"] == ["nakulnuked@gmail.com"]
        assert captured["merge_kwargs"]["qa_slack_channel"] == "#web"
        # A merged PR is closed; re-commenting on it is noise.
        assert captured["post_comment"] is False

    @pytest.mark.asyncio
    async def test_merge_without_those_settings_skips_them(self, client, monkeypatch):
        """The state the user actually had: registered before ticking either."""
        from app import models
        from app.routers import webhooks
        from app.schemas import MergeActionResult, PRAnalysisResult, PRContext

        client.post("/webhooks/repos", json={
            **SETTINGS, "export_to_docs": False, "qa_emails": [],
        })

        captured: dict = {}

        async def fake_analyze(**kwargs):
            captured.update(kwargs)
            return PRAnalysisResult(context=PRContext(
                repo=kwargs["repo"], pr_number=kwargs["pr_number"],
                title="T", author="a", url="https://x",
                files_changed=1, additions=1, deletions=1,
            ))

        async def fake_merge(result, configs, **kwargs):
            captured["merge_kwargs"] = kwargs
            return MergeActionResult()

        Session = client.session_factory  # type: ignore[attr-defined]
        monkeypatch.setattr(webhooks, "analyze_pull_request", fake_analyze)
        monkeypatch.setattr(webhooks, "run_merge_actions", fake_merge)
        # run_pr_job opens its own session rather than the request's, so the
        # override on get_db does not reach it.
        monkeypatch.setattr(webhooks, "SessionLocal", Session)
        db = Session()
        owner_id = db.query(models.User).filter(
            models.User.email == "m@x.com"
        ).one().id
        job = models.PRJob(
            repo="shadowyay/joyyy", pr_number=4, action=webhooks.MERGE_ACTION,
            status="queued", owner_id=owner_id,
        )
        db.add(job)
        db.commit()
        job_id = job.id
        db.close()

        await webhooks.run_pr_job(job_id)

        assert captured["export_to_docs"] is False
        assert captured["merge_kwargs"]["qa_recipients"] == []
