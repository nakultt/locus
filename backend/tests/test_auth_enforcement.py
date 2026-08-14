"""
Authentication and per-user isolation.

Every user-scoped route derives its user from the verified JWT. Before this,
routes trusted a client-supplied `user_id`, so changing an integer read or
modified any account -- including changing another user's password.
"""

import asyncio
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_client(tmp_path):
    from cryptography.fernet import Fernet
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import main
    from app.database import Base, get_db

    engine = create_engine(
        f"sqlite:///{tmp_path}/auth.db", connect_args={"check_same_thread": False}
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
    Fernet.generate_key()  # ensure cryptography is importable in this context

    with TestClient(main.app) as c:
        yield c

    main.app.dependency_overrides.clear()


def register(client: TestClient, email: str) -> dict:
    user = client.post(
        "/auth/signup", json={"email": email, "password": "secret123"}
    ).json()
    return {"Authorization": f"Bearer {user['token']}"}


class TestUnauthenticatedAccess:
    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("GET", "/auth/integrations"),
            ("GET", "/auth/me"),
            ("PUT", "/auth/user"),
            ("GET", "/api/conversations"),
            ("POST", "/api/conversations"),
            ("GET", "/webhooks/summary"),
            ("GET", "/webhooks/repos"),
            ("GET", "/webhooks/jobs"),
            # The task board reads two third-party accounts on the user's
            # behalf; an unauthenticated caller must never reach it.
            ("GET", "/tasks"),
            ("GET", "/tasks/detail?task_key=ACME-1"),
            ("POST", "/tasks/analyze?task_key=ACME-1"),
        ],
    )
    def test_requires_a_token(self, app_client, method, path):
        response = app_client.request(
            method, path, json={} if method in ("PUT", "POST") else None
        )
        assert response.status_code == 401

    def test_rejects_a_garbage_token(self, app_client):
        response = app_client.get(
            "/auth/me", headers={"Authorization": "Bearer not-a-jwt"}
        )
        assert response.status_code == 401

    def test_public_routes_stay_open(self, app_client):
        assert app_client.get("/health").status_code == 200
        assert app_client.post(
            "/auth/signup", json={"email": "open@x.com", "password": "secret123"}
        ).status_code == 201


class TestCrossUserIsolation:
    def test_one_user_cannot_read_anothers_conversation(self, app_client):
        alice = register(app_client, "alice@x.com")
        bob = register(app_client, "bob@x.com")

        conv = app_client.post(
            "/api/conversations", json={"title": "private"}, headers=alice
        ).json()

        # 404 rather than 403: a 403 would confirm the id exists.
        assert app_client.get(
            f"/api/conversations/{conv['id']}/messages", headers=bob
        ).status_code == 404
        assert app_client.get(
            f"/api/conversations/{conv['id']}/messages", headers=alice
        ).status_code == 200

    def test_one_user_cannot_delete_anothers_conversation(self, app_client):
        alice = register(app_client, "alice2@x.com")
        bob = register(app_client, "bob2@x.com")

        conv = app_client.post(
            "/api/conversations", json={"title": "keep"}, headers=alice
        ).json()

        assert app_client.delete(
            f"/api/conversations/{conv['id']}", headers=bob
        ).status_code == 404
        # Still there for its owner.
        assert app_client.get(
            f"/api/conversations/{conv['id']}/messages", headers=alice
        ).status_code == 200

    def test_integrations_are_listed_per_user(self, app_client):
        alice = register(app_client, "alice3@x.com")
        bob = register(app_client, "bob3@x.com")

        app_client.post(
            "/auth/connect",
            json={"service_name": "github", "api_key": "ghp_alice"},
            headers=alice,
        )

        assert len(app_client.get("/auth/integrations", headers=alice).json()["integrations"]) == 1
        assert len(app_client.get("/auth/integrations", headers=bob).json()["integrations"]) == 0

    def test_profile_update_only_touches_the_caller(self, app_client):
        """
        The account-takeover case: previously PUT /auth/user/{id} let anyone
        set any user's password.
        """
        register(app_client, "victim@x.com")
        attacker = register(app_client, "attacker@x.com")

        app_client.put("/auth/user", json={"password": "hijacked"}, headers=attacker)

        # The victim's original password still works.
        assert app_client.post(
            "/auth/login", json={"email": "victim@x.com", "password": "secret123"}
        ).status_code == 200
        # The attacker changed only their own.
        assert app_client.post(
            "/auth/login", json={"email": "attacker@x.com", "password": "hijacked"}
        ).status_code == 200


class TestCredentialIsolation:
    def test_concurrent_users_do_not_share_credentials(self):
        """
        Service credentials live in a ContextVar, so two agents running at once
        cannot see each other's tokens. With the previous module-level dict,
        whichever task wrote last won for both.
        """
        from app.services.github import _github_config, get_github_tools

        async def act(token: str, delay: float) -> str:
            get_github_tools(token=token)
            # Yield exactly where the old code was overwritten.
            await asyncio.sleep(delay)
            return _github_config.get("token")

        async def both():
            return await asyncio.gather(act("ghp_ALICE", 0.05), act("ghp_BOB", 0.01))

        alice_token, bob_token = asyncio.run(both())
        assert alice_token == "ghp_ALICE"
        assert bob_token == "ghp_BOB"

    def test_unset_credentials_read_as_empty(self):
        from app.services.credential_context import CredentialProxy

        proxy = CredentialProxy("test")
        assert proxy.get("anything") is None
        assert not proxy
        assert "key" not in proxy

    def test_proxy_never_renders_values(self):
        """A leaked repr in a log would defeat encryption at rest."""
        from app.services.credential_context import CredentialProxy

        proxy = CredentialProxy("test")
        proxy.set({"token": "ghp_supersecret"})
        assert "ghp_supersecret" not in repr(proxy)
        assert "token" in repr(proxy)


class TestRequiredSecrets:
    """
    Both keys must be set explicitly. A generated ENCRYPTION_KEY changes on
    every restart and silently makes stored credentials undecryptable; a
    default SECRET_KEY was committed to a public repo, so anyone could mint a
    token for any user.
    """

    def _import_without(self, *missing: str) -> subprocess.CompletedProcess:
        backend = Path(__file__).resolve().parent.parent
        env = {k: v for k, v in os.environ.items() if k not in missing}
        env["PYTHONPATH"] = str(backend)

        # An empty cwd, because load_dotenv() walks up from wherever the
        # process starts and both the repo root and backend/ hold a .env.
        with tempfile.TemporaryDirectory() as empty:
            return subprocess.run(
                [sys.executable, "-c", "import app.security"],
                env=env,
                capture_output=True,
                text=True,
                cwd=empty,
            )

    def test_missing_encryption_key_fails_at_import(self):
        result = self._import_without("ENCRYPTION_KEY", "SECRET_KEY")
        assert result.returncode != 0
        assert "ENCRYPTION_KEY" in result.stderr

    def test_error_says_how_to_generate_one(self):
        result = self._import_without("ENCRYPTION_KEY", "SECRET_KEY")
        assert "Fernet.generate_key" in result.stderr
