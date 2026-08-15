"""
Refreshing Google access tokens.

A Google access token lives an hour; the refresh token beside it lives until
someone revokes it. Every background loop here runs indefinitely, so by the
time an analysis exports a report or a poller checks for replies, the stored
access token is almost always dead -- an hour after the user connected the
integration, everything downstream fails with a 401 that reads exactly like a
broken integration.

This is the one async refresh path. The per-tool modules (`google_docs`,
`gmail`, `calendar`) carry their own synchronous copies bound to their module
singletons; those serve the agent's tool calls, where the config is rebound
per request. Nothing outside a tool body should grow a fourth copy.

The refreshed token is written back to the database, not only to the config
dict. A refresh that lives in memory is spent on one call and the next loop
iteration starts expired again -- which is the same failure, just slower.
"""

import logging
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy.orm import Session

from app import crud

logger = logging.getLogger(__name__)

TOKEN_URL = "https://oauth2.googleapis.com/token"

# Refresh this long before nominal expiry. A token that expires mid-request is
# a 401 on a call that looked fine when it started.
EXPIRY_MARGIN_SECONDS = 120


def is_expired(credentials: dict) -> bool:
    """
    Whether a stored token needs refreshing.

    Unknown ages count as expired: a credential with no `obtained_at` predates
    the field, and treating it as fresh means a guaranteed 401 rather than a
    cheap refresh.
    """
    obtained_at = credentials.get("obtained_at")
    if not obtained_at:
        return True

    try:
        stamp = datetime.fromisoformat(obtained_at)
    except (TypeError, ValueError):
        return True

    # Stored naive by an older writer; these are UTC instants either way.
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)

    lifetime = int(credentials.get("expires_in", 3600))
    return datetime.now(UTC) >= stamp + timedelta(
        seconds=lifetime - EXPIRY_MARGIN_SECONDS
    )


async def valid_access_token(
    config: dict,
    *,
    db: Session | None = None,
    user_id: int | None = None,
    service: str | None = None,
) -> str | None:
    """
    Return a usable access token for a Google integration, refreshing if needed.

    Args:
        config: An integration config as built by `get_integration_configs` --
            `credentials` plus the OAuth `client_id`/`client_secret`.
        db, user_id, service: Supplied together to persist the refreshed token.
            Omitted, the refresh still works for this call but is forgotten,
            so the next caller refreshes again.

    Returns:
        A token, or None when there is nothing usable and no way to get one.
        Callers treat None as "not connected" rather than raising, since a
        dead Google integration must not take down the run around it.
    """
    credentials = config.get("credentials") or {}
    token = credentials.get("access_token")

    if token and not is_expired(credentials):
        return token

    refresh_token = credentials.get("refresh_token")
    client_id = config.get("client_id")
    client_secret = config.get("client_secret")

    if not (refresh_token and client_id and client_secret):
        # Nothing to refresh with. An unexpired token is still worth returning;
        # a missing client id is a configuration gap, not a reason to fail a
        # call that might still succeed.
        return token

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                TOKEN_URL,
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )
    except Exception as e:
        logger.warning("Google token refresh failed: %s", e)
        return token

    if response.status_code != 200:
        # A revoked or expired refresh token lands here. The user has to
        # reconnect; nothing this code can do recovers it.
        logger.warning(
            "Google token refresh rejected (%s): %s",
            response.status_code, response.text[:200],
        )
        return None

    payload = response.json()
    new_token = payload.get("access_token")
    if not new_token:
        return None

    # Google does not return the refresh token on a refresh, so the stored one
    # is carried forward. Dropping it would turn an hourly refresh into a
    # one-time one.
    credentials["access_token"] = new_token
    credentials["expires_in"] = payload.get("expires_in", 3600)
    credentials["obtained_at"] = datetime.now(UTC).isoformat()
    config["credentials"] = credentials

    if db is not None and user_id is not None and service:
        try:
            integration = crud.get_integration(db, user_id, service)
            if integration is not None:
                crud.update_integration_credentials(
                    db, integration.id, credentials
                )
        except Exception as e:
            # The token is good for this call either way; failing the work
            # because the record could not be written would be worse.
            logger.warning("Could not persist refreshed %s token: %s", service, e)

    return new_token
