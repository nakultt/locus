"""
Suggested fixes: the code that resolves a finding.

A finding tells someone where to look. The change to make is the part they
still have to write, and it is the expensive part. These tests pin the two
things that make a suggestion safe to offer:

**A suggestion is never presented as confirmed.** The scanner confirms the
problem; nothing confirms the fix. A Semgrep finding carries deterministic
authority, and the model-written patch attached to it does not inherit any of
it.

**An Apply button is only rendered where it works, over a range it may touch.**
GitHub renders ```suggestion as an applicable patch on inline review comments
and as an inert code block in the issue-style summary. A suggestion anchored
outside the diff is rejected outright, and one whose range runs past the diff
would overwrite code this PR never touched.
"""

import pytest

from app.schemas import (
    FindingSource,
    PRAnalysisResult,
    PRContext,
    ReviewFinding,
    ReviewPriority,
    SecurityFinding,
    SecuritySeverity,
    SuggestedFix,
)
from app.services import security_scan
from app.services.pr_agent import (
    _fix_candidates,
    build_inline_comments,
    render_pr_comment,
)


def make_context(**overrides) -> PRContext:
    defaults = dict(
        repo="acme/api", pr_number=892, title="Fix webhook timeouts",
        author="nakultt", url="https://github.com/acme/api/pull/892",
        branch="fix/LOC-431", files_changed=1, additions=4, deletions=1,
    )
    return PRContext(**{**defaults, **overrides})


def review_finding(**overrides) -> ReviewFinding:
    defaults = dict(
        priority=ReviewPriority.p1, category="correctness",
        title="Missing ownership check", file_path="api/users.py", line=42,
        description="Any caller can read any user.",
    )
    return ReviewFinding(**{**defaults, **overrides})


FIX = SuggestedFix(
    replacement="    if user.id != resource.owner_id:\n        raise HTTPException(403)",
    start_line=41,
    end_line=42,
    explanation="Rejects a caller who does not own the resource.",
)


class TestCandidateSelection:
    """
    A suggestion renders an Apply button whatever the priority, so offering
    one-click code for a nit invites churn on changes nobody asked for.
    """

    def test_nits_get_no_fix(self):
        p3 = review_finding(priority=ReviewPriority.p3, category="quality")
        assert _fix_candidates([], [], [p3]) == []

    def test_blocking_and_worth_fixing_are_selected(self):
        p1 = review_finding(priority=ReviewPriority.p1)
        p2 = review_finding(priority=ReviewPriority.p2)
        assert _fix_candidates([], [], [p1, p2]) == [p1, p2]

    def test_low_severity_security_is_not_worth_a_model_call(self):
        low = SecurityFinding(
            source=FindingSource.semgrep, severity=SecuritySeverity.low,
            title="Low", file_path="a.py", line=1, description="",
        )
        high = SecurityFinding(
            source=FindingSource.semgrep, severity=SecuritySeverity.high,
            title="High", file_path="a.py", line=2, description="",
        )
        assert _fix_candidates([low, high], [], []) == [high]

    def test_unverified_findings_still_get_a_fix(self):
        """
        The finding is a guess, but the reader is going to evaluate it either
        way -- and the concrete change it implies is what makes it evaluable.
        """
        unverified = SecurityFinding(
            source=FindingSource.llm, severity=SecuritySeverity.medium,
            title="Missing authz", file_path="a.py", line=5, description="",
        )
        assert _fix_candidates([], [unverified], []) == [unverified]


class TestSummaryRendering:
    def test_summary_never_renders_an_applicable_suggestion(self):
        """
        The summary goes to the issues endpoint, where a ```suggestion fence
        is an inert code block. Using it there would render something that
        looks applicable and is not.
        """
        out = render_pr_comment(PRAnalysisResult(
            context=make_context(),
            review_findings=[review_finding(suggested_fix=FIX)],
        ))
        assert "```suggestion" not in out
        assert "if user.id != resource.owner_id:" in out

    def test_a_fix_that_is_not_a_line_replacement_renders_as_prose(self):
        """
        The model reporting it cannot express the fix in one range is useful
        information. What it must not do is show a patch that is incomplete.
        """
        fix = SuggestedFix(
            replacement=None,
            explanation="Needs `import json` at the top of the module.",
        )
        out = render_pr_comment(PRAnalysisResult(
            context=make_context(),
            review_findings=[review_finding(suggested_fix=fix)],
        ))
        assert "Needs `import json`" in out
        assert "Suggested fix" in out

    def test_a_finding_with_no_fix_renders_unchanged(self):
        out = render_pr_comment(PRAnalysisResult(
            context=make_context(), review_findings=[review_finding()],
        ))
        assert "Missing ownership check" in out
        assert "Suggested fix" not in out

    def test_replacement_indentation_survives_rendering(self):
        """
        The replacement is applied verbatim; losing its leading whitespace
        would produce code that does not parse.
        """
        out = render_pr_comment(PRAnalysisResult(
            context=make_context(),
            review_findings=[review_finding(suggested_fix=FIX)],
        ))
        assert "    if user.id != resource.owner_id:" in out


class TestInlineAnchoring:
    """
    GitHub rejects an inline comment anchored outside the diff with a 422, and
    the scanner reads whole reconstructed files -- so a finding can legitimately
    point at code this PR never changed.
    """

    def test_a_fix_inside_the_diff_becomes_an_applicable_suggestion(self):
        result = PRAnalysisResult(
            context=make_context(),
            review_findings=[review_finding(suggested_fix=FIX)],
        )
        comments = build_inline_comments(result, {"api/users.py": {41, 42, 43}})

        assert len(comments) == 1
        assert comments[0]["path"] == "api/users.py"
        # Anchored to the end of the range: GitHub reads start_line upward.
        assert comments[0]["line"] == 42
        assert comments[0]["start_line"] == 41
        assert "```suggestion" in comments[0]["body"]

    def test_a_fix_outside_the_diff_is_not_posted_inline(self):
        result = PRAnalysisResult(
            context=make_context(),
            review_findings=[review_finding(suggested_fix=FIX)],
        )
        assert build_inline_comments(result, {"api/users.py": {90, 91}}) == []

    def test_a_range_extending_past_the_diff_is_refused(self):
        """
        Applying it would overwrite a line this PR never touched.
        """
        result = PRAnalysisResult(
            context=make_context(),
            review_findings=[review_finding(suggested_fix=FIX)],
        )
        # 41 is in the diff, 42 is not.
        assert build_inline_comments(result, {"api/users.py": {41}}) == []

    def test_a_single_line_fix_declares_no_start_line(self):
        """
        GitHub treats a start_line equal to line as a malformed range.
        """
        fix = SuggestedFix(
            replacement="    return None", start_line=42, end_line=42,
        )
        result = PRAnalysisResult(
            context=make_context(),
            review_findings=[review_finding(suggested_fix=fix)],
        )
        comments = build_inline_comments(result, {"api/users.py": {42}})

        assert len(comments) == 1
        assert "start_line" not in comments[0]

    def test_a_file_absent_from_the_diff_is_skipped(self):
        result = PRAnalysisResult(
            context=make_context(),
            review_findings=[review_finding(suggested_fix=FIX)],
        )
        assert build_inline_comments(result, {}) == []

    def test_a_fix_with_no_replacement_is_never_anchored(self):
        """Prose has nothing to apply, so it stays in the summary only."""
        fix = SuggestedFix(replacement=None, explanation="Refactor the module.")
        result = PRAnalysisResult(
            context=make_context(),
            review_findings=[review_finding(suggested_fix=fix)],
        )
        assert build_inline_comments(result, {"api/users.py": {41, 42}}) == []


class TestSecretsAreNeverEchoed:
    def test_a_gitleaks_finding_is_not_a_fix_candidate(self):
        """
        A detected credential is reported by location only. Asking a model to
        write the replacement line would hand it the secret and risk echoing
        it back into a PR comment -- widening the exposure being reported.
        """
        leak = SecurityFinding(
            source=FindingSource.gitleaks, severity=SecuritySeverity.critical,
            title="Possible aws-access-key committed",
            file_path="config/settings.py", line=12,
            description="A value matching a credential pattern was detected.",
        )
        assert leak not in _fix_candidates([leak], [], [])


class TestFixGeneration:
    @pytest.mark.asyncio
    async def test_a_bad_line_range_degrades_to_prose(self, monkeypatch):
        """
        Without a valid range there is nothing to anchor an Apply button to,
        and guessing one would apply the patch to the wrong code.
        """
        async def fake_invoke(_self, _payload):
            class R:
                content = (
                    '[{"index": 0, "replacement": "    x = 1", '
                    '"start_line": 90, "end_line": 40, '
                    '"explanation": "Use one."}]'
                )
            return R()

        monkeypatch.setattr(
            "langchain_core.runnables.base.RunnableSequence.ainvoke", fake_invoke
        )

        finding = review_finding()
        attached, error = await security_scan.suggest_fixes(
            [finding], {"api/users.py": "a\n" * 60}
        )

        assert error is None
        assert attached == 1
        assert finding.suggested_fix.replacement is None
        assert finding.suggested_fix.explanation == "Use one."

    @pytest.mark.asyncio
    async def test_unparseable_output_attaches_nothing(self, monkeypatch):
        """The findings are the product; a broken fix pass must not cost them."""
        async def fake_invoke(_self, _payload):
            class R:
                content = "I could not work out a fix, sorry."
            return R()

        monkeypatch.setattr(
            "langchain_core.runnables.base.RunnableSequence.ainvoke", fake_invoke
        )

        finding = review_finding()
        attached, error = await security_scan.suggest_fixes(
            [finding], {"api/users.py": "a\n" * 60}
        )

        assert attached == 0
        assert error is not None
        assert finding.suggested_fix is None

    @pytest.mark.asyncio
    async def test_a_model_failure_is_reported_not_raised(self, monkeypatch):
        async def boom(_self, _payload):
            raise RuntimeError("model server is down")

        monkeypatch.setattr(
            "langchain_core.runnables.base.RunnableSequence.ainvoke", boom
        )

        finding = review_finding()
        attached, error = await security_scan.suggest_fixes(
            [finding], {"api/users.py": "a\n" * 60}
        )

        assert attached == 0
        assert "model server is down" in error
        assert finding.suggested_fix is None

    @pytest.mark.asyncio
    async def test_a_file_we_cannot_read_is_skipped_without_a_model_call(self):
        """
        The replacement has to match real indentation and line numbers. With
        no file content there is nothing to anchor to, so there is nothing to
        ask the model for either.
        """
        finding = review_finding(file_path="not/fetched.py")
        attached, error = await security_scan.suggest_fixes([finding], {})

        assert (attached, error) == (0, None)
        assert finding.suggested_fix is None


class TestDiffLinePositions:
    """
    An inline comment can only anchor to a line the diff touches; GitHub
    rejects anything else with a 422. The line numbers here are the head
    revision's, which is what the comment API anchors against.
    """

    DIFF = (
        "diff --git a/api/users.py b/api/users.py\n"
        "--- a/api/users.py\n"
        "+++ b/api/users.py\n"
        "@@ -38,6 +38,8 @@ def get_user(user_id):\n"
        "     user = db.get(user_id)\n"
        "     if user is None:\n"
        "         raise NotFound()\n"
        "+    if user.id != resource.owner_id:\n"
        "+        raise HTTPException(403)\n"
        "     return user\n"
    )

    @pytest.mark.asyncio
    async def test_added_and_context_lines_are_commentable(self, monkeypatch):
        from app.services import github_pr

        async def fake_diff(_t, _r, _n):
            return self.DIFF

        monkeypatch.setattr(github_pr, "get_pr_diff", fake_diff)
        positions = await github_pr.get_diff_line_positions("t", "acme/api", 1)

        # The hunk starts at 38 and runs through the six lines shown.
        assert positions["api/users.py"] == {38, 39, 40, 41, 42, 43}

    @pytest.mark.asyncio
    async def test_deleted_lines_are_not_commentable(self, monkeypatch):
        """A removed line exists only on the left; there is nothing to anchor to."""
        from app.services import github_pr

        diff = (
            "--- a/a.py\n"
            "+++ b/a.py\n"
            "@@ -10,2 +10,1 @@\n"
            " kept()\n"
            "-removed()\n"
        )

        async def fake_diff(_t, _r, _n):
            return diff

        monkeypatch.setattr(github_pr, "get_pr_diff", fake_diff)
        positions = await github_pr.get_diff_line_positions("t", "acme/api", 1)

        # Only the kept line, at its new-side number.
        assert positions["a.py"] == {10}


class TestNumberedWindow:
    def test_line_numbers_are_real_file_lines(self):
        """
        The model picks a line range off these numbers. If they did not match
        the file, every suggestion would be anchored to the wrong place.
        """
        source = "\n".join(f"line{n}" for n in range(1, 41))
        window = security_scan._numbered_window(source, line=20)

        assert "20: line20" in window
        assert "8: line8" in window       # 20 - 12 context
        assert "32: line32" in window     # 20 + 12 context
        assert "7: line7" not in window

    def test_a_window_near_the_top_does_not_run_off_the_start(self):
        source = "\n".join(f"line{n}" for n in range(1, 10))
        window = security_scan._numbered_window(source, line=2)

        assert window.startswith("1: line1")

    def test_an_empty_file_yields_no_window(self):
        assert security_scan._numbered_window("", line=3) == ""
