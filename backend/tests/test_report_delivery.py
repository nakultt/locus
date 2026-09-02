"""
The written report reaches the people asked to act on it.

A Google Doc that gets written and then linked nowhere is work nobody reads.
The brief in each notification is short by design -- "what to test" is three
lines -- and the analysis behind it is where the findings, the requirement
context and the reviewed discussion live. Without the link that detail exists
but is unreachable from the message doing the asking.

Where it is *not* added matters too. An approval or a changes-requested
verdict reports a decision someone has already made; linking the analysis they
just finished reading is noise, and noise in a review channel is how a team
learns to skim it.
"""

from app import models, schemas
from app.services.pipeline.merge_actions import _qa_email_text
from app.services.pipeline.review_flow import format_review_notification


def _result(doc_url: str | None = None) -> schemas.PRAnalysisResult:
    return schemas.PRAnalysisResult(
        context=schemas.PRContext(
            repo="acme/api",
            pr_number=42,
            title="Retry the merge gate",
            author="junior-dev",
            url="https://github.com/acme/api/pull/42",
            additions=30,
            deletions=4,
            files_changed=3,
        ),
        doc_url=doc_url,
    )


def _review(**kwargs) -> models.PRReview:
    defaults = {
        "repo": "acme/api",
        "pr_number": 42,
        "pr_url": "https://github.com/acme/api/pull/42",
        "pr_title": "Retry the merge gate",
        "author": "junior-dev",
        "state": schemas.ReviewState.awaiting_review.value,
        "round_number": 1,
        "owner_id": 1,
    }
    return models.PRReview(**{**defaults, **kwargs})


class TestQANotifications:
    def test_email_carries_the_report_link(self):
        body = _qa_email_text(_result("https://docs.google.com/d/abc"), "Check retries")

        assert "https://docs.google.com/d/abc" in body
        assert "Check retries" in body

    def test_email_omits_the_line_entirely_without_a_report(self):
        """Docs export is off by default; an empty label would be clutter."""
        body = _qa_email_text(_result(), "Check retries")

        assert "Full analysis" not in body
        assert "None" not in body

    def test_slack_post_carries_the_report_link(self):
        import asyncio

        from app.services.pipeline.merge_actions import post_qa_thread

        # No bot token, so it returns without posting -- the text is still
        # built and returned, which is the part under test.
        _, _, text = asyncio.run(
            post_qa_thread({}, "#qa", _result("https://docs.google.com/d/xyz"), "Check")
        )

        assert "https://docs.google.com/d/xyz" in text

    def test_slack_post_omits_the_link_without_a_report(self):
        import asyncio

        from app.services.pipeline.merge_actions import post_qa_thread

        _, _, text = asyncio.run(post_qa_thread({}, "#qa", _result(), "Check"))

        assert "Full analysis" not in text


class TestReviewNotifications:
    def test_review_request_carries_the_report_link(self):
        """The reviewer is being asked to read the change; this is the point."""
        text = format_review_notification(
            _review(),
            schemas.ReviewOutcome.review_requested,
            None,
            [],
            ["senior-dev"],
            doc_url="https://docs.google.com/d/abc",
        )

        assert "https://docs.google.com/d/abc" in text
        assert "@senior-dev" in text

    def test_resubmission_carries_the_report_link(self):
        text = format_review_notification(
            _review(round_number=2),
            schemas.ReviewOutcome.resubmitted,
            "senior-dev",
            ["Add a test"],
            ["senior-dev"],
            doc_url="https://docs.google.com/d/abc",
        )

        assert "https://docs.google.com/d/abc" in text
        assert "Add a test" in text

    def test_a_verdict_does_not_carry_it(self):
        """
        Approval and changes-requested report a decision already reached.
        Linking the analysis the reviewer just read is noise.
        """
        for outcome in (
            schemas.ReviewOutcome.approved,
            schemas.ReviewOutcome.changes_requested,
        ):
            text = format_review_notification(
                _review(),
                outcome,
                "senior-dev",
                [],
                ["senior-dev"],
                doc_url="https://docs.google.com/d/abc",
            )
            assert "docs.google.com" not in text, outcome

    def test_omits_the_link_when_no_report_was_written(self):
        text = format_review_notification(
            _review(),
            schemas.ReviewOutcome.review_requested,
            None,
            [],
            ["senior-dev"],
        )

        assert "Full analysis" not in text
