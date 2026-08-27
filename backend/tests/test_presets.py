"""
Presets: a template applied at write time, never a stored authority.

The rule this file guards: `resolve_settings` stays the sole arbiter of what a
run does. A preset expanded at read time would add a second resolution layer
above it, and the worker, the API and the UI preview would be one refactor
away from disagreeing about what a run will do -- which is the exact drift
`agent_settings` was written to prevent.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.services import presets


class TestContents:
    def test_no_preset_enables_auto_merge(self):
        """
        A preset must never be the thing that enables the only path writing to
        a default branch with no human in the loop. Picking "Autonomous"
        because you want the agent to write code is not saying "and land it
        unread".
        """
        for preset in presets.PRESETS.values():
            assert preset["values"]["auto_merge_on_approval"] is False

    def test_both_modes_exist_and_name_themselves(self):
        assert presets.PRESETS["assisted"]["values"]["authoring_mode"] == "assisted"
        assert presets.PRESETS["autonomous"]["values"]["authoring_mode"] == "autonomous"

    def test_the_autonomous_description_says_the_brief_leaves_the_machine(self):
        """
        The one claim a user must not have to find in a changelog. Every model
        that reads your code automatically runs locally; this one does not.
        """
        text = presets.PRESETS["autonomous"]["description"].lower()
        assert "remote" in text and "leaves the machine" in text

    def test_an_unknown_name_is_none_rather_than_an_error(self):
        assert presets.get("wildly-autonomous") is None
        assert presets.get("") is None


class TestMatches:
    def test_saved_values_matching_the_preset(self):
        assert presets.matches("assisted", {
            "authoring_mode": "assisted",
            "autonomous_max_rounds": 2,
            "auto_merge_on_approval": False,
            "project_board_sync": True,
        })

    def test_a_changed_dial_no_longer_matches(self):
        assert not presets.matches("assisted", {
            "authoring_mode": "assisted",
            "autonomous_max_rounds": 5,
            "auto_merge_on_approval": False,
            "project_board_sync": True,
        })

    def test_settings_the_preset_says_nothing_about_do_not_break_the_match(self):
        """
        A preset says nothing about a Slack channel, so a repo that set one has
        not modified the preset. Without this every repo that filled in
        anything at all would render as "(modified)".
        """
        assert presets.matches("autonomous", {
            "authoring_mode": "autonomous",
            "autonomous_max_rounds": 2,
            "auto_merge_on_approval": False,
            "project_board_sync": True,
            "slack_channel": "#web",
            "qa_emails": ["qa@example.com"],
        })

    def test_an_unknown_preset_never_matches(self):
        assert not presets.matches("sentient", {"authoring_mode": "assisted"})


@pytest.fixture
def client(tmp_path):
    import main
    from app.database import Base, get_db

    engine = create_engine(
        f"sqlite:///{tmp_path}/p.db", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    main.app.dependency_overrides[get_db] = override
    with TestClient(main.app) as c:
        signup = c.post(
            "/auth/signup", json={"email": "p@x.com", "password": "secret123"}
        ).json()
        c.headers["Authorization"] = f"Bearer {signup['token']}"
        yield c
    main.app.dependency_overrides.clear()


class TestApi:
    def test_serves_the_same_dict_the_service_holds(self, client):
        """One source, so the API and the UI cannot disagree."""
        body = client.get("/webhooks/presets").json()

        served = {p["name"]: p["values"] for p in body["presets"]}
        assert served == {
            name: preset["values"] for name, preset in presets.PRESETS.items()
        }

    def test_requires_authentication(self, client):
        assert client.get(
            "/webhooks/presets", headers={"Authorization": "Bearer bad"}
        ).status_code == 401

    def test_picking_a_preset_stores_only_a_label(self, client):
        """
        `preset_label` is display only. What a run does comes from the dials
        the preset copied into the form, which the user can still change.
        """
        client.put("/webhooks/defaults", json={
            "authoring_mode": "autonomous",
            "autonomous_max_rounds": 2,
            "preset_label": "autonomous",
        })

        body = client.get("/webhooks/defaults").json()
        assert body["preset_label"] == "autonomous"
        assert body["authoring_mode"] == "autonomous"
        # The label did not enable auto-merge, and could not have.
        assert body["auto_merge_on_approval"] is False
