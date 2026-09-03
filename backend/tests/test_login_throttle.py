"""
Failed sign-ins are throttled; successful ones are not.

`/auth/login` accepted unlimited password guesses against any address someone
knew. These pin the shape of the fix, because each rule in it exists to avoid a
specific worse failure:

- only *failures* count, so ordinary use never trips it;
- a success clears the history, so the real owner getting in un-throttles them;
- the key is the email rather than the caller's address, so one attacker cannot
  lock out every user of a deployment that sits behind a load balancer.
"""

import pytest
from fastapi.testclient import TestClient

from app.core import rate_limit
from app.routers.auth import LOGIN_WINDOW_SECONDS, MAX_FAILED_LOGINS, _login_bucket

PASSWORD = "correct-horse-battery"


@pytest.fixture
def client(tmp_path):
    """
    A client over a database of this test's own.

    Same shape as `test_auth_enforcement.py`: the app's own engine is replaced
    so the suite never writes to a developer's real database, and `with
    TestClient(...)` is what runs the lifespan that creates the tables.

    The failure counter is process-wide module state, so it is cleared around
    every test — otherwise one test's leftover failures fail the next one for
    reasons that have nothing to do with it.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app import main
    from app.core.database import Base, get_db

    engine = create_engine(
        f"sqlite:///{tmp_path}/throttle.db",
        connect_args={"check_same_thread": False},
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
    rate_limit.clear()

    with TestClient(main.app) as c:
        yield c

    rate_limit.clear()
    main.app.dependency_overrides.clear()


def _signup(client: TestClient, email: str) -> None:
    response = client.post(
        "/auth/signup", json={"email": email, "password": PASSWORD}
    )
    assert response.status_code == 201, response.text


def _login(client: TestClient, email: str, password: str):
    return client.post(
        "/auth/login", json={"email": email, "password": password}
    )


def test_repeated_failures_are_eventually_refused(client):
    email = "throttle-target@example.com"
    _signup(client, email)

    for attempt in range(MAX_FAILED_LOGINS):
        assert _login(client, email, "wrong").status_code == 401, (
            f"attempt {attempt} should still be answered as a bad password"
        )

    refused = _login(client, email, "wrong")
    assert refused.status_code == 429
    # A caller told to back off has to be told for how long, or the only
    # workable strategy left is to keep retrying.
    assert int(refused.headers["Retry-After"]) > 0


def test_the_real_password_is_refused_too_once_throttled(client):
    """
    The throttle is not a password check with extra steps.

    Answering a *correct* password normally while refusing wrong ones would
    turn the endpoint into an oracle: an attacker who hits the limit learns
    they were wrong, and the one response that differs tells them when they
    are right.
    """
    email = "throttle-oracle@example.com"
    _signup(client, email)

    for _ in range(MAX_FAILED_LOGINS):
        assert _login(client, email, "wrong").status_code == 401

    assert _login(client, email, PASSWORD).status_code == 429


def test_a_success_clears_the_history(client):
    email = "throttle-recovers@example.com"
    _signup(client, email)

    for _ in range(MAX_FAILED_LOGINS - 1):
        assert _login(client, email, "wrong").status_code == 401

    assert _login(client, email, PASSWORD).status_code == 200

    # Back to a full budget: the mistyped attempts before a successful sign-in
    # must not count against the next session.
    for _ in range(MAX_FAILED_LOGINS):
        assert _login(client, email, "wrong").status_code == 401


def test_one_account_being_guessed_does_not_lock_out_another(client):
    """
    The reason the key is the email and not the caller's address.

    Behind a load balancer every request arrives from the proxy, so an
    IP-keyed counter would let one attacker take the whole product's sign-in
    down by failing repeatedly against a single throwaway address.
    """
    victim = "throttle-bystander@example.com"
    target = "throttle-attacked@example.com"
    _signup(client, victim)
    _signup(client, target)

    for _ in range(MAX_FAILED_LOGINS + 5):
        _login(client, target, "wrong")

    assert _login(client, target, PASSWORD).status_code == 429
    assert _login(client, victim, PASSWORD).status_code == 200


def test_case_and_padding_do_not_buy_a_fresh_budget(client):
    """
    `crud.authenticate_user` treats these as one account, so the throttle must
    too — otherwise every capitalisation is another ten free guesses.
    """
    email = "throttle-case@example.com"
    _signup(client, email)

    for _ in range(MAX_FAILED_LOGINS):
        assert _login(client, email, "wrong").status_code == 401

    assert _login(client, "  Throttle-Case@Example.COM  ", "wrong").status_code == 429


def test_signing_up_does_not_consume_the_login_budget(client):
    email = "throttle-fresh@example.com"
    _signup(client, email)
    assert rate_limit.count(_login_bucket(email), LOGIN_WINDOW_SECONDS) == 0
    assert _login(client, email, PASSWORD).status_code == 200
