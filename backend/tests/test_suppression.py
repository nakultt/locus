"""
Dismissing a finding, and the `@locus` commands that do it.

A false positive was permanent before this: the scan re-runs on every push, the
finding returns, and the only way to silence it is to stop reading the comment
-- which silences the true positives with it.

Two things carry the safety of the feature:

**The command text is untrusted.** Anyone who can comment on a pull request
writes it, which on a public repo is anyone. Parsing is a regex over a fixed
vocabulary, no model is involved, and the widest reachable effect is hiding a
finding on the pull request the comment was posted on.

**Locus must not obey its own comment.** The comment it posts ends with the
`@locus ignore` hint, so a handler that read its own output would instruct
itself -- the confused-deputy shape the untrusted-text rules exist to stop.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models, schemas
from app.core.database import Base
from app.services.pipeline import suppression

OWNER = 1
REPO = "acme/api"


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    session.add(models.User(
        id=OWNER, email="d@a.com", hashed_password="x", timezone="UTC"))
    session.commit()
    try:
        yield session
    finally:
        session.close()


def result_with(*findings) -> schemas.PRAnalysisResult:
    return schemas.PRAnalysisResult(
        context=schemas.PRContext(
            repo=REPO, pr_number=892, title="t", author="a", url="u",
            branch="b", files_changed=1, additions=1, deletions=0,
        ),
        review_findings=list(findings),
    )


def review(title: str, path: str = "api/users.py"):
    return schemas.ReviewFinding(
        priority=schemas.ReviewPriority.p2, category="quality",
        title=title, file_path=path, line=42, description="d",
    )


class TestCommandParsing:
    def test_an_ordinary_comment_carries_no_command(self):
        assert suppression.parse_commands("Looks good to me, shipping.") == []

    def test_ignore_is_parsed(self):
        commands = suppression.parse_commands("@locus ignore Unused import")

        assert len(commands) == 1
        assert commands[0].verb == "ignore"
        assert commands[0].target == "Unused import"
        assert commands[0].suppresses

    def test_dismiss_is_a_synonym(self):
        assert suppression.parse_commands("@locus dismiss X")[0].suppresses

    def test_explain_is_recognised_but_does_not_suppress(self):
        """
        Accepted so the vocabulary is stable and the user is not told a
        reasonable command is invalid.
        """
        commands = suppression.parse_commands("@locus explain Race on cache")

        assert commands[0].verb == "explain"
        assert not commands[0].suppresses

    def test_a_reason_is_captured_separately(self):
        commands = suppression.parse_commands(
            "@locus ignore Unused import -- it is re-exported on purpose"
        )

        assert commands[0].target == "Unused import"
        assert "re-exported" in commands[0].reason

    def test_because_also_introduces_a_reason(self):
        commands = suppression.parse_commands(
            "@locus ignore Shell call because the input is a literal"
        )

        assert commands[0].target == "Shell call"
        assert "literal" in commands[0].reason

    def test_quotes_and_backticks_are_stripped(self):
        commands = suppression.parse_commands('@locus ignore "Unused import"')
        assert commands[0].target == "Unused import"

    def test_a_command_must_start_its_line(self):
        """
        Otherwise quoting someone else's comment fires the command again.
        """
        assert suppression.parse_commands(
            "I think we should tell it: @locus ignore X"
        ) == []

    def test_a_bare_mention_is_not_a_command(self):
        """
        People talk about the bot. Replying "unknown command" to every
        mention would be its own kind of noise.
        """
        assert suppression.parse_commands("@locus is being noisy today") == []

    def test_several_commands_in_one_comment(self):
        commands = suppression.parse_commands(
            "@locus ignore First finding\n@locus ignore Second finding"
        )
        assert [c.target for c in commands] == ["First finding", "Second finding"]


class TestMatching:
    def test_an_exact_title_matches(self):
        result = result_with(review("Unused import"))
        assert suppression.match_finding(result, "Unused import") is not None

    def test_a_partial_title_matches(self):
        """People do not retype a title exactly."""
        result = result_with(review("Unused import in the header block"))
        assert suppression.match_finding(result, "unused import") is not None

    def test_an_ambiguous_target_matches_nothing(self):
        """
        Silencing the wrong finding is invisible. Better to do nothing and
        let the author be more specific.
        """
        result = result_with(
            review("Unused import", path="a.py"),
            review("Unused import", path="b.py"),
        )
        assert suppression.match_finding(result, "Unused import") is None

    def test_an_unknown_target_matches_nothing(self):
        result = result_with(review("Unused import"))
        assert suppression.match_finding(result, "something else") is None


class TestSuppressing:
    def test_a_suppressed_finding_is_withheld(self, db):
        suppression.suppress(
            db, owner_id=OWNER, repo=REPO, pr_number=892,
            file_path="api/users.py", title="Unused import",
        )
        active = suppression.active_for(
            db, owner_id=OWNER, repo=REPO, pr_number=892)

        result = result_with(review("Unused import"), review("Real problem"))
        withheld = suppression.apply(result, active)

        assert withheld == 1
        assert [f.title for f in result.review_findings] == ["Real problem"]

    def test_a_finding_that_moved_is_still_suppressed(self, db):
        """
        Keyed by file and title, not line -- a line-keyed suppression would
        lapse silently the next time anyone edited above it.
        """
        suppression.suppress(
            db, owner_id=OWNER, repo=REPO, pr_number=892,
            file_path="api/users.py", title="Unused import",
        )
        active = suppression.active_for(
            db, owner_id=OWNER, repo=REPO, pr_number=892)

        moved = review("Unused import")
        moved.line = 907
        result = result_with(moved)

        assert suppression.apply(result, active) == 1

    def test_suppression_does_not_leak_to_another_pull_request(self, db):
        """A finding dismissed on one PR says nothing about another."""
        suppression.suppress(
            db, owner_id=OWNER, repo=REPO, pr_number=892,
            file_path="api/users.py", title="Unused import",
        )
        active = suppression.active_for(
            db, owner_id=OWNER, repo=REPO, pr_number=999)

        assert suppression.apply(result_with(review("Unused import")), active) == 0

    def test_a_repo_wide_suppression_applies_everywhere(self, db):
        suppression.suppress(
            db, owner_id=OWNER, repo=REPO, pr_number=None, scope="repo",
            file_path="api/users.py", title="Unused import",
        )
        active = suppression.active_for(
            db, owner_id=OWNER, repo=REPO, pr_number=999)

        assert suppression.apply(result_with(review("Unused import")), active) == 1

    def test_suppression_does_not_leak_across_users(self, db):
        suppression.suppress(
            db, owner_id=OWNER, repo=REPO, pr_number=892,
            file_path="api/users.py", title="Unused import",
        )
        active = suppression.active_for(
            db, owner_id=2, repo=REPO, pr_number=892)

        assert active == set()

    def test_dismissing_twice_does_not_duplicate(self, db):
        for _ in range(2):
            suppression.suppress(
                db, owner_id=OWNER, repo=REPO, pr_number=892,
                file_path="api/users.py", title="Unused import",
                suppressed_by="nakultt",
            )

        assert db.query(models.SuppressedFinding).count() == 1

    def test_the_title_is_matched_exactly_not_fuzzily(self, db):
        """
        A fuzzy match would let one dismissal silence findings nobody looked
        at, which is worse than having no suppression.
        """
        suppression.suppress(
            db, owner_id=OWNER, repo=REPO, pr_number=892,
            file_path="api/users.py", title="Unused import",
        )
        active = suppression.active_for(
            db, owner_id=OWNER, repo=REPO, pr_number=892)

        result = result_with(review("Unused import in the header block"))

        assert suppression.apply(result, active) == 0

    def test_who_dismissed_it_and_why_are_recorded(self, db):
        """A suppression with no author is indistinguishable from a bug."""
        suppression.suppress(
            db, owner_id=OWNER, repo=REPO, pr_number=892,
            file_path="api/users.py", title="Unused import",
            suppressed_by="nakultt", reason="re-exported on purpose",
        )
        row = db.query(models.SuppressedFinding).one()

        assert row.suppressed_by == "nakultt"
        assert row.reason == "re-exported on purpose"


class TestDisclosure:
    def test_the_comment_says_findings_were_hidden(self):
        """
        A scanner that quietly stops mentioning things is worse than one that
        never mentioned them: the silence reads as a clean run.
        """
        from app.services.pipeline.pr_agent import render_pr_comment

        result = result_with(review("Real problem"))
        result.suppressed_count = 2

        out = render_pr_comment(result)

        assert "2 finding(s) hidden" in out

    def test_a_run_with_nothing_hidden_says_nothing(self):
        from app.services.pipeline.pr_agent import render_pr_comment

        out = render_pr_comment(result_with(review("Real problem")))

        assert "hidden" not in out
