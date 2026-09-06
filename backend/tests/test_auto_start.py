"""
What starts the authoring agent.

`authoring_mode` answers "may the agent write this work item". These three
settings answer the separate question of who has to press the button, and the
two are checked independently everywhere -- an account with every trigger on
still writes nothing for an item somebody put in assisted mode.

The defaults are deliberately not uniform. The review and QA triggers fired
automatically before they were settings, so defaulting them off would silently
stop a pipeline that works, on an upgrade nobody thought was behavioural.
Assignment is new capability with a much larger blast radius and is opt-in.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models, schemas
from app.services.authoring import assignment_watch
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


class TestDefaults:
    def test_review_and_qa_default_on_assignment_off(self, db):
        """
        The asymmetry is the point, and it is load-bearing rather than a
        preference: two of these describe behaviour that already existed.
        """
        resolved = resolve_settings(db, 1, None)

        assert resolved.auto_start_on_review is True
        assert resolved.auto_start_on_qa is True
        assert resolved.auto_start_on_assignment is False

    def test_the_api_schema_agrees_with_the_resolver(self, db):
        """
        Two defaults for one setting drift. The form would then show a trigger
        as off while a run reads it as on, which is the "looks like the setting
        never saved" failure one layer up.
        """
        fields = schemas.PRAgentDefaultsUpdate.model_fields
        resolved = resolve_settings(db, 1, None)

        for name in (
            "auto_start_on_assignment",
            "auto_start_on_review",
            "auto_start_on_qa",
        ):
            assert fields[name].default == getattr(resolved, name), name

    def test_a_stored_choice_wins_over_the_default(self, db):
        db.add(models.PRAgentDefaults(
            owner_id=1,
            auto_start_on_assignment=1,
            auto_start_on_review=0,
            auto_start_on_qa=0,
        ))
        db.commit()

        resolved = resolve_settings(db, 1, None)

        assert resolved.auto_start_on_assignment is True
        assert resolved.auto_start_on_review is False
        assert resolved.auto_start_on_qa is False
        assert resolved.sources["auto_start_on_review"] == "defaults"

    def test_no_row_reports_unset_rather_than_a_choice(self, db):
        """
        `sources` is what the dashboard reads to explain a skipped stage, so
        "nobody has saved settings" must not render as a decision somebody
        made.
        """
        resolved = resolve_settings(db, 1, None)
        assert resolved.sources["auto_start_on_assignment"] == "unset"


class TestAssignmentSweepPicksOnlyUntouchedWork:
    """
    The sweep starts fresh work and nothing else. A rework belongs to the event
    triggers, which know which branch to continue -- starting a new branch
    under an open pull request is the duplicate-PR failure the rework fix
    exists to prevent, arriving from a different direction.
    """

    def _card(self, **kwargs) -> schemas.TaskCard:
        base = dict(
            key="acme/api#7",
            source=schemas.TaskSource.github,
            title="Add the thing",
            url="https://example.test/7",
        )
        base.update(kwargs)
        return schemas.TaskCard(**base)

    def test_an_untouched_item_is_picked_up(self, db):
        assert assignment_watch.is_untouched(
            db, owner_id=1, card=self._card()
        ) is True

    def test_an_item_with_a_pull_request_is_left_alone(self, db):
        card = self._card(pull_requests=[
            schemas.TaskPullRequest(repo="acme/api", pr_number=3)
        ])
        assert assignment_watch.is_untouched(db, owner_id=1, card=card) is False

    def test_an_item_with_a_linked_branch_is_left_alone(self, db):
        """
        Somebody opened a branch from the issue and is presumably writing in
        it. That is the state the board renders as `branch_created` rather
        than `assigned`.
        """
        card = self._card(linked_branches=[
            schemas.LinkedBranch(name="feature/thing", repo="acme/api")
        ])
        assert assignment_watch.is_untouched(db, owner_id=1, card=card) is False

    def test_a_previous_attempt_stops_it_forever(self, db):
        """
        The guard that makes the sweep idempotent across restarts. Without it
        a sweep that opened a pull request and then restarted opens a second
        one, because the board has not learned about the first yet.
        """
        db.add(models.AuthoringAttempt(
            owner_id=1, ticket_key="acme/api#7", repo="acme/api",
            attempt=1, trigger="initial",
        ))
        db.commit()

        assert assignment_watch.is_untouched(
            db, owner_id=1, card=self._card()
        ) is False

    def test_a_failed_attempt_also_stops_it(self, db):
        """
        A failure spends an attempt, and retrying it here would be a loop with
        no end -- the same reasoning as "every failure consumes an attempt".
        """
        db.add(models.AuthoringAttempt(
            owner_id=1, ticket_key="acme/api#7", repo="acme/api",
            attempt=1, trigger="initial", opened=0,
            error="the driver raised",
        ))
        db.commit()

        assert assignment_watch.is_untouched(
            db, owner_id=1, card=self._card()
        ) is False

    def test_another_users_attempt_does_not_block_yours(self, db):
        """Attempts are scoped to the owner, like everything else here."""
        db.add(models.AuthoringAttempt(
            owner_id=2, ticket_key="acme/api#7", repo="acme/api",
            attempt=1, trigger="initial",
        ))
        db.commit()

        assert assignment_watch.is_untouched(
            db, owner_id=1, card=self._card()
        ) is True


class TestOnlyEnabledAccountsAreSwept:
    def test_an_account_that_did_not_opt_in_is_absent(self, db):
        db.add(models.PRAgentDefaults(owner_id=1, auto_start_on_assignment=0))
        db.add(models.PRAgentDefaults(owner_id=2, auto_start_on_assignment=1))
        db.commit()

        assert assignment_watch._enabled_owner_ids(db) == [2]

    def test_an_account_with_no_defaults_row_is_absent(self, db):
        """
        Opt-in means opt-in: a deployment where nobody has saved settings must
        sweep nothing at all, and pay one query per tick to find that out.
        """
        assert assignment_watch._enabled_owner_ids(db) == []

    @pytest.mark.asyncio
    async def test_the_sweep_returns_immediately_with_nobody_enabled(
        self, monkeypatch, db
    ):
        called = {"boards": 0}

        async def fake_build(*_a, **_kw):
            called["boards"] += 1
            raise AssertionError("no board should be built")

        monkeypatch.setattr(
            "app.services.pipeline.task_board.build", fake_build
        )
        monkeypatch.setattr(
            "app.core.database.SessionLocal", lambda: db
        )
        monkeypatch.setattr(
            "app.services.authoring.assignment_watch.SessionLocal", lambda: db
        )

        assert await assignment_watch.sweep_once() == 0
        assert called["boards"] == 0


class TestTheGatesAreIndependentOfTheMode:
    """
    Two switches, and both must be on. Collapsing them would mean a team that
    wants the agent but wants to decide each rework itself has to turn the
    whole mode off, which also stops the board button they would then be
    relying on.
    """

    def test_the_review_gate_is_read_where_the_webhook_checks_it(self):
        """
        A source check, like the credential-builder one: the gate is three
        lines inside a webhook branch that no unit test reaches without a full
        GitHub payload, and the failure if it is dropped is silent -- reworks
        simply stop arriving.
        """
        import pathlib

        source = (
            pathlib.Path(__file__).resolve().parent.parent
            / "app" / "routers" / "webhooks.py"
        ).read_text(encoding="utf-8")

        assert "item_settings.auto_start_on_review" in source
        # And beside the mode, never instead of it.
        assert 'item_settings.authoring_mode == "autonomous"' in source

    def test_the_qa_gate_is_read_where_the_reply_path_checks_it(self):
        import pathlib

        source = (
            pathlib.Path(__file__).resolve().parent.parent
            / "app" / "services" / "pipeline" / "qa_feedback.py"
        ).read_text(encoding="utf-8")

        assert "settings.auto_start_on_qa" in source
        assert 'settings.authoring_mode != "autonomous"' in source


class TestEveryTriggerReachesTheDriverTheSameWay:
    """
    The rule this feature had to preserve. It exists because the webhook path
    was fixed to continue an open pull request while the board path was not,
    so the same click meant different things depending on which arm ran. A
    third trigger copying the orchestration would reintroduce that.
    """

    def test_the_board_endpoint_does_not_build_its_own_request(self):
        import pathlib

        source = (
            pathlib.Path(__file__).resolve().parent.parent
            / "app" / "routers" / "tasks.py"
        ).read_text(encoding="utf-8")

        assert "authoring_flow.start_for_card(" in source
        assert "authoring.AuthoringRequest(" not in source, (
            "The board endpoint builds its own request again; it must go "
            "through authoring_flow.start_for_card like every other trigger."
        )

    def test_the_sweep_does_not_build_its_own_request(self):
        import pathlib

        source = (
            pathlib.Path(__file__).resolve().parent.parent
            / "app" / "services" / "authoring" / "assignment_watch.py"
        ).read_text(encoding="utf-8")

        assert "authoring_flow.start_for_card(" in source
        assert "AuthoringRequest(" not in source

    def test_the_sweep_never_creates_a_report_document(self):
        """
        `report_sync.ensure_for_ticket` is a write. A sweep that called it
        would open a Google Doc for every assigned item at once -- the exact
        mistake that function avoids by never running from the board listing.
        """
        import pathlib

        source = (
            pathlib.Path(__file__).resolve().parent.parent
            / "app" / "services" / "authoring" / "assignment_watch.py"
        ).read_text(encoding="utf-8")

        # A call, not a mention: the module's own comment explains at length
        # why it does not make one, and that comment is the documentation this
        # test protects.
        assert "ensure_for_ticket(" not in source
        assert "doc_url_hook=None" in source


class TestTheSettingsRoundTripThroughTheAPI:
    """
    Saved, then read back. A setting that stores but reads back wrong looks
    exactly like one that never saved -- which is the failure mode this whole
    area keeps producing, and the reason the resolver has a single home.
    """

    @pytest.fixture
    def client(self, tmp_path, monkeypatch):
        from fastapi.testclient import TestClient
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from app import main
        from app.core.database import Base, get_db
        from app.core.dependencies import get_current_user

        engine = create_engine(
            f"sqlite:///{tmp_path}/api.db",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)
        session = Session()
        user = models.User(id=1, email="a@b.test", hashed_password="x")
        session.add(user)
        session.commit()

        main.app.dependency_overrides[get_db] = lambda: session
        main.app.dependency_overrides[get_current_user] = lambda: user
        with TestClient(main.app) as c:
            yield c
        main.app.dependency_overrides.clear()
        session.close()

    def test_an_untouched_account_reads_back_the_documented_defaults(
        self, client
    ):
        body = client.get("/webhooks/defaults").json()

        assert body["auto_start_on_review"] is True
        assert body["auto_start_on_qa"] is True
        assert body["auto_start_on_assignment"] is False

    def test_each_toggle_saves_and_reads_back(self, client):
        saved = client.get("/webhooks/defaults").json()
        saved.update(
            auto_start_on_assignment=True,
            auto_start_on_review=False,
            auto_start_on_qa=True,
        )

        put = client.put("/webhooks/defaults", json=saved)
        assert put.status_code == 200

        body = client.get("/webhooks/defaults").json()
        assert body["auto_start_on_assignment"] is True
        assert body["auto_start_on_review"] is False
        assert body["auto_start_on_qa"] is True

    def test_turning_one_off_does_not_disturb_the_others(self, client):
        """
        Three booleans written by one form. Storing them as a single bitmask
        or forgetting one in `_apply_auto_start` reads as the form losing a
        checkbox, which is indistinguishable from the save failing.
        """
        saved = client.get("/webhooks/defaults").json()
        saved["auto_start_on_qa"] = False
        client.put("/webhooks/defaults", json=saved)

        body = client.get("/webhooks/defaults").json()
        assert body["auto_start_on_qa"] is False
        assert body["auto_start_on_review"] is True
        assert body["auto_start_on_assignment"] is False
