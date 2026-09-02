"""
The bound, the handoff, and the two automatic triggers.

Nothing before this phase is dangerous; nothing before it is complete either.
Shipping the driver without the bound means the first reviewer who requests
changes twice gets an agent that reworks forever, and `PRReview.round_number` --
the signal that makes a stalled review visible -- stops meaning anything.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models, schemas
from app.services.authoring import authoring, authoring_flow
from app.services.pipeline import review_flow
from app.services.pipeline.agent_settings import resolve_settings


@pytest.fixture
def db(tmp_path):
    from app.core.database import Base

    engine = create_engine(
        f"sqlite:///{tmp_path}/d.db", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def settings_for(db, *, mode="autonomous", rounds=2, ticket_key="LOC-42"):
    db.query(models.WorkItemSettings).delete()
    db.add(models.WorkItemSettings(
        ticket_key=ticket_key, authoring_mode=mode,
        autonomous_max_rounds=rounds, owner_id=1,
    ))
    db.commit()
    return resolve_settings(db, 1, None, ticket_key=ticket_key)


def spend(db, count: int, *, opened=False, ticket_key="LOC-42"):
    for _ in range(count):
        authoring.record_attempt(
            db,
            owner_id=1,
            request=authoring.AuthoringRequest(
                ticket_key=ticket_key, title="t", repo="acme/api"
            ),
            result=authoring.AuthoringResult(
                opened=opened, pr_number=1 if opened else None, driver="stub"
            ),
        )


class TestShouldRetry:
    def test_the_first_attempt_is_allowed(self, db):
        retry, _ = authoring.should_retry(
            db, owner_id=1, ticket_key="LOC-42", settings=settings_for(db)
        )
        assert retry is True

    def test_the_bound_is_the_first_attempt_plus_the_reworks(self, db):
        """`autonomous_max_rounds = 2` means three swings, then a person."""
        s = settings_for(db, rounds=2)

        spend(db, 2)
        assert authoring.should_retry(
            db, owner_id=1, ticket_key="LOC-42", settings=s
        )[0] is True

        spend(db, 1)
        retry, reason = authoring.should_retry(
            db, owner_id=1, ticket_key="LOC-42", settings=s
        )
        assert retry is False
        assert "3 times" in reason

    def test_failures_consume_the_bound_too(self, db):
        """
        Decision 3. Without it a reliably-failing ticket retries forever and
        the bound protects nothing.
        """
        s = settings_for(db, rounds=0)
        spend(db, 1, opened=False)

        assert authoring.should_retry(
            db, owner_id=1, ticket_key="LOC-42", settings=s
        )[0] is False

    def test_assisted_mode_never_retries(self, db):
        retry, reason = authoring.should_retry(
            db, owner_id=1, ticket_key="LOC-42",
            settings=settings_for(db, mode="assisted"),
        )
        assert retry is False
        assert "off for this work item" in reason

    def test_a_handed_back_item_never_retries(self, db):
        settings_for(db)
        authoring.hand_back(db, owner_id=1, ticket_key="LOC-42", reason="spent")

        retry, reason = authoring.should_retry(
            db, owner_id=1, ticket_key="LOC-42",
            settings=resolve_settings(db, 1, None, ticket_key="LOC-42"),
        )
        assert retry is False
        assert reason == "spent"

    def test_a_human_push_stops_it(self, db):
        """
        The same rule as a human commit at authoring time: an agent
        overwriting somebody's work is the worst thing it can do quietly.
        """
        retry, reason = authoring.should_retry(
            db, owner_id=1, ticket_key="LOC-42",
            settings=settings_for(db), human_pushed=True,
        )
        assert retry is False
        assert "human has pushed" in reason

    def test_the_throughput_cap_stops_it(self, db, monkeypatch):
        monkeypatch.setattr(authoring, "MAX_OPEN_AUTONOMOUS_PRS", 1)
        s = settings_for(db)
        spend(db, 1, opened=True, ticket_key="OTHER-1")

        retry, reason = authoring.should_retry(
            db, owner_id=1, ticket_key="LOC-42", settings=s, repo="acme/api"
        )
        assert retry is False
        assert "already open" in reason


class TestHandoffMessage:
    def test_states_the_count_and_what_happens_next(self):
        """
        "Locus gave up" tells somebody nothing they can act on. The most
        useful thing to know is that picking it up costs only reading.
        """
        message = authoring.handoff_message(
            "LOC-42", attempts=3,
            reason="the test suite is still failing",
        )

        assert "LOC-42 is yours now" in message
        assert "3 times" in message
        assert "test suite is still failing" in message
        assert "unchanged" in message


class TestHandBackPersistsFirst:
    @pytest.mark.asyncio
    async def test_the_write_survives_a_failed_announcement(self, db, monkeypatch):
        """
        The reverse order -- announcing a handoff that did not persist --
        re-triggers the driver on the next event, so the team reads "it is
        yours now" while the agent keeps working.
        """
        async def explode(*args, **kwargs):
            raise RuntimeError("Slack is down")

        monkeypatch.setattr(
            "app.services.pipeline.review_flow.post_review_notification", explode
        )

        await authoring_flow._hand_back(
            db, owner_id=1, repo="acme/api", pr_number=1, ticket_key="LOC-42",
            reason="spent", integration_configs={"slack": {"bot_token": "x"}},
            slack_channel="#review",
        )

        row = db.query(models.WorkItemSettings).first()
        assert row.handed_back_at is not None
        assert row.handed_back_reason == "spent"

    @pytest.mark.asyncio
    async def test_a_second_handoff_does_not_announce_again(self, db, monkeypatch):
        """
        A repeat is what gets a bot muted, and a muted bot takes the review
        pings and QA threads down with it.
        """
        sends = []

        async def capture(config, channel, text):
            sends.append(text)
            return True

        monkeypatch.setattr(
            "app.services.pipeline.review_flow.post_review_notification", capture
        )

        for _ in range(2):
            await authoring_flow._hand_back(
                db, owner_id=1, repo="acme/api", pr_number=1,
                ticket_key="LOC-42", reason="spent",
                integration_configs={"slack": {"bot_token": "x"}},
                slack_channel="#review",
            )

        assert len(sends) == 1

    @pytest.mark.asyncio
    async def test_a_failed_announcement_is_recorded_as_failed(self, db, monkeypatch):
        """
        A message nobody received looks exactly like one nobody answered, so
        the record has to distinguish them.
        """
        async def refuse(*args, **kwargs):
            return False

        monkeypatch.setattr(
            "app.services.pipeline.review_flow.post_review_notification", refuse
        )

        await authoring_flow._hand_back(
            db, owner_id=1, repo="acme/api", pr_number=1, ticket_key="LOC-42",
            reason="spent", integration_configs={"slack": {"bot_token": "x"}},
            slack_channel="#review",
        )

        event = db.query(models.CommunicationEvent).filter(
            models.CommunicationEvent.outcome == "handed_back"
        ).first()
        assert event is not None
        assert event.succeeded == 0


class TestMaybeRetry:
    @pytest.mark.asyncio
    async def test_a_work_item_is_never_guessed(self, db, monkeypatch):
        """
        Attaching a key we inferred would put one team's rejection history in
        front of another team's pull request.
        """
        called = []
        monkeypatch.setattr(
            authoring, "get_driver", lambda *a, **k: _Driver(called)
        )

        result = await authoring_flow.maybe_retry(
            db, owner_id=1, repo="acme/api", pr_number=1, ticket_key=None,
            settings=settings_for(db), integration_configs={},
            trigger="changes_requested",
        )

        assert result is None
        assert called == []

    @pytest.mark.asyncio
    async def test_no_driver_configured_does_nothing_quietly(self, db, monkeypatch):
        monkeypatch.delenv("LOCUS_AUTHORING_DRIVER", raising=False)

        result = await authoring_flow.maybe_retry(
            db, owner_id=1, repo="acme/api", pr_number=1, ticket_key="LOC-42",
            settings=settings_for(db), integration_configs={},
            trigger="changes_requested",
        )

        assert result is None
        assert db.query(models.WorkItemSettings).first().handed_back_at is None

    @pytest.mark.asyncio
    async def test_a_held_retry_at_the_cap_says_nothing(self, db, monkeypatch):
        """
        A held retry that reports every time trains people to ignore the
        channel, the same rule `automerge.sweep_once` follows.
        """
        sends = []

        async def capture(config, channel, text):
            sends.append(text)
            return True

        monkeypatch.setattr(
            "app.services.pipeline.review_flow.post_review_notification", capture
        )
        monkeypatch.setattr(authoring, "MAX_OPEN_AUTONOMOUS_PRS", 1)
        monkeypatch.setattr(authoring, "get_driver", lambda *a, **k: _Driver([]))

        s = settings_for(db)
        spend(db, 1, opened=True, ticket_key="OTHER-1")

        await authoring_flow.maybe_retry(
            db, owner_id=1, repo="acme/api", pr_number=1, ticket_key="LOC-42",
            settings=s, integration_configs={"slack": {"bot_token": "x"}},
            trigger="changes_requested", slack_channel="#review",
        )

        assert sends == []
        assert db.query(models.WorkItemSettings).first().handed_back_at is None

    @pytest.mark.asyncio
    async def test_a_spent_bound_hands_back_and_announces_once(
        self, db, monkeypatch
    ):
        sends = []

        async def capture(config, channel, text):
            sends.append(text)
            return True

        monkeypatch.setattr(
            "app.services.pipeline.review_flow.post_review_notification", capture
        )
        monkeypatch.setattr(authoring, "get_driver", lambda *a, **k: _Driver([]))

        s = settings_for(db, rounds=0)
        spend(db, 1)

        await authoring_flow.maybe_retry(
            db, owner_id=1, repo="acme/api", pr_number=1, ticket_key="LOC-42",
            settings=s, integration_configs={"slack": {"bot_token": "x"}},
            trigger="changes_requested", slack_channel="#review",
        )

        assert len(sends) == 1
        assert "LOC-42 is yours now" in sends[0]
        assert db.query(models.WorkItemSettings).first().handed_back_at is not None

    @pytest.mark.asyncio
    async def test_a_successful_retry_records_its_trigger(self, db, monkeypatch):
        monkeypatch.setattr(authoring, "get_driver", lambda *a, **k: _Driver([]))

        result = await authoring_flow.maybe_retry(
            db, owner_id=1, repo="acme/api", pr_number=1, ticket_key="LOC-42",
            settings=settings_for(db), integration_configs={},
            trigger="qa_rejected", rejection="the button does nothing",
        )

        assert result.opened is True
        row = authoring.attempts_for(db, 1, "LOC-42")[0]
        assert row.trigger == "qa_rejected"

    @pytest.mark.asyncio
    async def test_the_rejection_reaches_the_driver(self, db, monkeypatch):
        seen = []
        monkeypatch.setattr(
            authoring, "get_driver", lambda *a, **k: _Driver(seen)
        )

        await authoring_flow.maybe_retry(
            db, owner_id=1, repo="acme/api", pr_number=1, ticket_key="LOC-42",
            settings=settings_for(db), integration_configs={},
            trigger="qa_rejected", rejection="the button does nothing",
        )

        assert seen[0].rejection == "the button does nothing"
        assert seen[0].trigger == "qa_rejected"

    @pytest.mark.asyncio
    async def test_a_driver_that_raises_still_consumes_an_attempt(
        self, db, monkeypatch
    ):
        """
        Every failure consumes an attempt. One that escaped past the recording
        would not, which is how a reliably-failing ticket retries forever.
        """
        class Exploding:
            name = "boom"

            async def author(self, request, configs):
                raise RuntimeError("the driver died")

        monkeypatch.setattr(authoring, "get_driver", lambda *a, **k: Exploding())

        await authoring_flow.maybe_retry(
            db, owner_id=1, repo="acme/api", pr_number=1, ticket_key="LOC-42",
            settings=settings_for(db), integration_configs={},
            trigger="changes_requested",
        )

        rows = authoring.attempts_for(db, 1, "LOC-42")
        assert len(rows) == 1
        assert "the driver died" in rows[0].error


class TestMergeGate:
    def _review(self, **kwargs):
        base = dict(
            repo="acme/api", pr_number=1, owner_id=1,
            state=schemas.ReviewState.approved.value,
        )
        base.update(kwargs)
        return models.PRReview(**base)

    def test_a_machine_authored_workflow_edit_never_merges(self):
        """
        The one thing that must not happen is a machine-written change to the
        checks that gate machine-written changes landing on the strength of
        those checks.
        """
        allowed, blockers = review_flow.evaluate_merge_gate(
            self._review(), None, "success", [], True,
            changed_paths=[".github/workflows/ci.yml", "src/thing.py"],
            machine_authored=True,
        )

        assert allowed is False
        assert any("CI workflows" in b for b in blockers)

    def test_a_human_authored_workflow_edit_is_not_blocked_by_this_rule(self):
        """The rule is about machine-authored changes, not about workflows."""
        allowed, _ = review_flow.evaluate_merge_gate(
            self._review(), None, "success", [], True,
            changed_paths=[".github/workflows/ci.yml"],
            machine_authored=False,
        )

        assert allowed is True

    def test_a_machine_authored_change_elsewhere_still_merges(self):
        allowed, _ = review_flow.evaluate_merge_gate(
            self._review(), None, "success", [], True,
            changed_paths=["src/thing.py"], machine_authored=True,
        )

        assert allowed is True

    def test_the_author_cannot_be_the_approving_reviewer(self):
        """
        True today by construction, asserted so it cannot regress. An approval
        by the author is not a review, and autonomous mode makes the author a
        machine.
        """
        allowed, blockers = review_flow.evaluate_merge_gate(
            self._review(author="dev", last_reviewer="dev"),
            None, "success", [], True,
        )

        assert allowed is False
        assert any("author" in b for b in blockers)

    def test_a_different_reviewer_is_fine(self):
        allowed, _ = review_flow.evaluate_merge_gate(
            self._review(author="dev", last_reviewer="lead"),
            None, "success", [], True,
        )

        assert allowed is True

    def test_review_findings_still_do_not_block_at_any_priority(self):
        """
        Do not quietly tighten this for authored PRs: it would make the
        approval advisory, which is the failure the current wording describes.
        """
        analysis = schemas.PRAnalysisResult(
            repo="acme/api", pr_number=1,
            context=schemas.PRContext(
                repo="acme/api", pr_number=1, title="t", author="dev",
                url="https://github.invalid/pr/1",
            ),
            review_findings=[schemas.ReviewFinding(
                title="This is wrong", priority="p1", description="x",
                file_path="a.py",
            )],
        )

        allowed, _ = review_flow.evaluate_merge_gate(
            self._review(), analysis, "success", [], True,
            machine_authored=True, changed_paths=["src/a.py"],
        )

        assert allowed is True


class _Driver:
    """A driver that records the requests it was given and opens a PR."""

    name = "stub"

    def __init__(self, seen: list):
        self._seen = seen

    async def author(self, request, integration_configs):
        self._seen.append(request)
        return authoring.AuthoringResult(
            opened=True, pr_number=99, pr_url="https://github.invalid/pr/99",
            branch="locus/LOC-42-1", driver=self.name,
        )
