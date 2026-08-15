"""
The written record that goes to the senior dev and the testing team.

The PR comment is a summary read next to the code. This is the opposite
document: the people asked to trust the pipeline's verdict did not watch it
run, and trusting it is only reasonable if they can read what it actually did.

The tests that matter are the ones about what must not be quietly omitted --
a search that matched nothing, a message that failed to send, a step that was
skipped. Each of those is invisible everywhere else in the system, and a report
that drops them reads as a clean run.
"""

from datetime import UTC, datetime, timedelta

from app import models, schemas
from app.services import full_report


def _result(**kw):
    ctx = schemas.PRContext(
        repo="acme/widget", pr_number=7, title="Restructure the page",
        author="dev", url="https://github.com/acme/widget/pull/7",
        files_changed=1, additions=7, deletions=8,
        **kw.pop("context", {}),
    )
    return schemas.PRAnalysisResult(context=ctx, **kw)


def _event(**kw):
    defaults = {
        "repo": "acme/widget", "pr_number": 7, "loop": "context",
        "direction": "searched", "channel": "slack", "succeeded": 1,
        "created_at": datetime.now(UTC), "owner_id": 1,
    }
    defaults.update(kw)
    return models.CommunicationEvent(**defaults)


class TestTheRecordIsComplete:
    def test_a_search_that_matched_nothing_still_appears(self):
        """
        The whole reason the query is stored. A search that found nothing and
        a search that never ran produce identical silence everywhere else, and
        only one of them means the requirement context is missing.
        """
        text = full_report.render(
            _result(),
            events=[_event(query="joyyy#7", outcome="no matches")],
        )

        assert "joyyy#7" in text
        assert "no matches" in text

    def test_a_failed_send_is_called_out(self):
        """
        A message nobody received looks exactly like one nobody replied to.
        """
        text = full_report.render(
            _result(),
            events=[_event(
                loop="qa", direction="sent", channel="email",
                target="qa@acme.com", body="Ready to test", succeeded=0,
            )],
        )

        assert "DELIVERY FAILED" in text

    def test_every_review_round_is_recorded_with_its_words(self):
        """
        GitHub reports each review as an isolated event. The round history is
        the thing only Locus has, so the report is where it has to appear.
        """
        review = models.PRReview(
            repo="acme/widget", pr_number=7, state="merged", round_number=2,
            last_reviewer="senior-dev", owner_id=1,
        )
        review.rounds = [
            models.PRReviewRound(
                id=1, round_number=1, outcome="changes_requested",
                reviewer="senior-dev", body='add word "orange" too',
                created_at=datetime.now(UTC),
            ),
            models.PRReviewRound(
                id=2, round_number=2, outcome="approved",
                reviewer="senior-dev", created_at=datetime.now(UTC),
            ),
        ]

        text = full_report.render(_result(), review=review)

        assert 'add word "orange" too' in text
        assert "Round 1" in text and "Round 2" in text

    def test_skipped_and_failed_steps_are_shown(self):
        """
        A step that did not run is the usual reason the report is missing
        something, so listing only the successful ones hides the explanation.
        """
        text = full_report.render(_result(stages=[
            schemas.PipelineStage(
                key="docs", label="Write report", kind="write",
                state=schemas.StageState.failed, detail="401 from Google",
            ),
            schemas.PipelineStage(
                key="fixes", label="Write suggested fixes", kind="write",
                state=schemas.StageState.skipped, detail="no diff lines",
            ),
        ]))

        assert "401 from Google" in text
        assert "skipped" in text

    def test_errors_are_listed(self):
        text = full_report.render(_result(errors=["gitleaks failed"]))

        assert "gitleaks failed" in text


class TestFindingsAreSeparated:
    def test_confirmed_and_unverified_are_not_merged(self):
        """
        The split is the reason the scanner is trusted. Collapsing it in the
        report would hand an unverified finding the authority of a rule match.
        """
        text = full_report.render(_result(
            confirmed_findings=[schemas.SecurityFinding(
                title="Hardcoded secret", severity=schemas.SecuritySeverity.high,
                file_path="a.py", line=3, source=schemas.FindingSource.gitleaks,
                description="an API key is committed",
            )],
            unverified_findings=[schemas.SecurityFinding(
                title="Possible XSS", severity=schemas.SecuritySeverity.medium,
                file_path="b.py", line=9, source=schemas.FindingSource.llm,
                description="unescaped user input",
            )],
        ))

        confirmed_at = text.index("Hardcoded secret")
        unverified_at = text.index("Possible XSS")
        assert text.index("Unverified") > confirmed_at
        assert unverified_at > text.index("Unverified")

    def test_a_review_finding_keeps_its_priority(self):
        text = full_report.render(_result(review_findings=[
            schemas.ReviewFinding(
                title="Malformed HTML", priority=schemas.ReviewPriority.p1,
                category="correctness", file_path="t.html", line=11,
                description="closing tag is broken",
            )
        ]))

        assert "P1" in text
        assert "Malformed HTML" in text


class TestRendering:
    def test_inherited_discussion_is_marked(self):
        """
        Context the analysis was given by a sibling PR on the same ticket.
        Omitting it understates what the run used; showing it unmarked reads
        as discussion about this PR.
        """
        event = _event(direction="received", body="we agreed on orange")
        event.inherited = True

        text = full_report.render(_result(), events=[event])

        assert "inherited" in text

    def test_a_long_body_is_trimmed_and_says_so(self):
        text = full_report.render(
            _result(), events=[_event(direction="received", body="x" * 5000)]
        )

        assert "trimmed" in text

    def test_timestamps_render_in_the_team_timezone(self):
        """
        These are shared events people discuss with each other, so everyone
        has to read the same wall clock.
        """
        stamp = datetime(2026, 8, 15, 14, 15, tzinfo=UTC)
        text = full_report.render(
            _result(), events=[_event(created_at=stamp, query="q")]
        )

        # 14:15 UTC is 19:45 IST.
        assert "19:45 IST" in text

    def test_a_naive_timestamp_is_read_as_utc(self):
        """
        SQLite stores UTC without labelling it. Resolving against the server's
        zone would shift the whole document with nothing on the page to show it.
        """
        naive = datetime(2026, 8, 15, 14, 15)
        text = full_report.render(
            _result(), events=[_event(created_at=naive, query="q")]
        )

        assert "19:45 IST" in text

    def test_it_renders_with_nothing_recorded(self):
        """A first run on a PR with no history must still produce a report."""
        text = full_report.render(_result())

        assert "acme/widget#7" in text
        assert "Nothing recorded." in text

    def test_events_are_grouped_by_loop_in_order(self):
        now = datetime.now(UTC)
        text = full_report.render(_result(), events=[
            _event(loop="qa", direction="sent", body="ready to test",
                   created_at=now + timedelta(hours=2)),
            _event(loop="context", query="early search", created_at=now),
        ])

        assert text.index("Context gathering") < text.index("Testing team")
