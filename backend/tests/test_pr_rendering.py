"""
PR comment rendering.

The load-bearing guarantee here is that scanner-confirmed findings and
model-generated ones never appear as the same kind of claim. One hallucinated
"confirmed vulnerability" on a colleague's PR is enough for a team to stop
trusting the bot permanently.
"""

from app.schemas import (
    FindingSource,
    PRAnalysisResult,
    PRContext,
    RelatedSlackThread,
    RelatedTicket,
    SecurityFinding,
    SecuritySeverity,
)
from app.services.pr_agent import render_pr_comment, render_slack_summary


def make_context(**overrides) -> PRContext:
    defaults = dict(
        repo="acme/api",
        pr_number=892,
        title="Fix payment webhook timeouts",
        author="nakultt",
        url="https://github.com/acme/api/pull/892",
        branch="fix/LOC-431",
        files_changed=4,
        additions=87,
        deletions=23,
    )
    return PRContext(**{**defaults, **overrides})


CONFIRMED = SecurityFinding(
    source=FindingSource.semgrep,
    severity=SecuritySeverity.high,
    title="Subprocess shell true",
    file_path="api/users.py",
    line=5,
    description="Shell injection risk.",
)

UNVERIFIED = SecurityFinding(
    source=FindingSource.llm,
    severity=SecuritySeverity.medium,
    title="Missing authorization check",
    file_path="api/webhook.py",
    line=45,
    description="Endpoint does not verify caller identity.",
)


class TestFindingSeparation:
    def test_confirmed_and_unverified_render_in_distinct_sections(self):
        out = render_pr_comment(PRAnalysisResult(
            context=make_context(),
            confirmed_findings=[CONFIRMED],
            unverified_findings=[UNVERIFIED],
        ))
        assert "confirmed" in out.lower()
        assert "unverified" in out.lower()
        # The unverified section must carry an explicit caveat.
        assert "not** confirmed" in out or "not confirmed" in out.lower()

    def test_unverified_only_never_claims_confirmation(self):
        out = render_pr_comment(PRAnalysisResult(
            context=make_context(),
            unverified_findings=[UNVERIFIED],
        ))
        assert "Security findings (confirmed)" not in out
        assert "unverified" in out.lower()

    def test_clean_pr_says_nothing_detected(self):
        out = render_pr_comment(PRAnalysisResult(context=make_context()))
        assert "No issues detected" in out


class TestSecretHandling:
    def test_secret_value_is_never_rendered(self):
        """
        Gitleaks findings report location only. Echoing the credential into a
        PR comment would widen the exposure being reported.
        """
        leak = SecurityFinding(
            source=FindingSource.gitleaks,
            severity=SecuritySeverity.critical,
            title="Possible aws-access-key committed",
            file_path="config/settings.py",
            line=12,
            description="A value matching a credential pattern was detected.",
        )
        out = render_pr_comment(PRAnalysisResult(
            context=make_context(), confirmed_findings=[leak]
        ))
        assert "config/settings.py:12" in out
        # The schema has no field capable of carrying the secret.
        assert not hasattr(leak, "secret_value")


class TestSeverityOrdering:
    def test_critical_renders_before_low(self):
        low = SecurityFinding(
            source=FindingSource.semgrep, severity=SecuritySeverity.low,
            title="Low issue", file_path="a.py", line=1, description="",
        )
        critical = SecurityFinding(
            source=FindingSource.semgrep, severity=SecuritySeverity.critical,
            title="Critical issue", file_path="b.py", line=2, description="",
        )
        out = render_pr_comment(PRAnalysisResult(
            context=make_context(), confirmed_findings=[low, critical]
        ))
        assert out.index("Critical issue") < out.index("Low issue")


class TestContextRendering:
    def test_includes_tickets_and_threads(self):
        out = render_pr_comment(PRAnalysisResult(context=make_context(
            ticket_keys=["LOC-431"],
            tickets=[RelatedTicket(
                key="LOC-431", summary="Payment webhook timeouts",
                status="In Progress", assignee="Nakul",
                url="https://x.atlassian.net/browse/LOC-431",
            )],
            slack_threads=[RelatedSlackThread(
                channel="payments", permalink="https://s.slack.com/p/1",
                message_count=14, summary="Retry count should be 3",
            )],
        )))
        assert "LOC-431" in out
        assert "#payments" in out

    def test_reports_referenced_but_missing_tickets(self):
        out = render_pr_comment(PRAnalysisResult(
            context=make_context(ticket_keys=["LOC-999"], tickets=[])
        ))
        assert "LOC-999" in out
        assert "not found" in out


class TestSlackSummary:
    def test_flags_confirmed_findings(self):
        r = PRAnalysisResult(context=make_context(), confirmed_findings=[CONFIRMED])
        assert "confirmed" in render_slack_summary(r).lower()

    def test_clean_pr_shows_no_findings(self):
        assert "No security findings" in render_slack_summary(
            PRAnalysisResult(context=make_context())
        )
