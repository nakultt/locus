"""
Request dependencies.

The single place a request's identity is established. Every user-scoped route
derives its user from the verified JWT here rather than from a client-supplied
`user_id`, which was previously spoofable by changing an integer.
"""

import os

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app import crud, models
from app.core import security
from app.core.database import get_db
from app.services.authoring import agent_runtime
from app.services.chat import llm_config

# Services authenticated through the shared Google OAuth app. Their stored
# access tokens expire hourly and are refreshed with the client credentials.
GOOGLE_SERVICES = {
    "gmail", "calendar", "docs", "sheets", "slides", "drive", "forms", "meet",
}

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")

# auto_error=False so a missing header produces our 401 rather than FastAPI's
# generic one, keeping the message consistent with an invalid token.
_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> models.User:
    """
    Resolve the authenticated user from the Authorization header.

    Raises:
        HTTPException 401 if the token is missing, invalid, expired, or names
        a user that no longer exists.
    """
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = security.verify_token(credentials.credentials)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    subject = payload.get("sub")
    try:
        user_id = int(subject)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None

    user = crud.get_user_by_id(db, user_id)
    if not user:
        # The token is well-formed but the account is gone.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer exists",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


def get_integration_configs(
    db: Session, user_id: int
) -> dict[str, dict]:
    """
    Load and decrypt a user's integration credentials.

    Shared by the chat router and the background worker so both see the same
    credential shape.

    This is also where the user's model backend and agent runtime are bound,
    and deliberately so.
    `get_llm()` is called from thirteen places, none of which takes a user --
    the security scanner and the chat agent both just ask for a model. Every
    path that reaches one already comes through here to build its credentials,
    so binding here means no caller can be missed; missing one would silently
    run that path on the deployment default rather than the settings the user
    entered, which looks like the setting not having saved.
    """
    llm_config.bind_for_user(db, user_id)
    agent_runtime.bind_for_user(db, user_id)

    configs: dict[str, dict] = {}

    for integration in crud.get_user_integrations(db, user_id):
        config: dict = {}

        api_key = crud.get_integration_key(db, user_id, integration.service_name)
        if api_key:
            config["api_key"] = api_key

        credentials = crud.get_integration_credentials(
            db, user_id, integration.service_name
        )
        if credentials:
            config["credentials"] = credentials

            # A Google access token lives an hour; a refresh token lives until
            # revoked. Refreshing needs the OAuth client credentials, which are
            # environment configuration rather than per-user data, so they are
            # attached here -- the one place every caller builds a config.
            # Without them a background loop running more than an hour after
            # the user last connected fails with a 401 it cannot recover from,
            # which is indistinguishable from the integration being broken.
            if (
                integration.service_name in GOOGLE_SERVICES
                and credentials.get("refresh_token")
                and GOOGLE_CLIENT_ID
                and GOOGLE_CLIENT_SECRET
            ):
                config["client_id"] = GOOGLE_CLIENT_ID
                config["client_secret"] = GOOGLE_CLIENT_SECRET

        if config:
            configs[integration.service_name] = config

    return configs
