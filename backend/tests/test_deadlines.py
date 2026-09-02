"""
Deadline tracking and event constraints.

Deadlines are the boundary the scheduler will not push work past; constraints
override its guess at how movable an event is. Both are per-user, so the tests
check isolation as well as behaviour.
"""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app import main
    from app.core.database import Base, get_db

    engine = create_engine(
        f"sqlite:///{tmp_path}/dl.db", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    main.app.dependency_overrides[get_db] = override

    with TestClient(main.app) as c:
        user = c.post(
            "/auth/signup", json={"email": "d@x.com", "password": "secret123"}
        ).json()
        c.headers["Authorization"] = f"Bearer {user['token']}"
        yield c

    main.app.dependency_overrides.clear()


def future(days: int = 3) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).isoformat()


class TestDeadlines:
    def test_create_and_list(self, client):
        response = client.post("/api/schedule/deadlines", json={
            "key": "LOC-431",
            "title": "Payment webhook timeouts",
            "due_at": future(),
            "estimated_minutes": 120,
            "source": "jira",
        })
        assert response.status_code == 201
        assert response.json()["key"] == "LOC-431"

        listing = client.get("/api/schedule/deadlines").json()
        assert len(listing) == 1
        assert listing[0]["estimated_minutes"] == 120

    def test_reregistering_updates_rather_than_duplicating(self, client):
        """A Jira sync runs repeatedly; it must not pile up rows."""
        for minutes in (60, 180):
            client.post("/api/schedule/deadlines", json={
                "key": "LOC-431",
                "title": "Payment webhook timeouts",
                "due_at": future(),
                "estimated_minutes": minutes,
            })

        listing = client.get("/api/schedule/deadlines").json()
        assert len(listing) == 1
        assert listing[0]["estimated_minutes"] == 180

    def test_listing_is_ordered_by_due_date(self, client):
        client.post("/api/schedule/deadlines", json={
            "key": "LATE", "title": "Later", "due_at": future(10),
        })
        client.post("/api/schedule/deadlines", json={
            "key": "SOON", "title": "Sooner", "due_at": future(1),
        })

        keys = [d["key"] for d in client.get("/api/schedule/deadlines").json()]
        assert keys == ["SOON", "LATE"]

    def test_delete(self, client):
        created = client.post("/api/schedule/deadlines", json={
            "key": "LOC-1", "title": "Thing", "due_at": future(),
        }).json()

        assert client.delete(
            f"/api/schedule/deadlines/{created['id']}"
        ).status_code == 204
        assert client.get("/api/schedule/deadlines").json() == []

    def test_deleting_someone_elses_deadline_is_a_404(self, client):
        from app import main
        from app.core.database import get_db

        created = client.post("/api/schedule/deadlines", json={
            "key": "MINE", "title": "Private", "due_at": future(),
        }).json()

        override = main.app.dependency_overrides[get_db]
        with TestClient(main.app) as other:
            main.app.dependency_overrides[get_db] = override
            signup = other.post(
                "/auth/signup", json={"email": "o@x.com", "password": "secret123"}
            ).json()
            other.headers["Authorization"] = f"Bearer {signup['token']}"

            assert other.delete(
                f"/api/schedule/deadlines/{created['id']}"
            ).status_code == 404
            # Still there for its owner.
            assert len(client.get("/api/schedule/deadlines").json()) == 1

    def test_requires_authentication(self, client):
        assert client.get(
            "/api/schedule/deadlines", headers={"Authorization": "Bearer bad"}
        ).status_code == 401

    def test_rejects_an_absurd_estimate(self, client):
        response = client.post("/api/schedule/deadlines", json={
            "key": "X", "title": "X", "due_at": future(), "estimated_minutes": 99999,
        })
        assert response.status_code == 422


class TestEventConstraints:
    def test_set_and_overwrite(self, client):
        for event_class in ("hard_fixed", "flexible"):
            response = client.post("/api/schedule/constraints", json={
                "event_id": "evt_1", "event_class": event_class,
            })
            assert response.status_code == 204

    def test_rejects_an_unknown_class(self, client):
        response = client.post("/api/schedule/constraints", json={
            "event_id": "evt_1", "event_class": "whenever",
        })
        assert response.status_code == 422

    def test_requires_authentication(self, client):
        assert client.post(
            "/api/schedule/constraints",
            json={"event_id": "e", "event_class": "flexible"},
            headers={"Authorization": "Bearer bad"},
        ).status_code == 401


class TestPlanningWithoutCalendar:
    def test_planning_reports_the_missing_integration(self, client):
        """
        A clear 400 rather than an empty plan: an empty plan reads as "nothing
        to move" when the real problem is that no calendar was read.
        """
        response = client.post("/api/schedule/plan", json={
            "title": "Sync", "start": "tomorrow at 3pm",
        })
        assert response.status_code == 400
        assert "Calendar" in response.json()["detail"]

    def test_unparseable_time_is_rejected_before_any_lookup(self, client):
        response = client.post("/api/schedule/plan", json={
            "title": "Sync", "start": "sometime whenever",
        })
        assert response.status_code == 400
        assert "understand" in response.json()["detail"]
