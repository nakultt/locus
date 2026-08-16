"""
Keeping one report document current as the flow moves.

The export used to create a new document on every run, so a PR pushed to five
times had five documents -- each frozen where it was written, and every link
already sent to a reviewer or the testing team pointing at a stale one. The
link is the reason the document is worth writing at all.

These tests pin the two halves: the document id is stable, and the events that
carry no code change still refresh it.
"""

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models, schemas
from app.services import report_sync

REPO, PR, OWNER = "acme/widget", 7, 1


@pytest.fixture
def db(tmp_path):
    from app.database import Base

    engine = create_engine(
        f"sqlite:///{tmp_path}/r.db", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _result():
    return schemas.PRAnalysisResult(
        context=schemas.PRContext(
            repo=REPO, pr_number=PR, title="Restructure",
            author="dev", url=f"https://github.com/{REPO}/pull/{PR}",
        )
    )


def _completed_job(db):
    db.add(models.PRJob(
        repo=REPO, pr_number=PR, action="synchronize",
        status=schemas.PRJobStatus.completed.value,
        result_json=json.dumps(json.loads(_result().model_dump_json())),
        owner_id=OWNER,
    ))
    db.commit()


def _report(db, document_id="doc-abc"):
    db.add(models.PRReport(
        repo=REPO, pr_number=PR, document_id=document_id, owner_id=OWNER,
    ))
    db.commit()


class TestDocumentURL:
    def test_the_url_comes_from_the_stored_id(self, db):
        _report(db)

        url = report_sync.document_url(
            db, owner_id=OWNER, repo=REPO, pr_number=PR
        )

        assert url == "https://docs.google.com/document/d/doc-abc/edit"

    def test_no_report_is_no_url(self, db):
        assert report_sync.document_url(
            db, owner_id=OWNER, repo=REPO, pr_number=PR
        ) is None

    def test_another_users_report_is_not_returned(self, db):
        """Identity comes from the row, never from the repo name alone."""
        _report(db)

        assert report_sync.document_url(
            db, owner_id=999, repo=REPO, pr_number=PR
        ) is None


class TestRefresh:
    @pytest.mark.asyncio
    async def test_it_rewrites_the_existing_document(self, db, monkeypatch):
        """
        The point of the whole change: same document, new contents. A new file
        per event would leave every link already sent pointing at a snapshot.
        """
        _report(db)
        _completed_job(db)
        captured = {}

        async def fake_export(result, config, **kw):
            captured["review_row"] = kw.get("review_row")
            captured["events"] = kw.get("timeline_events")
            return "https://docs.google.com/document/d/doc-abc/edit"

        monkeypatch.setattr(
            "app.services.pr_agent.export_to_google_doc", fake_export
        )

        url = await report_sync.refresh(
            db, owner_id=OWNER, repo=REPO, pr_number=PR,
            integration_configs={"docs": {"credentials": {}}},
        )

        assert url == "https://docs.google.com/document/d/doc-abc/edit"
        assert "events" in captured

    @pytest.mark.asyncio
    async def test_it_does_not_create_a_first_document(self, db, monkeypatch):
        """
        The first document is written by an analysis, which is the only step
        that has read the code. A review event has nothing to describe yet.
        """
        _completed_job(db)
        called = False

        async def fake_export(*a, **kw):
            nonlocal called
            called = True
            return "u"

        monkeypatch.setattr(
            "app.services.pr_agent.export_to_google_doc", fake_export
        )

        url = await report_sync.refresh(
            db, owner_id=OWNER, repo=REPO, pr_number=PR,
            integration_configs={"docs": {"credentials": {}}},
        )

        assert called is False
        assert url is None

    @pytest.mark.asyncio
    async def test_a_failure_returns_the_stored_url(self, db, monkeypatch):
        """
        The notification this decorates is worth sending whether or not the
        document could be brought up to date.
        """
        _report(db)
        _completed_job(db)

        async def boom(*a, **kw):
            raise RuntimeError("Docs is down")

        monkeypatch.setattr(
            "app.services.pr_agent.export_to_google_doc", boom
        )

        url = await report_sync.refresh(
            db, owner_id=OWNER, repo=REPO, pr_number=PR,
            integration_configs={"docs": {"credentials": {}}},
        )

        assert url == "https://docs.google.com/document/d/doc-abc/edit"

    @pytest.mark.asyncio
    async def test_docs_not_connected_is_not_an_error(self, db):
        _report(db)
        _completed_job(db)

        url = await report_sync.refresh(
            db, owner_id=OWNER, repo=REPO, pr_number=PR,
            integration_configs={},
        )

        assert url == "https://docs.google.com/document/d/doc-abc/edit"

    @pytest.mark.asyncio
    async def test_no_analysis_yet_leaves_the_document_alone(
        self, db, monkeypatch
    ):
        """
        Nothing to write. Rendering a report from no analysis would replace a
        real document with an empty one.
        """
        _report(db)
        called = False

        async def fake_export(*a, **kw):
            nonlocal called
            called = True
            return "u"

        monkeypatch.setattr(
            "app.services.pr_agent.export_to_google_doc", fake_export
        )

        url = await report_sync.refresh(
            db, owner_id=OWNER, repo=REPO, pr_number=PR,
            integration_configs={"docs": {"credentials": {}}},
        )

        assert called is False
        assert url == "https://docs.google.com/document/d/doc-abc/edit"


class TestTaskScopedDocument:
    """
    The document belongs to the work item, not the pull request.

    A task routinely spans several pull requests -- the feature, the fix after
    QA rejected it, the follow-up. A document per PR scatters the record across
    those the same way a document per push scattered it across pushes, and
    leaves every link already sent describing only part of the work.
    """

    def test_a_second_pr_on_the_ticket_finds_the_same_document(self, db):
        db.add(models.PRReport(
            repo=REPO, pr_number=42, ticket_key="LOC-42",
            document_id="doc-abc", owner_id=OWNER,
        ))
        db.commit()

        # PR #57 is the fix after QA rejected #42. Nothing was ever written
        # against it directly.
        found = report_sync.find_report(
            db, owner_id=OWNER, repo=REPO, pr_number=57, ticket_key="LOC-42"
        )

        assert found is not None
        assert found.document_id == "doc-abc"

    def test_the_url_is_the_tasks_url_from_any_of_its_prs(self, db):
        db.add(models.PRReport(
            repo=REPO, pr_number=42, ticket_key="LOC-42",
            document_id="doc-abc", owner_id=OWNER,
        ))
        db.commit()

        url = report_sync.document_url(
            db, owner_id=OWNER, repo=REPO, pr_number=57, ticket_key="LOC-42"
        )

        assert url == "https://docs.google.com/document/d/doc-abc/edit"

    def test_a_pre_existing_pr_keyed_row_is_adopted_not_duplicated(self, db):
        """
        Rows written before this existed have no ticket.

        Finding them only by ticket would hand every one a second document and
        leave the link already sent pointing at the older, now-frozen one --
        the exact failure the per-PR document was introduced to avoid.
        """
        db.add(models.PRReport(
            repo=REPO, pr_number=42, ticket_key=None,
            document_id="doc-legacy", owner_id=OWNER,
        ))
        db.commit()

        found = report_sync.find_report(
            db, owner_id=OWNER, repo=REPO, pr_number=42,
            ticket_key="LOC-42", adopt=True,
        )

        assert found.document_id == "doc-legacy"
        # Claimed for the task, so the next PR on it continues this document.
        assert found.ticket_key == "LOC-42"
        assert db.query(models.PRReport).count() == 1

    def test_a_read_only_lookup_does_not_claim(self, db):
        """A lookup that only reads must not mutate."""
        db.add(models.PRReport(
            repo=REPO, pr_number=42, ticket_key=None,
            document_id="doc-legacy", owner_id=OWNER,
        ))
        db.commit()

        report_sync.find_report(
            db, owner_id=OWNER, repo=REPO, pr_number=42,
            ticket_key="LOC-42", adopt=False,
        )

        assert db.query(models.PRReport).one().ticket_key is None

    def test_work_without_a_ticket_still_gets_a_document(self, db):
        """
        A pull request with no tracker reference is ordinary and must keep
        working, keyed by the PR.
        """
        db.add(models.PRReport(
            repo=REPO, pr_number=99, ticket_key=None,
            document_id="doc-untracked", owner_id=OWNER,
        ))
        db.commit()

        found = report_sync.find_report(
            db, owner_id=OWNER, repo=REPO, pr_number=99, ticket_key=None
        )

        assert found.document_id == "doc-untracked"

    def test_a_different_ticket_does_not_share_the_document(self, db):
        db.add(models.PRReport(
            repo=REPO, pr_number=42, ticket_key="LOC-42",
            document_id="doc-abc", owner_id=OWNER,
        ))
        db.commit()

        assert report_sync.find_report(
            db, owner_id=OWNER, repo=REPO, pr_number=58, ticket_key="LOC-99"
        ) is None

    def test_another_users_document_is_never_returned(self, db):
        db.add(models.PRReport(
            repo=REPO, pr_number=42, ticket_key="LOC-42",
            document_id="doc-theirs", owner_id=OWNER + 1,
        ))
        db.commit()

        assert report_sync.find_report(
            db, owner_id=OWNER, repo=REPO, pr_number=42, ticket_key="LOC-42"
        ) is None
