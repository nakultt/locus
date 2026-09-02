"""
What moved between analysis rounds.

The question a reviewer asks on round three is "did they fix what I flagged in
round two". Both halves of the answer were already stored -- the review loop
counts rounds, every run stores its findings -- and nothing joined them, so it
had to be answered by eye-diffing two comments.

The load-bearing decision here is that a finding is identified by file and
title, never by line number. Anyone inserting a line above a finding shifts it,
and a line-keyed diff would report every surviving finding as resolved with an
identical one newly introduced -- which is worse than reporting nothing.
"""

import json

from app import schemas
from app.services.pipeline import finding_diff
from app.services.pipeline.pr_agent import render_pr_comment


def context() -> schemas.PRContext:
    return schemas.PRContext(
        repo="acme/api", pr_number=892, title="t", author="a", url="u",
        branch="b", files_changed=1, additions=1, deletions=0,
    )


def review(title: str, path: str = "api/users.py", line: int = 42):
    return schemas.ReviewFinding(
        priority=schemas.ReviewPriority.p1, category="correctness",
        title=title, file_path=path, line=line, description="d",
    )


def result_with(*findings) -> schemas.PRAnalysisResult:
    return schemas.PRAnalysisResult(
        context=context(), review_findings=list(findings)
    )


def stored(*findings) -> dict:
    return json.loads(result_with(*findings).model_dump_json())


class TestIdentity:
    def test_a_finding_that_moved_down_the_file_is_not_new(self):
        """
        The regression this exists to prevent: someone adds an import, every
        finding shifts, and a line-keyed diff calls the whole set resolved and
        reintroduced.
        """
        before = stored(review("No ownership check", line=42))
        current = result_with(review("No ownership check", line=57))

        delta = finding_diff.compare(current, before)

        assert delta.resolved == []
        assert delta.introduced == []
        assert len(delta.persisting) == 1

    def test_the_same_title_in_another_file_is_a_separate_finding(self):
        before = stored(review("Missing check", path="api/users.py"))
        current = result_with(review("Missing check", path="api/orders.py"))

        delta = finding_diff.compare(current, before)

        assert len(delta.resolved) == 1
        assert len(delta.introduced) == 1

    def test_rewording_of_case_and_spacing_is_the_same_finding(self):
        """A model rewrapping its own title is not a new defect."""
        before = stored(review("No  ownership check"))
        current = result_with(review("no ownership CHECK"))

        delta = finding_diff.compare(current, before)

        assert delta.resolved == []
        assert len(delta.persisting) == 1


class TestComparison:
    def test_a_fixed_finding_is_reported_resolved(self):
        before = stored(review("No ownership check"), review("Unused import"))
        current = result_with(review("Unused import"))

        delta = finding_diff.compare(current, before)

        assert len(delta.resolved) == 1
        assert "No ownership check" in delta.resolved[0]

    def test_a_new_finding_is_reported_introduced(self):
        before = stored(review("Unused import"))
        current = result_with(review("Unused import"), review("Race on cache"))

        delta = finding_diff.compare(current, before)

        assert len(delta.introduced) == 1
        assert "Race on cache" in delta.introduced[0]

    def test_security_and_review_findings_share_one_namespace(self):
        """
        A reviewer reading "2 no longer reported" does not care which pass
        produced them.
        """
        before = json.loads(schemas.PRAnalysisResult(
            context=context(),
            confirmed_findings=[schemas.SecurityFinding(
                source=schemas.FindingSource.semgrep,
                severity=schemas.SecuritySeverity.high,
                title="Shell injection", file_path="a.py", line=1,
                description="d",
            )],
        ).model_dump_json())
        current = result_with()

        delta = finding_diff.compare(current, before)

        assert len(delta.resolved) == 1
        assert "Shell injection" in delta.resolved[0]

    def test_a_first_run_has_no_baseline(self):
        """
        Reporting every finding on a first analysis as "newly introduced"
        would be noise on the run where the full list is already shown.
        """
        delta = finding_diff.compare(result_with(review("Anything")), None)

        assert delta.has_baseline is False
        assert delta.introduced == []

    def test_an_unreadable_stored_result_is_treated_as_no_baseline(self):
        """A result under an older schema must not break the run."""
        delta = finding_diff.compare(result_with(review("x")), {"garbage": True})

        # It parses as a dict with no findings, so everything reads as new --
        # which is correct: we genuinely cannot see a prior finding.
        assert delta.has_baseline is True
        assert len(delta.introduced) == 1


class TestRendering:
    def test_nothing_renders_without_a_baseline(self):
        assert finding_diff.render(finding_diff.FindingDelta()) == ""

    def test_nothing_renders_when_nothing_moved(self):
        """
        A "0 resolved, 0 new" line on every push trains people to skip the
        section that matters when something does move.
        """
        delta = finding_diff.FindingDelta(has_baseline=True)
        assert finding_diff.render(delta) == ""

    def test_resolved_is_worded_as_no_longer_reported(self):
        """
        Deleting the file resolves a finding too. The tool knows what it
        stopped seeing, not what anyone did about it.
        """
        delta = finding_diff.FindingDelta(
            resolved=["api/users.py: No ownership check"], has_baseline=True
        )
        out = finding_diff.render(delta)

        assert "no longer reported" in out
        assert "fixed" not in out.lower()

    def test_persisting_findings_are_counted_not_listed(self):
        """They are rendered in full below; repeating them says nothing new."""
        delta = finding_diff.FindingDelta(
            persisting=[f"a.py: Finding {n}" for n in range(4)],
            has_baseline=True,
        )
        out = finding_diff.render(delta)

        assert "4 still open" in out
        assert "Finding 0" not in out

    def test_a_long_list_collapses_to_a_count(self):
        delta = finding_diff.FindingDelta(
            resolved=[f"a.py: Finding {n}" for n in range(9)], has_baseline=True
        )
        out = finding_diff.render(delta)

        assert "9 no longer reported" in out
        assert "and 4 more" in out


class TestInPRComment:
    def test_the_delta_leads_the_comment(self):
        """
        On a re-review this is the only part someone needs. Burying it under
        context they read on round one is what makes a long comment go unread.
        """
        result = result_with(review("Still broken"))
        result.delta = schemas.FindingDeltaSummary(
            resolved=["api/users.py: No ownership check"],
            persisting=["api/users.py: Still broken"],
        )
        out = render_pr_comment(result)

        assert "Since the last run" in out
        assert out.index("Since the last run") < out.index("Code review")

    def test_a_run_with_no_delta_renders_no_section(self):
        out = render_pr_comment(result_with(review("Anything")))
        assert "Since the last run" not in out
