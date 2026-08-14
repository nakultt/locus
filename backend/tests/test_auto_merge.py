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
