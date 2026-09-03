"""
Authentication Router
Signup, login, profile updates, and integration connection.

Every user-scoped route derives its user from the verified JWT. Routes no
longer accept a `user_id` from the caller, which previously allowed reading or
modifying another account by changing an integer.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import crud, models, schemas
from app.core import rate_limit, security
from app.core.database import get_db
from app.core.dependencies import get_current_user

router = APIRouter()

# Failed sign-ins, throttled.
#
# `/auth/login` accepted unlimited password guesses against any address someone
# knew, at whatever rate they could send them. Ten failures inside fifteen
# minutes is far above anything a person typing their own password reaches and
# far below what guessing needs.
#
# Keyed by **email, not IP**, which is the important decision here. Behind a
# load balancer every request carries the proxy's address, so an IP-keyed
# counter would let one attacker lock out every user of the product at once —
# turning a brute-force defence into a denial-of-service lever. Reading
# `X-Forwarded-For` instead would fix that and hand the attacker a header they
# can set to anything they like. The account being guessed at is the thing
# actually under attack, so that is what is counted.
#
# The residual cost is that someone who knows an address can keep that one
# account throttled by failing on purpose. That is the standard trade for this
# control, it expires on its own, and it is strictly better than the
# alternative of no limit at all.
MAX_FAILED_LOGINS = 10
LOGIN_WINDOW_SECONDS = 15 * 60


def _login_bucket(email: str) -> str:
    # Normalised, or `Alice@x.com` and `alice@x.com` would be ten guesses each
    # against an account that `crud.authenticate_user` treats as one.
    return f"login:{email.strip().lower()}"

# Services the connect endpoint accepts.
VALID_SERVICES = frozenset({
    "jira", "gmail", "calendar", "slack", "notion", "bugasura", "github",
    "docs", "sheets", "slides", "drive", "forms", "meet", "linear",
})


@router.post(
    "/signup",
    response_model=schemas.UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new user account",
)
async def signup(
    user: schemas.UserCreate,
    db: Session = Depends(get_db),
) -> schemas.UserResponse:
    """
    Create a new user account.

    - **email**: Valid email address (must be unique)
    - **password**: Minimum 6 characters
    """
    if crud.get_user_by_email(db, user.email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    db_user = crud.create_user(db, user)

    response = schemas.UserResponse.model_validate(db_user)
    response.token = security.create_access_token(
        user_id=db_user.id, email=db_user.email, name=db_user.name
    )
    return response


@router.post(
    "/login",
    response_model=schemas.UserResponse,
    summary="Authenticate user",
)
async def login(
    credentials: schemas.UserLogin,
    db: Session = Depends(get_db),
) -> schemas.UserResponse:
    """Authenticate with email and password, returning a JWT."""
    bucket = _login_bucket(credentials.email)

    # Checked before the password is verified, so a locked-out attacker cannot
    # keep spending bcrypt work on the server either.
    if rate_limit.count(bucket, LOGIN_WINDOW_SECONDS) >= MAX_FAILED_LOGINS:
        wait = rate_limit.retry_after(bucket, LOGIN_WINDOW_SECONDS)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "Too many failed sign-in attempts for this account. "
                f"Try again in {wait} seconds."
            ),
            headers={"Retry-After": str(wait)},
        )

    user = crud.authenticate_user(db, credentials.email, credentials.password)
    if not user:
        rate_limit.record(bucket, LOGIN_WINDOW_SECONDS)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    # A success clears the history: someone whose password was being guessed at
    # is not left throttled the moment they get in themselves.
    rate_limit.clear(bucket)

    response = schemas.UserResponse.model_validate(user)
    response.token = security.create_access_token(
        user_id=user.id,
        email=user.email,
        name=user.name,
        remember_me=credentials.remember_me,
    )
    return response


@router.get(
    "/me",
    response_model=schemas.UserResponse,
    summary="Current user",
)
async def read_me(
    current_user: models.User = Depends(get_current_user),
) -> schemas.UserResponse:
    """Return the authenticated user. Useful for validating a stored token."""
    return schemas.UserResponse.model_validate(current_user)


@router.put(
    "/user",
    response_model=schemas.UserResponse,
    summary="Update your profile",
)
async def update_user(
    user_update: schemas.UserUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> schemas.UserResponse:
    """
    Update the authenticated user's name, email, or password.

    Only ever updates the caller's own account.
    """
    if user_update.email and user_update.email != current_user.email:
        if crud.get_user_by_email(db, user_update.email):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered",
            )

    updated = crud.update_user(db, current_user.id, user_update)
    return schemas.UserResponse.model_validate(updated)


@router.post(
    "/connect",
    response_model=schemas.IntegrationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Connect a third-party integration",
)
async def connect_integration(
    integration: schemas.IntegrationCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> schemas.IntegrationResponse:
    """
    Store encrypted credentials for a third-party service.

    Supported services:
    - **jira**: `api_key` (API token) plus credentials with `email`, `url`, and
      optionally `default_project_key` (where new issues go by default)
    - **slack**: credentials with `bot_token` and optionally `user_token`
    - **github**, **notion**, **bugasura**, **linear**: `api_key`
    - **gmail**, **calendar**, Google Workspace: OAuth credentials
    """
    if integration.service_name.lower() not in VALID_SERVICES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid service. Must be one of: {', '.join(sorted(VALID_SERVICES))}",
        )

    if not integration.api_key and not integration.credentials:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either api_key or credentials must be provided",
        )

    db_integration = crud.add_integration(
        db=db,
        user_id=current_user.id,
        service_name=integration.service_name,
        api_key=integration.api_key,
        credentials=integration.credentials,
    )
    return schemas.IntegrationResponse.model_validate(db_integration)


@router.get(
    "/integrations",
    response_model=schemas.IntegrationList,
    summary="List your connected integrations",
)
async def list_integrations(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> schemas.IntegrationList:
    """List the authenticated user's connected integrations."""
    integrations = crud.get_user_integrations(db, current_user.id)
    return schemas.IntegrationList(
        integrations=[
            schemas.IntegrationResponse.model_validate(i) for i in integrations
        ],
        total=len(integrations),
    )


@router.delete(
    "/disconnect/{service_name}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Disconnect an integration",
)
async def disconnect_integration(
    service_name: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Remove one of the authenticated user's integrations."""
    if not crud.delete_integration(db, current_user.id, service_name):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Integration not found",
        )
