"""
The authoring dial: who writes the code for a work item.

`resolve_settings` gained a third and most specific layer. Autonomy is a
judgement about *this ticket* -- a dependency bump and a change to the
credential path are not the same risk -- and as one account-wide switch the
most dangerous ticket in the backlog sets policy for every ticket, so teams
leave it off and the mode is never exercised.

The property this file exists to protect: `ticket_key=None` must resolve
exactly as it did before the work-item layer existed. Every pre-existing call
site passes no ticket, and `tests/test_agent_defaults.py` passes unchanged
precisely because of it.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.services import task_board
from app.services.agent_settings import normalize_mode, resolve_settings


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


def defaults(db, **kwargs):
    row = models.PRAgentDefaults(owner_id=1, **kwargs)
    db.add(row)
    db.commit()
    return row


def registration(**kwargs):
    base = dict(repo="a/b", encrypted_secret="x", enabled=1, owner_id=1)
    base.update(kwargs)
    return models.RepoWebhook(**base)


def work_item(db, key="LOC-42", **kwargs):
    row = models.WorkItemSettings(ticket_key=key, owner_id=1, **kwargs)
    db.add(row)
    db.commit()
    return row


class TestResolutionChain:
    def test_nothing_anywhere_is_assisted(self, db):
        """The fallback is the safe mode, not the configured one."""
        resolved = resolve_settings(db, owner_id=1, registration=None)

        assert resolved.authoring_mode == "assisted"
        assert resolved.autonomous_max_rounds == 2
        assert resolved.sources["authoring_mode"] == "unset"

    def test_defaults_supply_the_mode(self, db):
        defaults(db, authoring_mode="autonomous", autonomous_max_rounds=4)

        resolved = resolve_settings(db, owner_id=1, registration=None)

        assert resolved.authoring_mode == "autonomous"
        assert resolved.autonomous_max_rounds == 4
        assert resolved.sources["authoring_mode"] == "defaults"

    def test_repo_beats_defaults(self, db):
        defaults(db, authoring_mode="autonomous")

        resolved = resolve_settings(
            db, owner_id=1, registration=registration(authoring_mode="assisted")
        )

        assert resolved.authoring_mode == "assisted"
        assert resolved.sources["authoring_mode"] == "repo"

    def test_work_item_beats_repo(self, db):
        defaults(db, authoring_mode="assisted")
        work_item(db, authoring_mode="autonomous")

        resolved = resolve_settings(
            db,
            owner_id=1,
            registration=registration(authoring_mode="assisted"),
            ticket_key="LOC-42",
        )

        assert resolved.authoring_mode == "autonomous"
        assert resolved.sources["authoring_mode"] == "work_item"

    def test_work_item_can_turn_it_off_for_one_ticket(self, db):
        """The direction that matters most: one risky ticket opting out."""
        defaults(db, authoring_mode="autonomous")
        work_item(db, key="LOC-9", authoring_mode="assisted")

        resolved = resolve_settings(
            db, owner_id=1, registration=None, ticket_key="LOC-9"
        )

        assert resolved.authoring_mode == "assisted"
        assert resolved.sources["authoring_mode"] == "work_item"

    def test_another_users_row_is_never_read(self, db):
        db.add(models.WorkItemSettings(
            ticket_key="LOC-42", authoring_mode="autonomous", owner_id=2
        ))
        db.commit()

        resolved = resolve_settings(
            db, owner_id=1, registration=None, ticket_key="LOC-42"
        )

        assert resolved.authoring_mode == "assisted"
        assert resolved.sources["authoring_mode"] == "unset"


class TestNoTicketKey:
    """
    Every call site that predates this layer passes no ticket, so the two must
    resolve identically or the change is not additive.
    """

    def test_a_work_item_row_is_invisible_without_its_key(self, db):
        work_item(db, authoring_mode="autonomous")

        resolved = resolve_settings(db, owner_id=1, registration=None)

        assert resolved.authoring_mode == "assisted"
        assert resolved.sources["authoring_mode"] == "unset"

    def test_every_other_setting_is_untouched_by_a_ticket_key(self, db):
        defaults(db, slack_channel="#web", export_to_docs=1)
        work_item(db, authoring_mode="autonomous")

        without = resolve_settings(db, owner_id=1, registration=None)
        with_key = resolve_settings(
            db, owner_id=1, registration=None, ticket_key="LOC-42"
        )

        assert without.slack_channel == with_key.slack_channel
        assert without.export_to_docs == with_key.export_to_docs
        assert without.qa_emails == with_key.qa_emails
        assert without.close_on_qa_signoff == with_key.close_on_qa_signoff


class TestHandedBack:
    def test_a_handed_back_item_forces_assisted(self, db):
        """
        Overrides everything above it. Without this the next review event
        re-triggers the driver on a work item that was explicitly given back.
        """
        from datetime import UTC, datetime

        defaults(db, authoring_mode="autonomous")
        work_item(
            db,
            authoring_mode="autonomous",
            handed_back_at=datetime.now(UTC),
            handed_back_reason="Three attempts, tests still failing",
        )

        resolved = resolve_settings(
            db,
            owner_id=1,
            registration=registration(authoring_mode="autonomous"),
            ticket_key="LOC-42",
        )

        assert resolved.authoring_mode == "assisted"
        assert resolved.sources["authoring_mode"] == "handed_back"
        assert resolved.handed_back is True
        assert resolved.handed_back_reason == "Three attempts, tests still failing"

    def test_an_ordinary_assisted_choice_is_not_a_handoff(self, db):
        """The UI reads these differently: one is a choice, one is a limit."""
        work_item(db, authoring_mode="assisted")

        resolved = resolve_settings(
            db, owner_id=1, registration=None, ticket_key="LOC-42"
        )

        assert resolved.sources["authoring_mode"] == "work_item"
        assert resolved.handed_back is False


class TestRounds:
    def test_the_bound_resolves_through_the_same_chain(self, db):
        defaults(db, autonomous_max_rounds=5)
        work_item(db, autonomous_max_rounds=1)

        assert resolve_settings(
            db, owner_id=1, registration=None
        ).autonomous_max_rounds == 5
        assert resolve_settings(
            db, owner_id=1, registration=None, ticket_key="LOC-42"
        ).autonomous_max_rounds == 1

    def test_zero_is_a_real_bound_not_an_absence(self, db):
        """One attempt and no reworks. Truthiness would read this as unset."""
        work_item(db, autonomous_max_rounds=0)

        resolved = resolve_settings(
            db, owner_id=1, registration=None, ticket_key="LOC-42"
        )

        assert resolved.autonomous_max_rounds == 0
        assert resolved.sources["autonomous_max_rounds"] == "work_item"


class TestNormalizeMode:
    def test_an_unrecognised_mode_degrades_to_assisted(self):
        """A bad value falls to the safe behaviour rather than 400-ing."""
        assert normalize_mode("wildly-autonomous") == "assisted"

    def test_none_stays_none(self):
        """None is how a repo row says nothing; coercing it would break the chain."""
        assert normalize_mode(None) is None
        assert normalize_mode("   ") is None

    def test_case_and_whitespace_are_tolerated(self):
        assert normalize_mode(" Autonomous ") == "autonomous"


class TestSourcePaths:
    def test_the_worktree_settings_resolve_repo_over_defaults(self, db):
        defaults(db, prepare_command="uv sync", test_command="pytest -q")

        resolved = resolve_settings(
            db,
            owner_id=1,
            registration=registration(test_command="pytest tests/ -q"),
        )

        assert resolved.prepare_command == "uv sync"
        assert resolved.sources["prepare_command"] == "defaults"
        assert resolved.test_command == "pytest tests/ -q"
        assert resolved.sources["test_command"] == "repo"

    def test_no_test_command_means_no_gate(self, db):
        assert resolve_settings(
            db, owner_id=1, registration=None
        ).test_command is None


# --- API -------------------------------------------------------------------


def _card(key: str, title: str = "A ticket"):
    from app import schemas

    return schemas.TaskCard(
        key=key,
        title=title,
        url="https://example.invalid/browse/" + key,
        source="jira",
        stage="assigned",
        stages=[],
        pull_requests=[],
    )


@pytest.fixture
def client(tmp_path, monkeypatch):
    import main
    from app import schemas
    from app.database import Base, get_db

    engine = create_engine(
        f"sqlite:///{tmp_path}/api.db", connect_args={"check_same_thread": False}
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
        # Only "LOC-42" is assigned to whoever is asking. Everything else must
        # 404 rather than 403 -- a 403 confirms the key exists.
        return schemas.TaskBoard(
            needs_you=[], in_flight=[_card("LOC-42")], unavailable=[], total=1
        )

    monkeypatch.setattr(task_board, "build", fake_build)

    main.app.dependency_overrides[get_db] = override
    with TestClient(main.app) as c:
        signup = c.post(
            "/auth/signup", json={"email": "m@x.com", "password": "secret123"}
        ).json()
        c.headers["Authorization"] = f"Bearer {signup['token']}"
        yield c
    main.app.dependency_overrides.clear()


class TestModeApi:
    def test_reads_the_resolved_mode_and_its_source(self, client):
        body = client.get("/tasks/mode", params={"task_key": "LOC-42"}).json()

        assert body["authoring_mode"] == "assisted"
        assert body["source"] == "unset"
        assert body["override"] is None

    def test_an_override_round_trips(self, client):
        client.put(
            "/tasks/mode",
            params={"task_key": "LOC-42"},
            json={"authoring_mode": "autonomous", "autonomous_max_rounds": 3},
        )

        body = client.get("/tasks/mode", params={"task_key": "LOC-42"}).json()
        assert body["authoring_mode"] == "autonomous"
        assert body["autonomous_max_rounds"] == 3
        assert body["source"] == "work_item"
        assert body["override"] == "autonomous"

    def test_a_null_mode_deletes_the_row_rather_than_storing_null(self, client):
        """
        Absence means "inherit". A row of nulls reads as a deliberate choice
        to the next person who queries the table.
        """
        client.put(
            "/tasks/mode",
            params={"task_key": "LOC-42"},
            json={"authoring_mode": "autonomous"},
        )
        client.put(
            "/tasks/mode",
            params={"task_key": "LOC-42"},
            json={"authoring_mode": None, "autonomous_max_rounds": None},
        )

        body = client.get("/tasks/mode", params={"task_key": "LOC-42"}).json()
        assert body["source"] == "unset"
        assert body["override"] is None

    def test_another_users_task_is_404_not_403(self, client):
        """A 403 confirms the key exists, which is enough to enumerate."""
        assert client.get(
            "/tasks/mode", params={"task_key": "OTHER-1"}
        ).status_code == 404
        assert client.put(
            "/tasks/mode",
            params={"task_key": "OTHER-1"},
            json={"authoring_mode": "autonomous"},
        ).status_code == 404

    def test_choosing_a_mode_clears_a_handoff(self, client):
        """
        The handoff stops the driver re-triggering itself. It was never meant
        to stop a person from deciding otherwise.
        """
        from datetime import UTC, datetime

        client.put(
            "/tasks/mode",
            params={"task_key": "LOC-42"},
            json={"authoring_mode": "autonomous"},
        )

        import main
        from app.database import get_db

        session = next(main.app.dependency_overrides[get_db]())
        row = session.query(models.WorkItemSettings).first()
        row.handed_back_at = datetime.now(UTC)
        row.handed_back_reason = "spent"
        session.commit()

        assert client.get(
            "/tasks/mode", params={"task_key": "LOC-42"}
        ).json()["source"] == "handed_back"

        body = client.put(
            "/tasks/mode",
            params={"task_key": "LOC-42"},
            json={"authoring_mode": "autonomous"},
        ).json()
        assert body["source"] == "work_item"
        assert body["handed_back"] is False

    def test_an_unrecognised_mode_is_rejected_by_the_schema(self, client):
        """
        The enum guards the API surface; `normalize_mode` guards what is
        already stored. Different jobs, and both are wanted.
        """
        assert client.put(
            "/tasks/mode",
            params={"task_key": "LOC-42"},
            json={"authoring_mode": "sentient"},
        ).status_code == 422

    def test_requires_authentication(self, client):
        assert client.get(
            "/tasks/mode",
            params={"task_key": "LOC-42"},
            headers={"Authorization": "Bearer bad"},
        ).status_code == 401


class TestRepoSettingsApi:
    def test_the_dial_round_trips_through_the_defaults_endpoint(self, client):
        client.put("/webhooks/defaults", json={
            "authoring_mode": "autonomous",
            "autonomous_max_rounds": 3,
            "test_command": "pytest -q",
        })

        body = client.get("/webhooks/defaults").json()
        assert body["authoring_mode"] == "autonomous"
        assert body["autonomous_max_rounds"] == 3
        assert body["test_command"] == "pytest -q"

    def test_defaults_are_assisted_before_anything_is_saved(self, client):
        body = client.get("/webhooks/defaults").json()

        assert body["authoring_mode"] == "assisted"
        assert body["autonomous_max_rounds"] == 2
