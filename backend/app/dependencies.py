"""
Request dependencies.

The single place a request's identity is established. Every user-scoped route
derives its user from the verified JWT here rather than from a client-supplied
`user_id`, which was previously spoofable by changing an integer.
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app import crud, models, security
from app.database import get_db

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
    """
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

        if config:
            configs[integration.service_name] = config

    return configs
