"""
Authentication Router
Signup, login, profile updates, and integration connection.

Every user-scoped route derives its user from the verified JWT. Routes no
longer accept a `user_id` from the caller, which previously allowed reading or
modifying another account by changing an integer.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import crud, models, schemas, security
from app.database import get_db
from app.dependencies import get_current_user

router = APIRouter()

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
    user = crud.authenticate_user(db, credentials.email, credentials.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

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
    - **jira**: `api_key` (API token) plus credentials with `email` and `url`
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
