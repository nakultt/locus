"""
Authentication Router
Endpoints for user signup, login, and integration connection
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import schemas, crud, security
from app.database import get_db

router = APIRouter()


@router.get(
    "/signup",
    summary="Signup endpoint info",
)
async def signup_info() -> dict[str, str]:
    """
    Informational endpoint for browser visits.

    Explains how to use the POST /auth/signup endpoint.
    """
    return {
        "message": "Use POST /auth/signup with JSON body to create a user.",
        "expected_body": {
            "email": "user@example.com",
            "password": "your-password",
            "name": "Your Name",
        },
    }


@router.post(
    "/signup",
    response_model=schemas.UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new user account"
)
async def signup(
    user: schemas.UserCreate,
    db: Session = Depends(get_db)
) -> schemas.UserResponse:
    """
    Create a new user account.
    
    - **email**: Valid email address (must be unique)
    - **password**: Password (minimum 6 characters)
    """
    # Check if user already exists
    existing_user = crud.get_user_by_email(db, user.email)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # Create user
    db_user = crud.create_user(db, user)
    
    # Generate JWT token
    token = security.create_access_token(
        user_id=db_user.id,
        email=db_user.email,
        name=db_user.name
    )
    
    response = schemas.UserResponse.model_validate(db_user)
    response.token = token
    return response


@router.post(
    "/login",
    response_model=schemas.UserResponse,
    summary="Authenticate user"
)
async def login(
    credentials: schemas.UserLogin,
    db: Session = Depends(get_db)
) -> schemas.UserResponse:
    """
    Authenticate user with email and password.
    
    Returns user info on success.
    """
    user = crud.authenticate_user(db, credentials.email, credentials.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )
    
    # Generate JWT token
    token = security.create_access_token(
        user_id=user.id,
        email=user.email,
        name=user.name,
        remember_me=credentials.remember_me
    )
    
    response = schemas.UserResponse.model_validate(user)
    response.token = token
    return response


@router.put(
    "/user/{user_id}",
    response_model=schemas.UserResponse,
    summary="Update user details"
)
async def update_user(
    user_id: int,
    user_update: schemas.UserUpdate,
    db: Session = Depends(get_db)
) -> schemas.UserResponse:
    """
    Update user profile details.
    
    Allows updating name, email, or password.
    """
    # Check if user exists
    user = crud.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
        
    # If email is being changed, check if new email is already taken
    if user_update.email and user_update.email != user.email:
        existing_user = crud.get_user_by_email(db, user_update.email)
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered"
            )
    
    updated_user = crud.update_user(db, user_id, user_update)
    return schemas.UserResponse.model_validate(updated_user)


@router.post(
    "/connect",
    response_model=schemas.IntegrationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Connect a third-party integration"
)
async def connect_integration(
    integration: schemas.IntegrationCreate,
    db: Session = Depends(get_db)
) -> schemas.IntegrationResponse:
    """
    Store encrypted API key/credentials for a third-party service.
    
    Supported services:
    - **jira**: Requires `api_key` (API token) and credentials with `email`, `url`
    - **gmail**: Requires `credentials` with OAuth tokens
    - **calendar**: Requires `credentials` with OAuth tokens
    - **slack**: Requires `api_key` (Bot token)
    - **notion**: Requires `api_key` (Integration token)
    """
    # Validate user exists
    user = crud.get_user_by_id(db, integration.user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Validate service name
    valid_services = {"jira", "gmail", "calendar", "slack", "notion", "bugasura", "github", "docs", "sheets", "slides", "drive", "forms", "meet", "linear"}
    if integration.service_name.lower() not in valid_services:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid service. Must be one of: {', '.join(sorted(valid_services))}"
        )
    
    # Validate credentials provided
    if not integration.api_key and not integration.credentials:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either api_key or credentials must be provided"
        )
    
    # Store integration with encryption
    db_integration = crud.add_integration(
        db=db,
        user_id=integration.user_id,
        service_name=integration.service_name,
        api_key=integration.api_key,
        credentials=integration.credentials
    )
    
    return schemas.IntegrationResponse.model_validate(db_integration)


@router.get(
    "/integrations/{user_id}",
    response_model=schemas.IntegrationList,
    summary="List user's connected integrations"
)
async def list_integrations(
    user_id: int,
    db: Session = Depends(get_db)
) -> schemas.IntegrationList:
    """Get all connected integrations for a user."""
    # Validate user exists
    user = crud.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    integrations = crud.get_user_integrations(db, user_id)
    return schemas.IntegrationList(
        integrations=[
            schemas.IntegrationResponse.model_validate(i) for i in integrations
        ],
        total=len(integrations)
    )


@router.delete(
    "/disconnect/{user_id}/{service_name}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Disconnect an integration"
)
async def disconnect_integration(
    user_id: int,
    service_name: str,
    db: Session = Depends(get_db)
) -> None:
    """Remove a connected integration."""
    success = crud.delete_integration(db, user_id, service_name)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Integration not found"
        )
