"""
The driver contract, and the guards on the board's second write.

The seam. The driver's entire contract is "open a pull request and return its
number" -- it does not merge, comment, notify or move a card, because
everything after the pull request exists is the pipeline that already runs.
That is what makes autonomous mode a setting rather than a fork.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.services import authoring, task_board


@pytest.fixture
def db(tmp_path):
    from app.database import Base

    engine = create_engine(
        f"sqlite:///{tmp_path}/d.db", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def request(**kwargs) -> authoring.AuthoringRequest:
    base = dict(ticket_key="LOC-42", title="Add the thing", repo="acme/api")
    base.update(kwargs)
    return authoring.AuthoringRequest(**base)


class TestNoneDriver:
    @pytest.mark.asyncio
    async def test_returns_an_error_not_an_empty_success(self):
        """
        The same distinction `comms_log` draws between a search that found
        nothing and one that never ran. "No driver is configured" and "the
        agent looked at this ticket and produced nothing" send someone to very
        different places.
        """
        result = await authoring.NoneDriver().author(request(), {})

        assert result.opened is False
        assert result.error and "driver" in result.error.lower()

    def test_is_the_default(self, monkeypatch):
        monkeypatch.delenv("LOCUS_AUTHORING_DRIVER", raising=False)

        assert authoring.get_driver().name == "none"

    def test_an_unknown_driver_name_falls_back_rather_than_raising(self, monkeypatch):
        """A bad driver name must not break app startup."""
        monkeypatch.setenv("LOCUS_AUTHORING_DRIVER", "nonexistent")

        assert authoring.get_driver().name == "none"


class TestContextMode:
    def test_full_is_the_default(self, monkeypatch):
        monkeypatch.delenv("LOCUS_AUTHORING_CONTEXT", raising=False)

        assert authoring.context_mode() == "full"
        assert request(context="the discussion").scoped().context == "the discussion"

    def test_ticket_only_drops_the_internal_discussion(self, monkeypatch):
        """
        A team that cannot send internal discussion to a third party gets a
        usable mode rather than no mode.
        """
        monkeypatch.setenv("LOCUS_AUTHORING_CONTEXT", "ticket_only")

        scoped = request(context="a Slack thread", description="the ticket").scoped()
        assert scoped.context == ""
        assert scoped.description == "the ticket"

    def test_ticket_only_keeps_the_asks_and_the_rejection(self, monkeypatch):
        """
        They are what the rework is responding to. An attempt that cannot see
        them is not a rework.
        """
        monkeypatch.setenv("LOCUS_AUTHORING_CONTEXT", "ticket_only")

        scoped = request(
            context="a Slack thread",
            asks=["add the word orange too"],
            rejection="the button does nothing",
        ).scoped()

        assert scoped.asks == ["add the word orange too"]
        assert scoped.rejection == "the button does nothing"

    def test_an_unrecognised_mode_degrades_to_full(self, monkeypatch):
        monkeypatch.setenv("LOCUS_AUTHORING_CONTEXT", "some_of_it")

        assert authoring.context_mode() == "full"


class TestAttemptHistory:
    def test_every_outcome_is_recorded_including_the_ones_that_opened_nothing(self, db):
        """
        Decision 3. A failure that left no row would not consume an attempt,
        and a reliably-failing ticket would retry forever.
        """
        authoring.record_attempt(
            db,
            owner_id=1,
            request=request(attempt=1),
            result=authoring.AuthoringResult(
                opened=False, error="timed out after 1200s", driver="opencode"
            ),
        )

        rows = authoring.attempts_for(db, 1, "LOC-42")
        assert len(rows) == 1
        assert rows[0].opened == 0
        assert rows[0].error == "timed out after 1200s"

    def test_the_next_attempt_counts_failures_too(self, db):
        for _ in range(2):
            authoring.record_attempt(
                db,
                owner_id=1,
                request=request(),
                result=authoring.AuthoringResult(opened=False, error="nope"),
            )

        assert authoring.next_attempt_number(db, owner_id=1, ticket_key="LOC-42") == 3

    def test_the_model_is_recorded_per_attempt(self, db):
        """
        "Which model wrote this diff" is the first question asked when an
        agent-authored change turns out to be wrong, and a mutable config value
        cannot answer it retroactively.
        """
        authoring.record_attempt(
            db,
            owner_id=1,
            request=request(),
            result=authoring.AuthoringResult(
                opened=True, pr_number=7, driver="opencode",
                model="some-model-v2", context_mode="ticket_only",
            ),
        )

        row = authoring.attempts_for(db, 1, "LOC-42")[0]
        assert row.model == "some-model-v2"
        assert row.context_mode == "ticket_only"

    def test_the_trigger_distinguishes_reworks_from_retries(self, db):
        """
        "The agent has tried three things" and "the agent tried once and a
        reviewer pushed back twice" need different responses from the person
        the work returns to.
        """
        for trigger in ("initial", "changes_requested", "qa_rejected"):
            authoring.record_attempt(
                db,
                owner_id=1,
                request=request(trigger=trigger),
                result=authoring.AuthoringResult(opened=True, pr_number=1),
            )

        assert [r.trigger for r in authoring.attempts_for(db, 1, "LOC-42")] == [
            "initial", "changes_requested", "qa_rejected"
        ]

    def test_another_users_attempts_are_never_counted(self, db):
        authoring.record_attempt(
            db, owner_id=2, request=request(),
            result=authoring.AuthoringResult(opened=False),
        )

        assert authoring.next_attempt_number(db, owner_id=1, ticket_key="LOC-42") == 1


class TestThroughputGuard:
    def _opened(self, db, pr_number: int, owner_id: int = 1):
        authoring.record_attempt(
            db, owner_id=owner_id, request=request(),
            result=authoring.AuthoringResult(
                opened=True, pr_number=pr_number, driver="opencode"
            ),
        )

    def test_counts_agent_authored_pull_requests_that_have_not_merged(self, db):
        for number in (1, 2):
            self._opened(db, number)

        assert authoring.open_autonomous_prs(db, owner_id=1, repo="acme/api") == 2

    def test_a_merged_pull_request_stops_counting(self, db):
        self._opened(db, 1)
        db.add(models.PRReview(
            repo="acme/api", pr_number=1, state="merged", owner_id=1
        ))
        db.commit()

        assert authoring.open_autonomous_prs(db, owner_id=1, repo="acme/api") == 0

    def test_several_attempts_on_one_pull_request_count_once(self, db):
        """The cap is on reviewer attention, and a rework is the same PR."""
        for _ in range(3):
            self._opened(db, 1)

        assert authoring.open_autonomous_prs(db, owner_id=1, repo="acme/api") == 1

    def test_attempts_that_opened_nothing_do_not_count(self, db):
        authoring.record_attempt(
            db, owner_id=1, request=request(),
            result=authoring.AuthoringResult(opened=False, error="empty diff"),
        )

        assert authoring.open_autonomous_prs(db, owner_id=1, repo="acme/api") == 0

    def test_the_cap_is_per_repo(self, db):
        self._opened(db, 1)

        assert authoring.throughput_exceeded(db, owner_id=1, repo="acme/other") is False

    def test_exceeded_at_the_configured_cap(self, db, monkeypatch):
        monkeypatch.setattr(authoring, "MAX_OPEN_AUTONOMOUS_PRS", 2)
        for number in (1, 2):
            self._opened(db, number)

        assert authoring.throughput_exceeded(db, owner_id=1, repo="acme/api") is True


class TestHandBack:
    def test_records_the_reason_and_the_time(self, db):
        row = authoring.hand_back(
            db, owner_id=1, ticket_key="LOC-42",
            reason="Three attempts, tests still failing",
        )

        assert row.handed_back_at is not None
        assert row.handed_back_reason == "Three attempts, tests still failing"

    def test_upserts_onto_an_existing_override(self, db):
        db.add(models.WorkItemSettings(
            ticket_key="LOC-42", authoring_mode="autonomous", owner_id=1
        ))
        db.commit()

        authoring.hand_back(db, owner_id=1, ticket_key="LOC-42", reason="spent")

        rows = db.query(models.WorkItemSettings).all()
        assert len(rows) == 1
        assert rows[0].handed_back_reason == "spent"


class TestGatherAsks:
    def test_carries_every_round_oldest_first(self, db):
        """
        A request satisfied in round two is still something the rework must
        not undo, so every round is carried rather than only the last.
        """
        review = models.PRReview(
            repo="acme/api", pr_number=1, state="changes_requested",
            ticket_keys="LOC-42", owner_id=1,
        )
        db.add(review)
        db.commit()
        for body in ("add the word orange too", "and rename the helper"):
            db.add(models.PRReviewRound(
                review_id=review.id, outcome="changes_requested",
                round_number=1, body=body,
            ))
        db.commit()

        assert authoring.gather_asks(db, owner_id=1, ticket_key="LOC-42") == [
            "add the word orange too", "and rename the helper"
        ]

    def test_an_approval_carries_no_ask(self, db):
        review = models.PRReview(
            repo="acme/api", pr_number=1, state="approved",
            ticket_keys="LOC-42", owner_id=1,
        )
        db.add(review)
        db.commit()
        db.add(models.PRReviewRound(
            review_id=review.id, outcome="approved", round_number=1, body="lgtm",
        ))
        db.commit()

        assert authoring.gather_asks(db, owner_id=1, ticket_key="LOC-42") == []


# --- The endpoint ----------------------------------------------------------


def _card(key: str, *, repo: str | None = "acme/api"):
    from app import schemas

    return schemas.TaskCard(
        key=key,
        title="Add the thing",
        url="https://example.invalid/browse/" + key,
        source="jira",
        stage="assigned",
        stages=[],
        pull_requests=(
            [schemas.TaskPullRequest(repo=repo, pr_number=1, state="awaiting_review")]
            if repo else []
        ),
    )


@pytest.fixture
def client(tmp_path, monkeypatch):
    import main
    from app import schemas
    from app.database import Base, get_db

    engine = create_engine(
        f"sqlite:///{tmp_path}/a.db", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    async def fake_build(db, owner_id, integration_configs):
        return schemas.TaskBoard(
            needs_you=[], in_flight=[_card("LOC-42")], unavailable=[], total=1
        )

    monkeypatch.setattr(task_board, "build", fake_build)

    main.app.dependency_overrides[get_db] = override
    with TestClient(main.app) as c:
        signup = c.post(
            "/auth/signup", json={"email": "a@x.com", "password": "secret123"}
        ).json()
        c.headers["Authorization"] = f"Bearer {signup['token']}"
        yield c
    main.app.dependency_overrides.clear()


def _go_autonomous(client):
    client.put(
        "/tasks/mode",
        params={"task_key": "LOC-42"},
        json={"authoring_mode": "autonomous"},
    )


class TestAuthorEndpoint:
    def test_a_task_that_is_not_yours_is_404_not_403(self, client):
        assert client.post(
            "/tasks/author", params={"task_key": "OTHER-1"}
        ).status_code == 404

    def test_assisted_mode_is_409_naming_the_source(self, client):
        response = client.post("/tasks/author", params={"task_key": "LOC-42"})

        assert response.status_code == 409
        assert "unset" in response.json()["detail"]

    def test_a_handed_back_item_is_409_carrying_the_reason(self, client, monkeypatch):
        import main
        from app.database import get_db

        _go_autonomous(client)
        session = next(main.app.dependency_overrides[get_db]())
        authoring.hand_back(
            session, owner_id=1, ticket_key="LOC-42",
            reason="Three attempts, tests still failing",
        )

        response = client.post("/tasks/author", params={"task_key": "LOC-42"})
        assert response.status_code == 409
        assert "tests still failing" in response.json()["detail"]

    def test_no_driver_configured_is_503(self, client, monkeypatch):
        monkeypatch.delenv("LOCUS_AUTHORING_DRIVER", raising=False)
        _go_autonomous(client)

        response = client.post("/tasks/author", params={"task_key": "LOC-42"})
        assert response.status_code == 503

    def test_the_throughput_cap_is_429(self, client, monkeypatch):
        import main
        from app.database import get_db

        _go_autonomous(client)
        monkeypatch.setattr(authoring, "get_driver", lambda *a, **k: _StubDriver())
        monkeypatch.setattr(authoring, "MAX_OPEN_AUTONOMOUS_PRS", 1)

        session = next(main.app.dependency_overrides[get_db]())
        authoring.record_attempt(
            session, owner_id=1, request=request(),
            result=authoring.AuthoringResult(
                opened=True, pr_number=9, driver="stub"
            ),
        )

        response = client.post("/tasks/author", params={"task_key": "LOC-42"})
        assert response.status_code == 429
        assert "reviewer attention" in response.json()["detail"].lower()

    def test_a_run_records_its_attempt_and_reports_the_pull_request(
        self, client, monkeypatch
    ):
        _go_autonomous(client)
        monkeypatch.setattr(authoring, "get_driver", lambda *a, **k: _StubDriver())

        body = client.post("/tasks/author", params={"task_key": "LOC-42"}).json()

        assert body["opened"] is True
        assert body["pr_number"] == 42
        assert body["attempt"] == 1
        assert body["attempts_remaining"] == 2

        history = client.get("/tasks/attempts", params={"task_key": "LOC-42"}).json()
        assert len(history) == 1
        assert history[0]["driver"] == "stub"

    def test_a_hand_back_from_the_driver_persists(self, client, monkeypatch):
        """
        A human's commits on the branch end autonomous mode for the work item
        immediately -- an agent overwriting a person's work is the worst thing
        it can do quietly.
        """
        _go_autonomous(client)
        monkeypatch.setattr(
            authoring, "get_driver",
            lambda *a, **k: _StubDriver(
                hand_back_reason="A human has commits on this branch"
            ),
        )

        body = client.post("/tasks/author", params={"task_key": "LOC-42"}).json()
        assert body["handed_back_reason"] == "A human has commits on this branch"

        mode = client.get("/tasks/mode", params={"task_key": "LOC-42"}).json()
        assert mode["source"] == "handed_back"
        assert mode["authoring_mode"] == "assisted"

    def test_requires_authentication(self, client):
        assert client.post(
            "/tasks/author",
            params={"task_key": "LOC-42"},
            headers={"Authorization": "Bearer bad"},
        ).status_code == 401


class _StubDriver:
    """A driver that opens a pull request without running anything."""

    name = "stub"

    def __init__(self, hand_back_reason: str | None = None):
        self._hand_back_reason = hand_back_reason

    async def author(self, request, integration_configs):
        return authoring.AuthoringResult(
            opened=self._hand_back_reason is None,
            pr_number=None if self._hand_back_reason else 42,
            pr_url=None if self._hand_back_reason else "https://github.invalid/pr/42",
            branch="locus/LOC-42-1",
            driver=self.name,
            model="stub-model",
            files_changed=2,
            lines_changed=30,
            hand_back_reason=self._hand_back_reason,
        )
