"""
A reopened ticket whose fix lands on a different branch.

The shape: a change merges, QA rejects it, the ticket goes back to In
Progress, and the fix arrives as a *new* pull request on a *new* branch. To
the review loop that pull request looks entirely new -- different number, no
review row, no recorded work item -- so it started cold. None of the Slack
discussion, none of the earlier review asks, and no knowledge of why QA
rejected the last attempt: the one piece of context that says what to get
right this time was the piece it could not see.

The key is recoverable from the branch and title, which is where
`linking.extract_ticket_keys` already looks. Once it is known, the sibling
pull requests are a lookup.

**A work item is never guessed.** If the branch and title name no ticket, the
run proceeds as genuinely new work rather than attaching one team's rejection
history to another team's pull request.
"""

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models, schemas
from app.database import Base
from app.services import review_flow, work_item

OWNER = 1
REPO = "acme/api"


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    session.add(models.User(
        id=OWNER, email="d@a.com", hashed_password="x", timezone="Asia/Kolkata"))
    session.commit()
    try:
        yield session
    finally:
        session.close()


def add_review(db, pr_number, state, ticket="LOC-431", repo=REPO):
    row = models.PRReview(
        repo=repo, pr_number=pr_number, pr_url=f"https://x/pull/{pr_number}",
        pr_title="Fix timeouts", state=state, round_number=1,
        ticket_keys=ticket, owner_id=OWNER,
    )
    db.add(row)
    db.commit()
    return row


class TestResolvingTheWorkItem:
    def test_a_recorded_key_wins(self, db):
        """A completed analysis knows more than a branch name does."""
        add_review(db, 7, schemas.ReviewState.merged.value, ticket="LOC-431")

        assert work_item.resolve_key(
            db, owner_id=OWNER, repo=REPO, pr_number=7, branch="feature/OTHER-1"
        ) == "LOC-431"

    def test_a_new_pull_request_reads_its_branch(self, db):
        """
        The reopened-ticket case: no review row exists yet, and without this
        the pull request inherits nothing.
        """
        assert work_item.resolve_key(
            db, owner_id=OWNER, repo=REPO, pr_number=9,
            branch="fix/LOC-431-retry-again",
        ) == "LOC-431"

    def test_the_title_and_body_are_read_too(self, db):
        assert work_item.resolve_key(
            db, owner_id=OWNER, repo=REPO, pr_number=9,
            title="LOC-431: second attempt",
        ) == "LOC-431"
        assert work_item.resolve_key(
            db, owner_id=OWNER, repo=REPO, pr_number=9,
            body="Closes LOC-431",
        ) == "LOC-431"

    def test_nothing_is_invented(self, db):
        """
        Attaching a guessed work item would put one team's rejection history
        in front of another team's pull request.
        """
        assert work_item.resolve_key(
            db, owner_id=OWNER, repo=REPO, pr_number=9,
            title="Tidy up the logger", branch="chore/logging",
        ) is None


class TestSiblings:
    def test_pull_requests_on_one_work_item_are_found(self, db):
        add_review(db, 7, schemas.ReviewState.merged.value)
        add_review(db, 9, schemas.ReviewState.awaiting_review.value)

        siblings = work_item.sibling_reviews(
            db, owner_id=OWNER, ticket_key="LOC-431", exclude_pr=9
        )

        assert [s.pr_number for s in siblings] == [7]

    def test_a_pr_carrying_several_keys_matches_any_of_them(self, db):
        add_review(db, 7, schemas.ReviewState.merged.value,
                   ticket="LOC-431\nOPS-12")

        assert work_item.sibling_reviews(
            db, owner_id=OWNER, ticket_key="OPS-12", exclude_pr=9
        )

    def test_another_users_pull_requests_are_not_siblings(self, db):
        row = add_review(db, 7, schemas.ReviewState.merged.value)
        row.owner_id = 2
        db.commit()

        assert work_item.sibling_reviews(
            db, owner_id=OWNER, ticket_key="LOC-431", exclude_pr=9
        ) == []

    def test_a_fix_in_another_repo_is_still_a_sibling(self, db):
        """A fix can land in a different repo from the change that broke it."""
        add_review(db, 3, schemas.ReviewState.merged.value, repo="acme/worker")

        assert work_item.sibling_reviews(
            db, owner_id=OWNER, ticket_key="LOC-431", exclude_pr=9
        )

    def test_the_previous_attempt_is_the_last_one(self, db):
        add_review(db, 3, schemas.ReviewState.merged.value)
        add_review(db, 7, schemas.ReviewState.merged.value)

        previous = work_item.previous_attempt(
            db, owner_id=OWNER, ticket_key="LOC-431", exclude_pr=9
        )

        assert previous.pr_number == 7


class TestRetryDetection:
    def test_a_new_pr_after_a_merge_is_a_retry(self, db):
        add_review(db, 7, schemas.ReviewState.merged.value)

        retry, previous = work_item.is_retry(
            db, owner_id=OWNER, repo=REPO, pr_number=9, ticket_key="LOC-431"
        )

        assert retry is True
        assert previous.pr_number == 7

    def test_an_open_sibling_is_not_a_retry(self, db):
        """
        Two pull requests in flight on one ticket is ordinary. Calling the
        second a retry would put a misleading history in front of the reviewer.
        """
        add_review(db, 7, schemas.ReviewState.awaiting_review.value)

        retry, _ = work_item.is_retry(
            db, owner_id=OWNER, repo=REPO, pr_number=9, ticket_key="LOC-431"
        )

        assert retry is False

    def test_the_first_pull_request_on_a_ticket_is_not_a_retry(self, db):
        retry, previous = work_item.is_retry(
            db, owner_id=OWNER, repo=REPO, pr_number=7, ticket_key="LOC-431"
        )

        assert (retry, previous) == (False, None)

    def test_no_work_item_means_no_retry(self, db):
        add_review(db, 7, schemas.ReviewState.merged.value)

        retry, _ = work_item.is_retry(
            db, owner_id=OWNER, repo=REPO, pr_number=9, ticket_key=None
        )

        assert retry is False


class TestQARejectionLookup:
    def add_thread(self, db, keys, resolved=0, pr_number=7):
        db.add(models.QAThread(
            repo=REPO, pr_number=pr_number, pr_url="u",
            slack_channel="#qa", slack_thread_ts="1",
            ticket_keys_json=json.dumps(keys), resolved=resolved,
            owner_id=OWNER,
        ))
        db.commit()

    def test_an_unresolved_thread_is_found(self, db):
        """An unresolved QA thread is why the ticket came back."""
        self.add_thread(db, ["LOC-431"])

        assert work_item.qa_rejection(
            db, owner_id=OWNER, ticket_key="LOC-431"
        ) is not None

    def test_a_resolved_thread_is_not_a_rejection(self, db):
        self.add_thread(db, ["LOC-431"], resolved=1)

        assert work_item.qa_rejection(
            db, owner_id=OWNER, ticket_key="LOC-431"
        ) is None

    def test_another_work_items_rejection_is_not_matched(self, db):
        self.add_thread(db, ["OPS-99"])

        assert work_item.qa_rejection(
            db, owner_id=OWNER, ticket_key="LOC-431"
        ) is None

    def test_unreadable_stored_keys_do_not_raise(self, db):
        db.add(models.QAThread(
            repo=REPO, pr_number=7, pr_url="u", slack_channel="#qa",
            slack_thread_ts="1", ticket_keys_json="not json",
            resolved=0, owner_id=OWNER,
        ))
        db.commit()

        assert work_item.qa_rejection(
            db, owner_id=OWNER, ticket_key="LOC-431"
        ) is None


class TestRetryNotice:
    def test_it_names_the_earlier_pull_request(self, db):
        """
        Telling a reviewer there is history without saying where it is leaves
        them to find it.
        """
        previous = add_review(db, 7, schemas.ReviewState.merged.value)

        text = review_flow.format_retry_notice(
            repo=REPO, pr_number=9, pr_url="https://x/pull/9",
            pr_title="Second attempt", ticket_key="LOC-431",
            previous=previous, qa_rejected=True, reviewers=["senior-dev"],
        )

        assert "LOC-431" in text
        assert f"{REPO}#7" in text
        assert "QA rejected" in text
        assert "@senior-dev" in text

    def test_a_merge_without_a_qa_rejection_is_worded_differently(self, db):
        previous = add_review(db, 7, schemas.ReviewState.merged.value)

        text = review_flow.format_retry_notice(
            repo=REPO, pr_number=9, pr_url="u", pr_title="t",
            ticket_key="LOC-431", previous=previous, qa_rejected=False,
            reviewers=["senior-dev"],
        )

        assert "QA rejected" not in text
        assert "merged earlier" in text
