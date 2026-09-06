"""
Nothing reads across accounts.

`Cross-user access returns 404, not 403` is an invariant this codebase already
holds on its HTTP surface. These are the two places it stopped holding
*underneath* that surface, where an endpoint scoped correctly and then called a
service that fell back past the owner.

Both fallbacks came from the same cause: a board running as one account while
the pipeline state -- registrations, reviews, reports -- had been written by
another. The links and settings appeared to be missing, and an owner-less retry
made them appear again. The real fix was to put the data on one account; the
workarounds are cross-account reads and are worse than the symptom.
"""

import pathlib
import re

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.services.pipeline import report_sync


@pytest.fixture
def db(tmp_path):
    from app.core.database import Base

    engine = create_engine(
        f"sqlite:///{tmp_path}/x.db", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


MINE, THEIRS = 1, 2
REPO = "acme/api"


class TestReportsAreNotSharedBetweenAccounts:
    """
    A report row carries a Google Doc id. Returning another account's row
    renders their document as this account's report link -- and a refresh
    writes this work item's history into their document.
    """

    def test_a_ticket_keyed_report_is_not_borrowed(self, db):
        db.add(models.PRReport(
            repo=REPO, pr_number=7, ticket_key="LOC-1",
            document_id="doc-theirs", owner_id=THEIRS,
        ))
        db.commit()

        assert report_sync.find_report(
            db, owner_id=MINE, repo=REPO, pr_number=7, ticket_key="LOC-1"
        ) is None

    def test_a_pr_keyed_report_is_not_borrowed(self, db):
        """
        The second fallback, for rows written before documents belonged to
        work items. Same leak by a different key.
        """
        db.add(models.PRReport(
            repo=REPO, pr_number=7, document_id="doc-theirs", owner_id=THEIRS,
        ))
        db.commit()

        assert report_sync.find_report(
            db, owner_id=MINE, repo=REPO, pr_number=7
        ) is None

    def test_the_url_helper_leaks_nothing_either(self, db):
        """
        `document_url` delegates, so it inherited the leak and is what the UI
        actually calls.
        """
        db.add(models.PRReport(
            repo=REPO, pr_number=7, ticket_key="LOC-1",
            document_id="doc-theirs", owner_id=THEIRS,
        ))
        db.commit()

        assert report_sync.document_url(
            db, owner_id=MINE, repo=REPO, pr_number=7, ticket_key="LOC-1"
        ) is None

    def test_my_own_report_is_still_found_by_either_key(self, db):
        """
        The fix must not become "reports are never found". Both lookups still
        work for the account that owns the row.
        """
        db.add(models.PRReport(
            repo=REPO, pr_number=7, ticket_key="LOC-1",
            document_id="doc-mine", owner_id=MINE,
        ))
        db.add(models.PRReport(
            repo=REPO, pr_number=9, document_id="doc-mine-pr", owner_id=MINE,
        ))
        db.commit()

        by_ticket = report_sync.find_report(
            db, owner_id=MINE, repo=REPO, pr_number=7, ticket_key="LOC-1"
        )
        by_pr = report_sync.find_report(db, owner_id=MINE, repo=REPO, pr_number=9)

        assert by_ticket is not None and by_ticket.document_id == "doc-mine"
        assert by_pr is not None and by_pr.document_id == "doc-mine-pr"

    def test_mine_wins_when_both_accounts_have_one(self, db):
        """
        The ordering that made the leak hard to see: with a row of my own the
        lookup was correct, and only an account that had none saw someone
        else's.
        """
        db.add(models.PRReport(
            repo=REPO, pr_number=7, ticket_key="LOC-1",
            document_id="doc-theirs", owner_id=THEIRS,
        ))
        db.add(models.PRReport(
            repo=REPO, pr_number=7, ticket_key="LOC-1",
            document_id="doc-mine", owner_id=MINE,
        ))
        db.commit()

        found = report_sync.find_report(
            db, owner_id=MINE, repo=REPO, pr_number=7, ticket_key="LOC-1"
        )
        assert found is not None and found.document_id == "doc-mine"


class TestRepoRegistrationsAreNotBorrowed:
    """
    Worse than a read. `resolve_settings` turns a registration into
    `source_path`, `prepare_command` and `test_command` -- a path on this
    server and two shell commands run inside the agent's workspace -- so
    borrowing another account's row runs their commands against their source
    tree on a click from someone who never saw either.
    """

    def test_no_router_falls_back_past_the_owner(self):
        """
        A source check. The failing case needs two accounts, a registered repo
        and a board card, and the symptom of a regression is not an error but
        a run that quietly uses the wrong settings.
        """
        import pathlib
        import re

        root = pathlib.Path(__file__).resolve().parent.parent / "app"
        for path in sorted(root.rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            for match in re.finditer(
                r"query\(models\.RepoWebhook\)\s*\.?filter\((.*?)\)\s*\.first\(\)",
                source,
                re.S,
            ):
                clause = match.group(1)
                if "owner_id" in clause:
                    continue
                # The one exemption, and it is the opposite of a cross-user
                # read: the GitHub webhook receiver's entry lookup. An inbound
                # webhook carries no user, so this row is how the owner is
                # *established* -- and the HMAC is then verified against its
                # own secret, so an attacker cannot pick which row answers.
                # Recognised by `enabled`, which no owner-scoped lookup uses.
                if "enabled" in clause and path.name == "webhooks.py":
                    continue
                raise AssertionError(
                    f"{path.name} looks up a RepoWebhook without an owner "
                    "filter; that row carries a source path and two shell "
                    "commands."
                )

    def test_resolve_settings_falls_back_to_my_defaults_not_their_repo(self, db):
        """
        What should happen for an unregistered repo: the account's own
        defaults, which is exactly the case `PRAgentDefaults` exists for.
        """
        from app.services.pipeline.agent_settings import resolve_settings

        db.add(models.RepoWebhook(
            repo=REPO, encrypted_secret="x", enabled=1, owner_id=THEIRS,
            authoring_mode="autonomous", test_command="rm -rf /",
        ))
        db.add(models.PRAgentDefaults(owner_id=MINE, authoring_mode="assisted"))
        db.commit()

        registration = db.query(models.RepoWebhook).filter(
            models.RepoWebhook.repo == REPO,
            models.RepoWebhook.owner_id == MINE,
        ).first()
        assert registration is None

        resolved = resolve_settings(db, MINE, registration)
        assert resolved.authoring_mode == "assisted"
        assert resolved.test_command is None


class TestTheFallbackPatternIsGoneEverywhere:
    """
    Nine of these were found, across seven modules, all the same shape: a query
    correctly scoped to the owner, then a re-query without them when it
    returned nothing.

    Individually each looked like a small robustness measure. Together they
    meant an account with no data of its own silently read another's --
    registrations carrying a source path and two shell commands, report rows
    carrying a Google Doc id, review rows that were then *written to*, and the
    QA transcript that becomes the authoring prompt's primary goal.

    A source check, because that is the only kind that catches the tenth. The
    symptom of a regression is not an error: it is an account seeing data, and
    the feature appearing to work.
    """

    OWNED = (
        "PRReport", "PRReview", "PRReviewRound", "QAThread", "AuthoringAttempt",
        "CommunicationEvent", "RepoWebhook", "PRJob", "PRAgentDefaults",
        "WorkItemSettings", "LLMSetting", "IntegrationHealth", "InterruptionEvent",
    )

    # An `if not x:` / `if x is None:` block, captured with its whole body.
    BLOCK = re.compile(
        r"^(?P<i>[ ]+)if (?:not \w+|\w+ is None):\n"
        r"(?P<body>(?:(?P=i)[ ]{4}.*\n|\n)+?)"
        r"(?=(?P=i)(?:[^ \n]|\Z))",
        re.M,
    )

    def test_no_owner_scoped_query_retries_without_the_owner(self):
        root = pathlib.Path(__file__).resolve().parent.parent / "app"
        offenders = []

        for path in sorted(root.rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            for match in self.BLOCK.finditer(source):
                body = match.group("body")
                if "db.query(" not in body or "owner_id" in body:
                    continue
                if not any(f"models.{name}" in body for name in self.OWNED):
                    continue
                line = source[: match.start()].count("\n") + 1
                offenders.append(f"{path.name}:{line}")

        assert offenders == [], (
            "An owner-scoped lookup falls back to an owner-less one in: "
            + ", ".join(offenders)
        )


SAMPLE_OFFENDER = '''def f(db, owner_id, repo):
    row = db.query(models.PRReport).filter(
        models.PRReport.owner_id == owner_id,
    ).first()
    if row is None:
        row = db.query(models.PRReport).filter(
            models.PRReport.repo == repo,
        ).first()
    return row
'''

SAMPLE_CLEAN = '''def f(db, owner_id, repo):
    row = db.query(models.PRReport).filter(
        models.PRReport.owner_id == owner_id,
    ).first()
    if row is None:
        return None
    return row
'''


def _offences(source: str) -> list:
    guard = TestTheFallbackPatternIsGoneEverywhere
    return [
        match
        for match in guard.BLOCK.finditer(source)
        if "db.query(" in match.group("body")
        and "owner_id" not in match.group("body")
        and any(f"models.{n}" in match.group("body") for n in guard.OWNED)
    ]


def test_the_guard_detects_the_shape_that_was_removed():
    """
    A source check that never fails is indistinguishable from one that cannot
    fail. This feeds it the exact shape found nine times.
    """
    assert len(_offences(SAMPLE_OFFENDER)) == 1


def test_the_guard_does_not_flag_an_honest_early_return():
    """And the negative case, or the guard is just matching `if`."""
    assert _offences(SAMPLE_CLEAN) == []
