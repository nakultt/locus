"""
Auto-merge on approval, and the gate that guards it.

This is the only path where Locus writes to a repository's default branch with
no human in the loop, so the gate matters more than the merge does. An approval
means "the change is right" -- it does not mean CI passed, and a reviewer may
have clicked approve before the checks finished.

Every test here is a case where merging would have been wrong.
"""

import pytest

from app import models, schemas
from app.services import review_flow


def _review(state=schemas.ReviewState.approved):
    return models.PRReview(
        repo="acme/widget", pr_number=42, state=state.value,
        round_number=1, owner_id=1,
    )


def _analysis(confirmed=(), review_findings=()):
    return schemas.PRAnalysisResult(
        context=schemas.PRContext(
            repo="acme/widget", pr_number=42, title="t",
            url="https://example.invalid/pr/42", author="dev", branch="b",
        ),
        confirmed_findings=list(confirmed),
        review_findings=list(review_findings),
    )


def _finding(severity=schemas.SecuritySeverity.high):
    return schemas.SecurityFinding(
        source=schemas.FindingSource.semgrep,
        severity=severity,
        title="SQL injection",
        file_path="app/db.py",
        description="Unparameterized query",
    )


def _review_finding(priority):
    return schemas.ReviewFinding(
        priority=priority, category="correctness", title="Breaks retry",
        file_path="app/x.py", description="d",
    )


class TestGatePasses:
    def test_approved_green_and_mergeable_merges(self):
        allowed, blockers = review_flow.evaluate_merge_gate(
            _review(), _analysis(), "success", [], True
        )

        assert allowed
        assert blockers == []

    def test_no_analysis_on_record_is_not_a_blocker(self):
        """
        A PR analyzed before the feature existed has no stored result.

        Treating a missing analysis as "unsafe" would make auto-merge refuse
        every PR on an existing install until it happened to be re-analyzed.
        """
        allowed, _ = review_flow.evaluate_merge_gate(
            _review(), None, "success", [], True
        )

        assert allowed

    def test_unverified_findings_do_not_block(self):
        """
        Unverified findings are a model's opinion.

        They are worth reporting, but blocking a merge on one would make
        auto-merge unusable -- and would elevate an unverified finding to the
        authority the confirmed/unverified split exists to deny it.
        """
        analysis = _analysis()
        analysis.unverified_findings = [_finding()]

        allowed, _ = review_flow.evaluate_merge_gate(
            _review(), analysis, "success", [], True
        )

        assert allowed

    @pytest.mark.parametrize("priority", [
        schemas.ReviewPriority.p2,
        schemas.ReviewPriority.p3,
    ])
    def test_p2_and_p3_findings_do_not_block(self, priority):
        """Only p1 means "do not merge this"; the rest are advisory."""
        allowed, _ = review_flow.evaluate_merge_gate(
            _review(), _analysis(review_findings=[_review_finding(priority)]),
            "success", [], True,
        )

        assert allowed


class TestGateHolds:
    def test_unapproved_pr_is_never_merged(self):
        allowed, blockers = review_flow.evaluate_merge_gate(
            _review(schemas.ReviewState.changes_requested),
            _analysis(), "success", [], True,
        )

        assert not allowed
        assert any("not approved" in b for b in blockers)

    def test_failing_ci_blocks_and_names_the_checks(self):
        allowed, blockers = review_flow.evaluate_merge_gate(
            _review(), _analysis(), "failure", ["unit-tests", "lint"], True
        )

        assert not allowed
        # The reviewer reading Slack needs to know which check, not just "CI".
        assert any("unit-tests" in b and "lint" in b for b in blockers)

    def test_unfinished_ci_holds_rather_than_merging(self):
        """
        A reviewer can approve before the checks finish.

        Merging on pending would make approval race CI, which is exactly the
        bug auto-merge is expected not to have.
        """
        allowed, blockers = review_flow.evaluate_merge_gate(
            _review(), _analysis(), "pending", [], True
        )

        assert not allowed
        assert any("not finished" in b for b in blockers)

    def test_merge_conflict_blocks(self):
        allowed, blockers = review_flow.evaluate_merge_gate(
            _review(), _analysis(), "success", [], False
        )

        assert not allowed
        assert any("conflict" in b for b in blockers)

    def test_unknown_mergeability_holds(self):
        """
        GitHub returns null while it recomputes.

        Unknown is not yes. The next event re-evaluates; assuming mergeable
        here would merge into a conflicted base.
        """
        allowed, blockers = review_flow.evaluate_merge_gate(
            _review(), _analysis(), "success", [], None
        )

        assert not allowed

    def test_confirmed_security_finding_blocks(self):
        """
        Confirmed findings are deterministic rule matches, not opinions.

        Auto-merging over one would contradict the reason the
        confirmed/unverified split exists.
        """
        allowed, blockers = review_flow.evaluate_merge_gate(
            _review(), _analysis(confirmed=[_finding()]), "success", [], True
        )

        assert not allowed
        assert any("confirmed security" in b for b in blockers)

    def test_p1_review_finding_blocks(self):
        allowed, blockers = review_flow.evaluate_merge_gate(
            _review(),
            _analysis(review_findings=[
                _review_finding(schemas.ReviewPriority.p1)
            ]),
            "success", [], True,
        )

        assert not allowed
        assert any("P1" in b for b in blockers)

    def test_every_blocker_is_reported_not_just_the_first(self):
        """
        A held merge should say everything wrong with it.

        Fixing CI only to be told about a security finding on the next round
        wastes a full cycle.
        """
        allowed, blockers = review_flow.evaluate_merge_gate(
            _review(), _analysis(confirmed=[_finding()]),
            "failure", ["unit-tests"], False,
        )

        assert not allowed
        assert len(blockers) == 3


class TestGateReporting:
    def test_a_held_merge_always_says_why(self):
        """
        An approved PR that silently stays open reads as a broken feature.
        """
        text = review_flow.format_merge_gate(
            schemas.MergeGateResult(blockers=["CI failing: unit-tests"])
        )

        assert "Not auto-merged" in text
        assert "unit-tests" in text

    def test_a_successful_merge_is_announced(self):
        text = review_flow.format_merge_gate(
            schemas.MergeGateResult(attempted=True, merged=True)
        )

        assert "Auto-merged" in text

    def test_a_rejected_merge_reports_githubs_reason(self):
        """
        GitHub can refuse for reasons the gate cannot see -- unsatisfied
        branch protection, or a required review from someone else.
        """
        text = review_flow.format_merge_gate(schemas.MergeGateResult(
            attempted=True, merged=False,
            detail="GitHub refused the merge (405): Required status check",
        ))

        assert "failed" in text
        assert "405" in text


class TestSettingsDefaultOff:
    def test_auto_merge_is_off_for_an_unregistered_repo(self, tmp_path):
        """
        The dangerous default is on. This must be the safe one.
        """
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from app.database import Base
        from app.services.agent_settings import resolve_settings

        engine = create_engine(f"sqlite:///{tmp_path}/s.db")
        Base.metadata.create_all(bind=engine)
        db = sessionmaker(bind=engine)()
        try:
            settings = resolve_settings(db, owner_id=1, registration=None)
            assert settings.auto_merge_on_approval is False
            assert settings.merge_method == "squash"
        finally:
            db.close()


class TestGateIsRetried:
    """
    Evaluating the gate once, on the approval event, does not work.

    GitHub computes mergeability lazily: the first read after any change
    returns `mergeable: null`, and the approval webhook fires within a second
    of the click. Without a retry the common path is an approved PR that sits
    open forever, which is worse than not having the feature.
    """

    @pytest.fixture
    def approved_repo(self, tmp_path, monkeypatch):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from app import security
        from app.database import Base
        from app.services import automerge

        engine = create_engine(
            f"sqlite:///{tmp_path}/sweep.db",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)
        monkeypatch.setattr(automerge, "SessionLocal", Session)

        db = Session()
        db.add(models.User(
            id=1, email="d@a.com", hashed_password="x", timezone="UTC"))
        db.add(models.Integration(
            service_name="github",
            encrypted_api_key=security.encrypt_token("ghp_x"),
            owner_id=1))
        db.add(models.RepoWebhook(
            repo="acme/widget", encrypted_secret=security.encrypt_token("s"),
            auto_merge_on_approval=1, merge_method="squash",
            jira_done_status="Done", close_issues_on_merge=1,
            enabled=1, owner_id=1))
        db.add(models.PRReview(
            repo="acme/widget", pr_number=42, pr_title="Add retry logic",
            state="approved", round_number=1, owner_id=1))
        db.commit()
        db.close()
        return Session

    @pytest.mark.asyncio
    async def test_a_pr_held_on_unknown_mergeability_merges_on_the_next_sweep(
        self, approved_repo, monkeypatch
    ):
        from app.services import automerge, github_pr

        # First read: GitHub is still computing. Second: it has an answer.
        answers = [
            {"merged": False, "mergeable": None, "head": {"sha": "a1"}},
            {"merged": False, "mergeable": True, "head": {"sha": "a1"}},
        ]

        async def fake_pr(_t, _r, _n):
            return answers.pop(0) if len(answers) > 1 else answers[0]

        async def fake_ci(_t, _r, _s):
            return "success", []

        merged: list[str] = []

        async def fake_merge(_t, repo, number, merge_method="squash",
                             commit_title=None):
            merged.append(f"{repo}#{number}")
            return True, "Merged"

        monkeypatch.setattr(github_pr, "get_pull_request", fake_pr)
        monkeypatch.setattr(github_pr, "get_combined_ci_state", fake_ci)
        monkeypatch.setattr(github_pr, "merge_pull_request", fake_merge)

        # Sweep one: GitHub has not decided yet, so nothing happens.
        assert await automerge.sweep_once() == 0
        assert merged == []

        # Sweep two: it has. Without this retry the PR is stuck forever.
        assert await automerge.sweep_once() == 1
        assert merged == ["acme/widget#42"]

    @pytest.mark.asyncio
    async def test_sweep_skips_repos_with_auto_merge_off(
        self, approved_repo, monkeypatch
    ):
        """The dangerous default stays off, including on the retry path."""
        from app.services import automerge, github_pr

        db = approved_repo()
        try:
            db.query(models.RepoWebhook).one().auto_merge_on_approval = 0
            db.commit()
        finally:
            db.close()

        async def boom(*_a, **_kw):
            raise AssertionError("must not touch GitHub for an opted-out repo")

        monkeypatch.setattr(github_pr, "get_pull_request", boom)

        assert await automerge.sweep_once() == 0

    @pytest.mark.asyncio
    async def test_a_still_blocked_pr_is_silent_on_retry(
        self, approved_repo, monkeypatch
    ):
        """
        Repeating the reason every minute would train people to ignore the
        channel. The blocker was already reported when the approval landed.
        """
        from app.services import automerge, github_pr, review_flow

        async def fake_pr(_t, _r, _n):
            return {"merged": False, "mergeable": False, "head": {"sha": "a1"}}

        async def fake_ci(_t, _r, _s):
            return "success", []

        async def loud(*_a, **_kw):
            raise AssertionError("a held retry must not post to Slack")

        monkeypatch.setattr(github_pr, "get_pull_request", fake_pr)
        monkeypatch.setattr(github_pr, "get_combined_ci_state", fake_ci)
        monkeypatch.setattr(review_flow, "post_review_notification", loud)

        assert await automerge.sweep_once() == 0
