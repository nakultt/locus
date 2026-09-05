"""
The defects a live end-to-end run of autonomous mode surfaced.

Every test here corresponds to something that was silently wrong on a real
ticket -- authored, reviewed, merged and signed off against GitHub, Slack and
Google. They are grouped in one file because they share that provenance: none
of them was caught by the existing suite, and each one failed in a way that
looked like success.
"""

from __future__ import annotations

import asyncio
import subprocess

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.core.database import Base
from app.schemas import (
    PipelineStage,
    PRAnalysisResult,
    PRContext,
    SecurityFinding,
    SecuritySeverity,
    StageState,
)
from app.services import integration_health
from app.services.authoring import authoring_flow
from app.services.pipeline import pr_agent, security_scan

# --------------------------------------------------------------------------
# The deterministic scanners must not depend on which event loop is running.
# --------------------------------------------------------------------------


class TestScannersRunOnAnyEventLoop:
    """
    uvicorn selects a SelectorEventLoop whenever it manages subprocesses of its
    own, which `reload=True` turns on. On Windows that loop cannot spawn a
    subprocess, so `asyncio.create_subprocess_exec` raised NotImplementedError
    -- whose message is the empty string. Semgrep and Gitleaks silently never
    ran, and the PR comment still said "No issues detected in the changed code".
    """

    def test_semgrep_runs_under_a_selector_event_loop(self):
        if not security_scan.semgrep_available():
            pytest.skip("semgrep is not installed")

        vulnerable = {
            "bad.py": "import subprocess\ndef r(c):\n    subprocess.call(c, shell=True)\n"
        }

        async def go():
            return await security_scan.run_semgrep(vulnerable)

        # The loop that used to break this, explicitly.
        loop = asyncio.new_event_loop()
        try:
            findings, error = loop.run_until_complete(go())
        finally:
            loop.close()

        assert error is None, f"semgrep reported an error: {error!r}"
        assert findings, "semgrep found nothing in deliberately vulnerable code"

    def test_a_scanner_failure_never_renders_an_empty_message(self):
        """
        `f"semgrep failed: {e}"` on a NotImplementedError produced
        "semgrep failed: " -- naming neither the cause nor anything to search
        for. The class name always says something.
        """
        assert security_scan._describe(NotImplementedError()) == "NotImplementedError"
        assert security_scan._describe(ValueError("boom")) == "boom"

    def test_run_binary_reports_a_timeout_as_a_timeout(self):
        async def go():
            return await security_scan._run_binary(
                ["python", "-c", "import time; time.sleep(5)"], timeout=1
            )

        loop = asyncio.new_event_loop()
        try:
            with pytest.raises(subprocess.TimeoutExpired):
                loop.run_until_complete(go())
        finally:
            loop.close()


# --------------------------------------------------------------------------
# A pass that failed is not a pass that found nothing.
# --------------------------------------------------------------------------


def _result(**kwargs) -> PRAnalysisResult:
    context = PRContext(
        repo="acme/api", pr_number=1, title="t", author="a", branch="b",
        url="https://github.com/acme/api/pull/1",
    )
    defaults = dict(
        context=context, summary="s", confirmed_findings=[],
        unverified_findings=[], review_findings=[], errors=[],
    )
    defaults.update(kwargs)
    return PRAnalysisResult(**defaults)


class TestBrokenScanNeverReadsAsClean:
    """
    The comment printed "No issues detected in the changed code." and "No
    issues raised." as its headline while the collapsed notes below recorded
    that every pass had failed. That is what let a dead scanner and a
    misdirected model backend sit unnoticed through a whole pipeline run.
    """

    def test_failed_security_pass_does_not_claim_nothing_was_found(self):
        body = pr_agent.render_pr_comment(
            _result(errors=["semgrep failed: NotImplementedError"])
        )
        assert "No issues detected in the changed code." not in body
        assert "did not complete" in body

    def test_failed_code_review_does_not_claim_nothing_was_raised(self):
        body = pr_agent.render_pr_comment(
            _result(errors=["Code review failed: Error code: 400"])
        )
        assert "No issues raised." not in body
        assert "did not complete" in body

    def test_findings_plus_a_failed_pass_are_marked_incomplete(self):
        """
        The more dangerous case: a partial list reads as a complete one, and
        nothing else in the output contradicts it.
        """
        body = pr_agent.render_pr_comment(_result(
            unverified_findings=[SecurityFinding(
                title="Something", severity=SecuritySeverity.medium,
                description="d", file_path="a.py", line=1,
                source=pr_agent.FindingSource.llm,
            )],
            errors=["semgrep failed: NotImplementedError"],
        ))
        assert "incomplete" in body.lower()

    def test_a_clean_run_still_reads_as_clean(self):
        body = pr_agent.render_pr_comment(_result())
        assert "No issues detected in the changed code." in body
        assert "No issues raised." in body
        assert "did not complete" not in body

    def test_an_unrelated_error_does_not_taint_either_section(self):
        """
        Only the passes that actually failed are called incomplete. A Slack
        outage says nothing about whether the code was scanned.
        """
        body = pr_agent.render_pr_comment(
            _result(errors=["Slack post failed: channel_not_found"])
        )
        assert "No issues detected in the changed code." in body
        assert "No issues raised." in body


# --------------------------------------------------------------------------
# One work item, one document.
# --------------------------------------------------------------------------


class _Ticket:
    def __init__(self, key):
        self.key = key


class _Issue:
    def __init__(self, number, relation):
        self.number = number
        self.relation = relation


class _Ctx:
    def __init__(self, tickets=(), linked_issues=()):
        self.tickets = list(tickets)
        self.linked_issues = list(linked_issues)


class TestWorkItemKeyIsOneDefinition:
    """
    The Google Docs export keyed on tracker keys only, while every other
    consumer fell back to the GitHub issue. On a repo with no Jira the export
    therefore saw no work item, skipped the ticket-keyed lookup in
    `report_sync.find_report`, and created a fresh document for each pull
    request -- leaving the document the board links, created from the ticket
    before any PR existed, reading "No pull request has been opened for this
    work yet" long after the work had merged.
    """

    def test_prefers_the_tracker_key(self):
        ctx = _Ctx(tickets=[_Ticket("KAN-3")],
                   linked_issues=[_Issue(1, "closes")])
        assert pr_agent.work_item_keys(ctx, "acme/api") == ["KAN-3"]

    def test_falls_back_to_the_closing_github_issue(self):
        ctx = _Ctx(linked_issues=[_Issue(7, "closes")])
        assert pr_agent.work_item_keys(ctx, "acme/api") == ["acme/api#7"]

    def test_a_mentioned_issue_is_not_a_work_item(self):
        ctx = _Ctx(linked_issues=[_Issue(7, "mentions")])
        assert pr_agent.work_item_keys(ctx, "acme/api") == []

    def test_no_work_item_is_empty_rather_than_guessed(self):
        assert pr_agent.work_item_keys(_Ctx(), "acme/api") == []


# --------------------------------------------------------------------------
# A rework continues the branch the reviewer read.
# --------------------------------------------------------------------------


class TestReworkContinuesTheReviewedBranch:
    """
    `existing_branch=None` was passed for both triggers, directly beneath a
    comment saying a rework continues the branch. Every rework therefore opened
    a second pull request: the review sat on one, the fix on the other, and the
    abandoned PR -- unmerged and `changes_requested` forever -- pinned the task
    board's stage, which reads the furthest state among unmerged PRs.
    """

    def test_strips_a_prefix_the_driver_will_re_add(self):
        assert authoring_flow.bare_title(
            "acme/api#1: Add a thing", "acme/api#1"
        ) == "Add a thing"

    def test_strips_a_prefix_that_already_doubled(self):
        assert authoring_flow.bare_title(
            "acme/api#1: acme/api#1: Add a thing", "acme/api#1"
        ) == "Add a thing"

    def test_leaves_an_unprefixed_title_alone(self):
        assert authoring_flow.bare_title(
            "Add a thing", "acme/api#1"
        ) == "Add a thing"

    def test_a_title_that_is_only_the_key_stays_usable(self):
        assert authoring_flow.bare_title("acme/api#1: ", "acme/api#1") == "acme/api#1"

    def test_reads_the_head_branch_from_github(self, monkeypatch):
        async def fake(token, repo, pr_number):
            return {"head": {"ref": "locus/acme-api-1-1"}}

        monkeypatch.setattr(authoring_flow.github_pr, "get_pull_request", fake)
        branch = asyncio.run(authoring_flow.head_branch(
            "acme/api", 1, {"github": {"api_key": "t"}}
        ))
        assert branch == "locus/acme-api-1-1"

    def test_an_explicit_null_head_does_not_crash(self, monkeypatch):
        """GitHub returns null for optional objects, so .get(k, default) does
        not save you -- the key is present and its value is None."""
        async def fake(token, repo, pr_number):
            return {"head": None}

        monkeypatch.setattr(authoring_flow.github_pr, "get_pull_request", fake)
        assert asyncio.run(authoring_flow.head_branch(
            "acme/api", 1, {"github": {"api_key": "t"}}
        )) is None

    def test_a_failed_lookup_falls_back_rather_than_losing_the_attempt(
        self, monkeypatch
    ):
        async def boom(token, repo, pr_number):
            raise RuntimeError("GitHub is down")

        monkeypatch.setattr(authoring_flow.github_pr, "get_pull_request", boom)
        assert asyncio.run(authoring_flow.head_branch(
            "acme/api", 1, {"github": {"api_key": "t"}}
        )) is None

    def test_no_token_reads_no_branch(self):
        assert asyncio.run(authoring_flow.head_branch("acme/api", 1, {})) is None


# --------------------------------------------------------------------------
# Integration health covers more than Gmail.
# --------------------------------------------------------------------------


OWNER = 1


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    session.add(models.User(
        id=OWNER, email="e2e@a.com", hashed_password="x", timezone="UTC"))
    session.commit()
    try:
        yield session
    finally:
        session.close()


def _stage(key, state):
    return PipelineStage(key=key, label=key, kind="read", state=state)


class TestIntegrationHealthCoversEveryService:
    """
    Only the Gmail poller ever wrote a health row. After a full pipeline run
    making many successful GitHub, Slack and Docs calls the table held one row,
    for gmail -- so "absent" meant both "never attempted" and "attempted
    constantly, never instrumented", and the panel could not tell you your
    GitHub token had expired.
    """

    def test_records_a_success_per_service(self, db):
        integration_health.record_stages(db, owner_id=OWNER, stages=[
            _stage("read_pr", StageState.done),
            _stage("slack_search", StageState.done),
            _stage("docs_export", StageState.done),
        ])
        rows = {
            r.service_name: r
            for r in db.query(models.IntegrationHealth)
            .filter(models.IntegrationHealth.owner_id == OWNER).all()
        }
        assert set(rows) == {"github", "slack", "docs"}
        assert all(r.last_success_at is not None for r in rows.values())

    def test_a_skipped_service_is_absent_rather_than_healthy(
        self, db
    ):
        integration_health.record_stages(db, owner_id=OWNER, stages=[
            _stage("jira", StageState.skipped),
        ])
        assert db.query(models.IntegrationHealth).filter(
            models.IntegrationHealth.owner_id == OWNER,
            models.IntegrationHealth.service_name == "jira",
        ).first() is None

    def test_a_failure_within_a_run_wins_over_a_success(
        self, db
    ):
        """The failure is the part somebody has to act on."""
        integration_health.record_stages(db, owner_id=OWNER, stages=[
            _stage("read_pr", StageState.done),
            _stage("pr_comment", StageState.failed),
        ])
        row = db.query(models.IntegrationHealth).filter(
            models.IntegrationHealth.owner_id == OWNER,
            models.IntegrationHealth.service_name == "github",
        ).first()
        assert row is not None
        assert row.consecutive_failures == 1

    def test_recording_never_raises(self, db):
        """Same rule as comms_log: a run that worked must not be reported as
        broken because the record could not be written."""
        integration_health.record_stages(
            db, owner_id=OWNER, stages=[object()]
        )
        integration_health.record_stages(
            db, owner_id=OWNER, stages=None
        )


# --------------------------------------------------------------------------
# A closed pull request leaves the loop.
# --------------------------------------------------------------------------


class TestClosedPullRequestsAreFinished:
    """
    GitHub sends the same `closed` action for a merge and an abandonment,
    distinguished only by `merged`. The merge half was handled and the other
    half was discarded, so nothing ever left the review loop except by merging.

    An abandoned pull request therefore stayed "in flight" forever, and
    `_derive_stage` reads the furthest state among the pull requests in flight.
    A superseded PR sitting in `changes_requested` pinned its task there for
    good -- the board showed "Changes requested, 2/9" for work that had merged
    and been signed off by QA.
    """

    def _review(self, state, pr_number=1):
        return models.PRReview(
            owner_id=OWNER, repo="acme/api", pr_number=pr_number,
            pr_url="u", pr_title="t", author="a",
            state=state, round_number=1,
        )

    def test_a_closed_pr_does_not_decide_the_stage(self, db):
        from app import schemas
        from app.services.pipeline import task_board

        stage, _ = task_board._derive_stage(
            reviews=[
                self._review(schemas.ReviewState.closed.value, 1),
                self._review(schemas.ReviewState.merged.value, 2),
            ],
            qa=None, analyzed=True,
        )
        assert stage == schemas.TaskStage.merged

    def test_everything_closed_is_not_reported_as_merged(self, db):
        """Abandoned work did not land, and saying it merged is a false claim."""
        from app import schemas
        from app.services.pipeline import task_board

        stage, _ = task_board._derive_stage(
            reviews=[self._review(schemas.ReviewState.closed.value, 1)],
            qa=None, analyzed=True,
        )
        assert stage == schemas.TaskStage.analyzed

    def test_an_open_pr_still_decides_the_stage(self, db):
        from app import schemas
        from app.services.pipeline import task_board

        stage, _ = task_board._derive_stage(
            reviews=[
                self._review(schemas.ReviewState.closed.value, 1),
                self._review(schemas.ReviewState.approved.value, 2),
            ],
            qa=None, analyzed=True,
        )
        assert stage == schemas.TaskStage.approved

    def test_a_round_trip_on_an_abandoned_pr_is_still_history(self, db):
        """`had_changes` spans every attempt: it happened to this task."""
        from app import schemas
        from app.services.pipeline import task_board

        _, had_changes = task_board._derive_stage(
            reviews=[
                self._review(schemas.ReviewState.changes_requested.value, 1),
                self._review(schemas.ReviewState.merged.value, 2),
            ],
            qa=None, analyzed=True,
        )
        assert had_changes is True

    def test_record_closed_sets_the_state(self, db):
        from app import schemas
        from app.services.pipeline import review_flow

        db.add(self._review(schemas.ReviewState.changes_requested.value, 1))
        db.commit()
        row = review_flow.record_closed(
            db, owner_id=OWNER, repo="acme/api", pr_number=1
        )
        assert row.state == schemas.ReviewState.closed.value
        assert row.pending_asks is None

    def test_record_closed_never_walks_back_a_merge(self, db):
        """GitHub closes a PR when it merges; the merge is what matters."""
        from app import schemas
        from app.services.pipeline import review_flow

        db.add(self._review(schemas.ReviewState.merged.value, 1))
        db.commit()
        row = review_flow.record_closed(
            db, owner_id=OWNER, repo="acme/api", pr_number=1
        )
        assert row.state == schemas.ReviewState.merged.value

    def test_an_unreviewed_pr_invents_no_record(self, db):
        from app.services.pipeline import review_flow

        assert review_flow.record_closed(
            db, owner_id=OWNER, repo="acme/api", pr_number=99
        ) is None

    def test_a_closed_pr_is_not_waiting_on_you(self, db):
        from app import schemas
        from app.services.pipeline import worklist

        db.add(self._review(schemas.ReviewState.closed.value, 1))
        db.commit()
        result = worklist.build(db, owner_id=OWNER)
        keys = [
            t.key for t in (result.needs_you + result.waiting_on_others)
        ]
        assert "acme/api#1" not in keys
        assert result.total_needs_you == 0

    def test_an_open_pr_is_still_waiting_on_you(self, db):
        """The filter removes finished work, not the list's whole purpose."""
        from app import schemas
        from app.services.pipeline import worklist

        db.add(self._review(schemas.ReviewState.changes_requested.value, 2))
        db.commit()
        result = worklist.build(db, owner_id=OWNER)
        keys = [
            t.key for t in (result.needs_you + result.waiting_on_others)
        ]
        assert "acme/api#2" in keys


# --------------------------------------------------------------------------
# The report renderer must survive a suggested fix.
# --------------------------------------------------------------------------


class TestSuggestedFixRendersInTheReport:
    """
    `suggested_fix` is a `SuggestedFix`, not a string, and the report handed
    the object straight to a helper that calls `.strip()`. Every render of a
    review finding carrying a fix raised `'SuggestedFix' object has no
    attribute 'strip'`.

    It was invisible because `report_sync.refresh` swallows its own failure and
    returns the stored URL -- deliberately, so a broken export cannot stop the
    notification it decorates. The document silently stopped being updated from
    the review and QA paths while every link to it kept working, so it still
    read "No pull request has been opened for this work yet" long after the
    work had merged.
    """

    def _finding(self, fix):
        from app import schemas
        return schemas.ReviewFinding(
            priority=schemas.ReviewPriority.p1,
            title="Something",
            description="d",
            file_path="a.py",
            line=1,
            category="correctness",
            suggested_fix=fix,
        )

    def _render(self, finding):
        from app.services.pipeline import full_report
        return "\n".join(full_report._render_fix(finding.suggested_fix))

    def test_renders_a_replacement_without_raising(self):
        from app import schemas
        fix = schemas.SuggestedFix(
            replacement="x = 1\n", start_line=10, end_line=11,
            explanation="because",
        )
        out = self._render(self._finding(fix))
        assert "x = 1" in out
        assert "lines 10-11" in out
        assert "because" in out

    def test_a_fix_with_no_replacement_still_explains_itself(self):
        """`replacement` is None exactly when the explanation is the answer."""
        from app import schemas
        fix = schemas.SuggestedFix(
            replacement=None, explanation="Needs a migration in another file.",
        )
        out = self._render(self._finding(fix))
        assert "migration" in out
        assert "Suggested replacement" not in out

    def test_the_whole_report_renders_with_a_fix_attached(self):
        """The end-to-end shape: this is what actually raised."""
        from app import schemas
        from app.services.pipeline import full_report

        result = _result(review_findings=[self._finding(
            schemas.SuggestedFix(
                replacement="y = 2\n", start_line=1, end_line=1,
                explanation="why",
            )
        )])
        text = full_report.render(result)
        assert "y = 2" in text
        assert "SuggestedFix" not in text


# --------------------------------------------------------------------------
# Git must never wait for a human.
# --------------------------------------------------------------------------


class TestGitIsNonInteractive:
    """
    The driver pushed to a bare `origin`, relying on whatever credential helper
    happened to be installed. On Windows that opens an account picker, so the
    push blocked until the attempt timed out -- spending it on a dialog nobody
    was awake to see. On a server there is no helper at all and the prompt
    fails in a way that reads like a rejected push.

    An agent that runs unattended cannot answer either, so prompting is
    disabled and authentication is explicit.
    """

    def test_a_credential_in_a_url_is_redacted(self):
        from app.services.authoring import workspace as ws
        msg = "fatal: unable to access https://x-access-token:ghp_SECRET@github.com/a/b.git/"
        out = ws.redact(msg)
        assert "ghp_SECRET" not in out
        assert "***:***" in out
        assert "github.com/a/b.git" in out

    def test_redaction_leaves_ordinary_text_alone(self):
        from app.services.authoring import workspace as ws
        assert ws.redact("Push rejected: non-fast-forward") == (
            "Push rejected: non-fast-forward"
        )

    def test_a_network_call_fails_fast_instead_of_prompting(self, tmp_path):
        """The whole point: no dialog, no hang, a prompt-disabled error."""
        from app.services.authoring import workspace as ws
        ws.run_git(["init", "-q"], tmp_path)
        result = ws.run_git(
            ["fetch", "https://github.com/nakultt/does-not-exist-locus-test.git"],
            tmp_path, check=False, timeout=60,
        )
        assert result.returncode != 0
        assert "terminal prompts disabled" in (result.stderr or "").lower()

    def test_an_https_remote_gets_the_token(self, tmp_path):
        from app.services.authoring import workspace as ws
        ws.run_git(["init", "-q"], tmp_path)
        ws.run_git(["remote", "add", "origin", "https://github.com/acme/api.git"], tmp_path)
        assert ws.authenticated_remote(tmp_path, "TKN") == (
            "https://x-access-token:TKN@github.com/acme/api.git"
        )

    def test_the_host_is_taken_from_the_remote_not_assumed(self, tmp_path):
        """GitHub Enterprise lives somewhere else."""
        from app.services.authoring import workspace as ws
        ws.run_git(["init", "-q"], tmp_path)
        ws.run_git(
            ["remote", "add", "origin", "https://ghe.acme.internal/acme/api.git"],
            tmp_path,
        )
        assert ws.authenticated_remote(tmp_path, "TKN").startswith(
            "https://x-access-token:TKN@ghe.acme.internal/"
        )

    def test_existing_credentials_are_not_doubled_up(self, tmp_path):
        from app.services.authoring import workspace as ws
        ws.run_git(["init", "-q"], tmp_path)
        ws.run_git(
            ["remote", "add", "origin", "https://old:secret@github.com/acme/api.git"],
            tmp_path,
        )
        out = ws.authenticated_remote(tmp_path, "TKN")
        assert out == "https://x-access-token:TKN@github.com/acme/api.git"
        assert "old:secret" not in out

    def test_a_non_https_remote_is_left_alone(self, tmp_path):
        """ssh and local paths carry their own credentials, or need none."""
        from app.services.authoring import workspace as ws
        ws.run_git(["init", "-q"], tmp_path)
        ws.run_git(["remote", "add", "origin", "git@github.com:acme/api.git"], tmp_path)
        assert ws.authenticated_remote(tmp_path, "TKN") == "origin"

    def test_no_token_means_no_rewriting(self, tmp_path):
        from app.services.authoring import workspace as ws
        ws.run_git(["init", "-q"], tmp_path)
        ws.run_git(["remote", "add", "origin", "https://github.com/acme/api.git"], tmp_path)
        assert ws.authenticated_remote(tmp_path, None) == "origin"


# --------------------------------------------------------------------------
# The channel a tester replies through must not change the record.
# --------------------------------------------------------------------------


class TestQAReplyRefreshesTheReportOnBothChannels:
    """
    The Slack QA path rewrote the report document after a reply; the email path
    did not. So the report ended with the merge and never recorded the tester's
    verdict whenever they replied by email -- which is the ordinary case, since
    the QA brief reaches them there.

    `close_on_qa_signoff` is deliberately identical across both channels
    because "the channel a tester chose must not change the outcome". The
    document is part of that outcome: it is the whole record, and the verdict
    is the one thing a later reader most wants from it.
    """

    def test_the_email_poller_refreshes_the_report(self):
        import inspect

        from app.services.pipeline import qa_email_poller

        source = inspect.getsource(qa_email_poller.poll_once)
        assert "report_sync.refresh" in source, (
            "a QA reply by email must rewrite the report, as the Slack path does"
        )

    def test_both_paths_refresh(self):
        """Neither channel is allowed to be the one that forgets."""
        import inspect

        from app.routers import slack_events
        from app.services.pipeline import qa_email_poller

        slack_src = inspect.getsource(slack_events)
        email_src = inspect.getsource(qa_email_poller)
        assert "report_sync.refresh" in slack_src
        assert "report_sync.refresh" in email_src

    def test_a_failed_refresh_does_not_lose_the_signoff(self, monkeypatch):
        """
        Recording the sign-off is the work; rewriting the document describes
        it. A document that cannot be written must not turn a sign-off that
        genuinely happened into a failure.
        """
        import inspect

        from app.services.pipeline import qa_email_poller

        source = inspect.getsource(qa_email_poller.poll_once)
        refresh_at = source.index("report_sync.refresh")
        preceding = source[:refresh_at]
        assert preceding.rstrip().endswith("try:") or "try:" in preceding[-200:], (
            "the refresh must be guarded so it cannot fail the sign-off"
        )


# --------------------------------------------------------------------------
# The board can say the agent is working.
# --------------------------------------------------------------------------


class TestAuthoringAttemptHasAState:
    """
    The attempt row was written only once the driver returned, which cost two
    things.

    The board could not say the agent was working: a card read `assigned` for
    the ten minutes a run takes, indistinguishable from one nobody had
    started. And a process that died mid-run left no row at all, so the bound
    never counted it -- "every failure consumes an attempt" held for every
    failure the driver reported, and not for the one that killed it.
    """

    def _request(self, **kw):
        from app.services.authoring.authoring import AuthoringRequest
        base = dict(
            ticket_key="acme/api#1", title="Do the thing", repo="acme/api",
            attempt=1, trigger="initial",
        )
        base.update(kw)
        return AuthoringRequest(**base)

    def _result(self, **kw):
        from app.services.authoring.authoring import AuthoringResult
        base = dict(opened=True, pr_number=7, driver="opencode")
        base.update(kw)
        return AuthoringResult(**base)

    def test_begin_marks_the_attempt_running(self, db):
        from app.services.authoring import authoring
        row = authoring.begin_attempt(db, owner_id=OWNER, request=self._request())
        assert row is not None
        assert row.state == "running"
        assert row.finished_at is None

    def test_a_running_attempt_is_visible_to_the_board(self, db):
        from app.services.authoring import authoring
        authoring.begin_attempt(db, owner_id=OWNER, request=self._request())
        running = authoring.running_attempts(db, owner_id=OWNER)
        assert "acme/api#1" in running

    def test_recording_updates_the_same_row(self, db):
        """
        One run is one row. Two would double-count against the bound, which is
        the thing the history exists to make real.
        """
        from app import models
        from app.services.authoring import authoring

        started = authoring.begin_attempt(db, owner_id=OWNER, request=self._request())
        authoring.record_attempt(
            db, owner_id=OWNER, request=self._request(),
            result=self._result(), started=started,
        )
        rows = db.query(models.AuthoringAttempt).filter(
            models.AuthoringAttempt.ticket_key == "acme/api#1"
        ).all()
        assert len(rows) == 1
        assert rows[0].state == "finished"
        assert rows[0].finished_at is not None
        assert rows[0].pr_number == 7

    def test_a_finished_attempt_is_no_longer_running(self, db):
        from app.services.authoring import authoring
        started = authoring.begin_attempt(db, owner_id=OWNER, request=self._request())
        authoring.record_attempt(
            db, owner_id=OWNER, request=self._request(),
            result=self._result(), started=started,
        )
        assert authoring.running_attempts(db, owner_id=OWNER) == {}

    def test_recording_without_a_start_still_works(self, db):
        """
        Backwards compatible: a caller that never called `begin_attempt`
        inserts, exactly as before.
        """
        from app import models
        from app.services.authoring import authoring

        authoring.record_attempt(
            db, owner_id=OWNER, request=self._request(), result=self._result(),
        )
        rows = db.query(models.AuthoringAttempt).all()
        assert len(rows) == 1
        assert rows[0].state == "finished"

    def test_a_crash_mid_run_still_consumes_the_attempt(self, db):
        """
        The row exists from the moment the driver is invoked, so a process
        that dies leaves evidence and the bound counts it.
        """
        from app.services.authoring import authoring
        authoring.begin_attempt(db, owner_id=OWNER, request=self._request())
        # No record_attempt -- the process died here.
        assert len(authoring.attempts_for(db, OWNER, "acme/api#1")) == 1

    def test_begin_never_raises(self, db, monkeypatch):
        """The run is the work; losing the marker must not lose the run."""
        from app.services.authoring import authoring

        def boom(*a, **k):
            raise RuntimeError("database is gone")

        monkeypatch.setattr(db, "commit", boom)
        assert authoring.begin_attempt(
            db, owner_id=OWNER, request=self._request()
        ) is None

    def test_running_is_scoped_to_the_owner(self, db):
        from app.services.authoring import authoring
        authoring.begin_attempt(db, owner_id=OWNER, request=self._request())
        assert authoring.running_attempts(db, owner_id=OWNER + 99) == {}
