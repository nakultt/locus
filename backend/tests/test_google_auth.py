"""
Refreshing Google access tokens.

A Google access token lives an hour and every loop here runs indefinitely, so
reading the stored token directly worked for exactly one hour after the user
connected the integration and failed with a 401 forever after. That failure is
indistinguishable from the integration being broken, which is why the Docs
export reported "no document returned" and QA emails silently stopped.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.services.integrations import google_auth


def _creds(*, age_seconds: int = 0, lifetime: int = 3600, refresh="r"):
    obtained = datetime.now(UTC) - timedelta(seconds=age_seconds)
    creds = {
        "access_token": "stored-token",
        "expires_in": lifetime,
        "obtained_at": obtained.isoformat(),
    }
    if refresh:
        creds["refresh_token"] = refresh
    return creds


def _config(**kw):
    return {
        "credentials": _creds(**kw),
        "client_id": "cid",
        "client_secret": "secret",
    }


class TestExpiry:
    def test_a_fresh_token_is_not_expired(self):
        assert google_auth.is_expired(_creds(age_seconds=10)) is False

    def test_an_old_token_is_expired(self):
        assert google_auth.is_expired(_creds(age_seconds=7200)) is True

    def test_it_expires_early_by_the_margin(self):
        """
        A token expiring mid-request is a 401 on a call that looked fine when
        it started, so the margin is deliberate.
        """
        almost = 3600 - google_auth.EXPIRY_MARGIN_SECONDS + 5
        assert google_auth.is_expired(_creds(age_seconds=almost)) is True

    def test_an_unknown_age_counts_as_expired(self):
        """
        A credential with no obtained_at predates the field. Treating it as
        fresh guarantees a 401; treating it as stale costs one refresh.
        """
        assert google_auth.is_expired({"access_token": "t"}) is True

    def test_an_unparseable_stamp_counts_as_expired(self):
        assert google_auth.is_expired(
            {"access_token": "t", "obtained_at": "not a date"}
        ) is True


class TestRefresh:
    @pytest.mark.asyncio
    async def test_a_valid_token_is_returned_without_a_refresh(self, monkeypatch):
        def _boom(*a, **kw):
            raise AssertionError("should not have called Google")

        monkeypatch.setattr(google_auth.httpx, "AsyncClient", _boom)

        token = await google_auth.valid_access_token(_config(age_seconds=5))

        assert token == "stored-token"

    @pytest.mark.asyncio
    async def test_an_expired_token_is_refreshed(self, monkeypatch):
        class _Response:
            status_code = 200

            @staticmethod
            def json():
                return {"access_token": "fresh-token", "expires_in": 3599}

        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, *a, **kw):
                return _Response()

        monkeypatch.setattr(google_auth.httpx, "AsyncClient", lambda **kw: _Client())

        config = _config(age_seconds=7200)
        token = await google_auth.valid_access_token(config)

        assert token == "fresh-token"
        # Written back onto the config, so the rest of this run reuses it.
        assert config["credentials"]["access_token"] == "fresh-token"

    @pytest.mark.asyncio
    async def test_the_refresh_token_is_kept(self, monkeypatch):
        """
        Google does not return the refresh token on a refresh. Dropping it
        would turn an hourly refresh into a one-time one.
        """
        class _Response:
            status_code = 200

            @staticmethod
            def json():
                return {"access_token": "fresh", "expires_in": 3599}

        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, *a, **kw):
                return _Response()

        monkeypatch.setattr(google_auth.httpx, "AsyncClient", lambda **kw: _Client())

        config = _config(age_seconds=7200)
        await google_auth.valid_access_token(config)

        assert config["credentials"]["refresh_token"] == "r"

    @pytest.mark.asyncio
    async def test_a_rejected_refresh_returns_nothing(self, monkeypatch):
        """
        A revoked refresh token cannot be recovered here. Returning the dead
        access token would just move the 401 one call later.
        """
        class _Response:
            status_code = 400
            text = "invalid_grant"

        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, *a, **kw):
                return _Response()

        monkeypatch.setattr(google_auth.httpx, "AsyncClient", lambda **kw: _Client())

        token = await google_auth.valid_access_token(_config(age_seconds=7200))

        assert token is None

    @pytest.mark.asyncio
    async def test_missing_client_credentials_do_not_crash(self):
        """
        The OAuth client id is environment configuration. Absent, an unexpired
        token is still worth returning rather than failing the call around it.
        """
        config = {"credentials": _creds(age_seconds=5)}

        assert await google_auth.valid_access_token(config) == "stored-token"

    @pytest.mark.asyncio
    async def test_a_network_error_falls_back_to_the_stored_token(
        self, monkeypatch
    ):
        def _boom(**kw):
            raise RuntimeError("network down")

        monkeypatch.setattr(google_auth.httpx, "AsyncClient", _boom)

        token = await google_auth.valid_access_token(_config(age_seconds=7200))

        # Probably dead, but the caller reports a real API error rather than
        # a confusing "not connected".
        assert token == "stored-token"
