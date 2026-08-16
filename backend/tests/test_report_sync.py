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


class TestTicketBrief:
    """
    The body of a document that exists before any code does.

    What it must carry is the requirement as whoever filed it stated it --
    that is the only thing there is to read at this point, and the reason for
    writing the document this early at all.
    """

    def test_the_description_is_carried_in_full(self, db):
        body = report_sync._ticket_brief(
            key="LOC-14",
            title="Rate-limit the export endpoint",
            url="https://acme.atlassian.net/browse/LOC-14",
            status="In Progress",
            assignee="dev",
            priority="High",
            description="Exports are unbounded.\nCap them at 100 rows a minute.",
            events=[],
        )

        assert "LOC-14 — Rate-limit the export endpoint" in body
        assert "Exports are unbounded." in body
        assert "Cap them at 100 rows a minute." in body
        assert "In Progress · dev · High" in body
        assert "https://acme.atlassian.net/browse/LOC-14" in body

    def test_a_missing_description_is_stated_rather_than_left_blank(self, db):
        """
        An empty section reads as a failed fetch. "The ticket has no
        description" is a fact about the ticket, which is different.
        """
        body = report_sync._ticket_brief(
            key="LOC-14", title="Something", url=None, status=None,
            assignee=None, priority=None, description="   ", events=[],
        )

        assert "The ticket has no description." in body

    def test_the_discussion_so_far_is_included(self, db):
        event = schemas.CommunicationEvent(
            id=1, loop="context", channel="slack", direction="received",
            participant="sara", target="dev", body="We agreed on 100/min.",
            permalink="https://slack.example/p1",
            created_at="2026-08-01T09:00:00Z",
        )

        body = report_sync._ticket_brief(
            key="LOC-14", title="Something", url=None, status=None,
            assignee=None, priority=None, description="Do the thing",
            events=[event],
        )

        assert "DISCUSSION SO FAR" in body
        assert "sara in #dev:" in body
        assert "We agreed on 100/min." in body
        assert "https://slack.example/p1" in body

    def test_it_says_no_pull_request_exists_yet(self, db):
        body = report_sync._ticket_brief(
            key="LOC-14", title="Something", url=None, status=None,
            assignee=None, priority=None, description=None, events=[],
        )

        assert "No pull request has been opened" in body


class TestEnsureForTicket:
    """
    A work item owns its document from the moment someone opens the task.

    Idempotent by construction: the second call must return the same link, or
    a task opened twice ends up with two documents and the link already sent
    points at the one nobody is updating.
    """

    @pytest.mark.asyncio
    async def test_a_document_is_created_and_recorded(self, db, monkeypatch):
        created = {}

        async def fake_create(config, *, title, body, db=None, user_id=None):
            created["title"] = title
            created["body"] = body
            return "doc-new"

        monkeypatch.setattr(
            "app.services.pr_agent.create_google_doc", fake_create
        )

        url = await report_sync.ensure_for_ticket(
            db, owner_id=OWNER, key="LOC-14", title="Rate-limit exports",
            integration_configs={"docs": {"access_token": "t"}},
            description="Cap the export.",
        )

        assert url == "https://docs.google.com/document/d/doc-new/edit"
        assert created["title"] == "LOC-14 — Rate-limit exports"
        assert "Cap the export." in created["body"]

        row = db.query(models.PRReport).filter_by(ticket_key="LOC-14").one()
        assert row.document_id == "doc-new"
        # The document started at the ticket, so there is no pull request to
        # name -- which is what the nullable columns exist for.
        assert row.repo is None
        assert row.pr_number is None

    @pytest.mark.asyncio
    async def test_the_second_open_reuses_the_first_document(self, db, monkeypatch):
        calls = []

        async def fake_create(config, *, title, body, db=None, user_id=None):
            calls.append(title)
            return f"doc-{len(calls)}"

        monkeypatch.setattr(
            "app.services.pr_agent.create_google_doc", fake_create
        )
        configs = {"docs": {"access_token": "t"}}

        first = await report_sync.ensure_for_ticket(
            db, owner_id=OWNER, key="LOC-14", title="X", integration_configs=configs
        )
        second = await report_sync.ensure_for_ticket(
            db, owner_id=OWNER, key="LOC-14", title="X", integration_configs=configs
        )

        assert first == second
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_a_pull_request_keyed_document_is_claimed_not_duplicated(
        self, db, monkeypatch
    ):
        """
        Work that started as a pull request keeps the link already sent out.
        Creating a second document here is the exact failure the per-task
        keying exists to prevent, one level up.
        """
        _report(db, document_id="doc-existing")

        async def fake_create(config, *, title, body, db=None, user_id=None):
            raise AssertionError("should not create a second document")

        monkeypatch.setattr(
            "app.services.pr_agent.create_google_doc", fake_create
        )

        url = await report_sync.ensure_for_ticket(
            db, owner_id=OWNER, key="LOC-14", title="X",
            integration_configs={"docs": {"access_token": "t"}},
            repo=REPO, pr_number=PR,
        )

        assert url == "https://docs.google.com/document/d/doc-existing/edit"
        assert db.query(models.PRReport).one().ticket_key == "LOC-14"

    @pytest.mark.asyncio
    async def test_without_docs_connected_the_task_still_renders(self, db):
        assert await report_sync.ensure_for_ticket(
            db, owner_id=OWNER, key="LOC-14", title="X", integration_configs={}
        ) is None
        assert db.query(models.PRReport).count() == 0

    @pytest.mark.asyncio
    async def test_a_failed_creation_costs_the_link_and_nothing_else(
        self, db, monkeypatch
    ):
        """
        A task is worth showing without its document. The document is not
        worth failing the board for.
        """
        async def fake_create(config, *, title, body, db=None, user_id=None):
            raise RuntimeError("Google Docs token could not be refreshed")

        monkeypatch.setattr(
            "app.services.pr_agent.create_google_doc", fake_create
        )

        assert await report_sync.ensure_for_ticket(
            db, owner_id=OWNER, key="LOC-14", title="X",
            integration_configs={"docs": {"access_token": "t"}},
        ) is None
        assert db.query(models.PRReport).count() == 0


class TestTheRetryKeepsTheWholeHistory:
    """
    One document per work item, rewritten in place, means the retry's export
    overwrites the first attempt's. If the render only knows about the current
    pull request, that rewrite silently deletes the reason the retry exists --
    and the link people already have keeps working, now pointing at a document
    that has forgotten the QA rejection.
    """

    def _rejected_first_attempt(self, db):
        """PR #7 merged and was rejected by QA; PR #8 is the fix."""
        first = models.PRReview(
            repo=REPO, pr_number=PR, pr_url="u7", pr_title="Add the export",
            author="dev", state=schemas.ReviewState.merged.value,
            round_number=2, ticket_keys="LOC-14", owner_id=OWNER,
        )
        first.rounds.append(models.PRReviewRound(
            round_number=1,
            outcome=schemas.ReviewOutcome.changes_requested.value,
            reviewer="senior-dev", body="Cap the page size.",
        ))
        db.add(first)
        db.add(models.PRReview(
            repo=REPO, pr_number=8, pr_url="u8", pr_title="Fix the export",
            author="dev", state=schemas.ReviewState.awaiting_review.value,
            round_number=1, ticket_keys="LOC-14", owner_id=OWNER,
        ))
        # The tester's verdict, recorded against the first pull request.
        db.add(models.CommunicationEvent(
            repo=REPO, pr_number=PR, ticket_key="LOC-14",
            loop="qa", direction="received", channel="gmail",
            participant="tester@acme.com",
            body="Still exports everything. Not fixed.",
            succeeded=1, owner_id=OWNER,
        ))
        db.commit()

    def test_the_first_attempts_messages_survive_the_retrys_render(self, db):
        from app.services import comms_log

        self._rejected_first_attempt(db)

        events = comms_log.work_item_history(
            db, owner_id=OWNER, repo=REPO, pr_number=8, ticket_key="LOC-14"
        )

        bodies = [e.body for e in events if e.body]
        assert "Still exports everything. Not fixed." in bodies
        # Marked, so the document does not present it as this PR's own.
        rejection = next(e for e in events if e.body and "Not fixed" in e.body)
        assert rejection.inherited is True

    def test_the_first_attempt_is_named_in_the_document(self, db):
        from app.services import full_report, work_item

        self._rejected_first_attempt(db)

        prior = work_item.sibling_reviews(
            db, owner_id=OWNER, ticket_key="LOC-14", exclude_pr=8
        )
        current = db.query(models.PRReview).filter_by(pr_number=8).one()

        text = full_report.render(
            _result(), review=current, prior_reviews=prior
        )

        assert "EARLIER ATTEMPTS AT THIS WORK" in text
        assert f"{REPO}#{PR}" in text
        # The reviewer's own words from the first attempt, not a summary.
        assert "Cap the page size." in text

    def test_the_retry_writes_to_the_same_document(self, db):
        """
        The point of keying by work item. A second document would leave the
        link already sent to the reviewer and the testing team pointing at the
        first attempt forever.
        """
        _report(db, document_id="doc-shared")
        db.query(models.PRReport).one().ticket_key = "LOC-14"
        db.commit()

        found = report_sync.find_report(
            db, owner_id=OWNER, repo=REPO, pr_number=8, ticket_key="LOC-14"
        )

        assert found.document_id == "doc-shared"

    def test_a_pull_request_with_no_siblings_renders_no_such_section(self, db):
        from app.services import full_report

        text = full_report.render(_result(), prior_reviews=[])

        assert "EARLIER ATTEMPTS AT THIS WORK" not in text
