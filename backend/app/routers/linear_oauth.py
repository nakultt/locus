"""
Linear OAuth Router
Handles OAuth 2.0 authentication flow for Linear
"""

import os
import secrets
from datetime import datetime, timedelta
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, status, Depends, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
import httpx

from app.database import get_db
from app import crud

router = APIRouter()

# Linear OAuth Configuration
LINEAR_CLIENT_ID = os.getenv("LINEAR_CLIENT_ID", "")
LINEAR_CLIENT_SECRET = os.getenv("LINEAR_CLIENT_SECRET", "")
LINEAR_REDIRECT_URI = os.getenv("LINEAR_REDIRECT_URI", "http://localhost:8000/auth/linear/callback")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")

# OAuth URLs
LINEAR_AUTH_URL = "https://linear.app/oauth/authorize"
LINEAR_TOKEN_URL = "https://api.linear.app/oauth/token"

# Scopes for Linear
# Available: read, write, issues:create, comments:create, admin
LINEAR_SCOPES = ["read", "write", "issues:create", "comments:create"]

# In-memory state storage (in production, use Redis or database)
_oauth_states: dict[str, dict] = {}


@router.get(
    "/linear",
    summary="Initiate Linear OAuth flow"
)
async def linear_oauth_start(
    user_id: int = Query(..., description="User ID to associate with the OAuth"),
):
    """
    Start the Linear OAuth flow.
    
    Redirects the user to Linear's OAuth consent screen.
    After consent, Linear redirects back to /auth/linear/callback
    """
    if not LINEAR_CLIENT_ID or not LINEAR_CLIENT_SECRET:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Linear OAuth not configured. Please set LINEAR_CLIENT_ID and LINEAR_CLIENT_SECRET."
        )
    
    # Generate state token for CSRF protection
    state = secrets.token_urlsafe(32)
    
    # Store state with user info (expires in 10 minutes)
    _oauth_states[state] = {
        "user_id": user_id,
        "created_at": datetime.utcnow().isoformat()
    }
    
    # Build OAuth URL
    params = {
        "client_id": LINEAR_CLIENT_ID,
        "redirect_uri": LINEAR_REDIRECT_URI,
        "response_type": "code",
        "scope": ",".join(LINEAR_SCOPES),  # Linear uses comma-separated scopes
        "state": state,
        "actor": "user",  # Resources created as the user
    }
    
    auth_url = f"{LINEAR_AUTH_URL}?{urlencode(params)}"
    
    return RedirectResponse(url=auth_url)


@router.get(
    "/linear/callback",
    summary="Handle Linear OAuth callback"
)
async def linear_oauth_callback(
    code: str = Query(None, description="Authorization code from Linear"),
    state: str = Query(None, description="State token for CSRF validation"),
    error: str = Query(None, description="Error from Linear"),
    db: Session = Depends(get_db)
):
    """
    Handle the OAuth callback from Linear.
    
    Exchanges the authorization code for access/refresh tokens
    and stores them in the database.
    """
    # Handle errors from Linear
    if error:
        return RedirectResponse(
            url=f"{FRONTEND_URL}/integrations/integrations-page?error={error}"
        )
    
    if not code or not state:
        return RedirectResponse(
            url=f"{FRONTEND_URL}/integrations/integrations-page?error=missing_params"
        )
    
    # Validate state
    if state not in _oauth_states:
        return RedirectResponse(
            url=f"{FRONTEND_URL}/integrations/integrations-page?error=invalid_state"
        )
    
    state_data = _oauth_states.pop(state)
    user_id = state_data["user_id"]
    
    # Check if state is expired (10 minutes)
    created_at = datetime.fromisoformat(state_data["created_at"])
    if datetime.utcnow() - created_at > timedelta(minutes=10):
        return RedirectResponse(
            url=f"{FRONTEND_URL}/integrations/integrations-page?error=state_expired"
        )
    
    # Exchange code for tokens
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                LINEAR_TOKEN_URL,
                data={
                    "client_id": LINEAR_CLIENT_ID,
                    "client_secret": LINEAR_CLIENT_SECRET,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": LINEAR_REDIRECT_URI,
                },
                headers={
                    "Content-Type": "application/x-www-form-urlencoded"
                }
            )
            
            if response.status_code != 200:
                error_detail = response.json().get("error_description", "Token exchange failed")
                return RedirectResponse(
                    url=f"{FRONTEND_URL}/integrations/integrations-page?error={error_detail}"
                )
            
            tokens = response.json()
            
    except Exception as e:
        print(f"Linear OAuth error: {e}")
        return RedirectResponse(
            url=f"{FRONTEND_URL}/integrations/integrations-page?error=token_exchange_failed"
        )
    
    # Store tokens as credentials
    credentials = {
        "access_token": tokens.get("access_token"),
        "token_type": tokens.get("token_type", "Bearer"),
        "scope": tokens.get("scope"),
        "expires_in": tokens.get("expires_in"),
        "obtained_at": datetime.utcnow().isoformat(),
    }
    
    # Verify user exists
    user = crud.get_user_by_id(db, user_id)
    if not user:
        return RedirectResponse(
            url=f"{FRONTEND_URL}/integrations/integrations-page?error=user_not_found"
        )
    
    # Store Linear integration
    try:
        # Check if integration already exists
        existing = crud.get_user_integration(db, user_id, "linear")
        if existing:
            # Update existing integration
            crud.update_integration_credentials(db, existing.id, credentials)
        else:
            # Create new integration
            crud.add_integration(
                db=db,
                user_id=user_id,
                service_name="linear",
                api_key=tokens.get("access_token"),  # Store access token as api_key for tool usage
                credentials=credentials
            )
    except Exception as e:
        print(f"Error storing Linear integration: {e}")
        return RedirectResponse(
            url=f"{FRONTEND_URL}/integrations/integrations-page?error=storage_failed"
        )
    
    # Redirect back to frontend with success
    return RedirectResponse(
        url=f"{FRONTEND_URL}/integrations/integrations-page?success=linear_connected&service=linear"
    )


async def refresh_linear_token(refresh_token: str) -> dict | None:
    """
    Refresh an expired Linear access token.
    
    Note: Linear tokens typically don't expire quickly, but this is here for future use.
    """
    # Linear OAuth tokens are long-lived, refresh may not be commonly needed
    # Implement if Linear provides refresh token functionality
    return None
