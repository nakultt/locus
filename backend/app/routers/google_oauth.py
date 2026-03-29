"""
Google OAuth Router
Handles OAuth 2.0 authentication flow for Gmail and Google Calendar
"""

import os
import json
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

# Google OAuth Configuration
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/google/callback")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")

# OAuth URLs
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

# Scopes for Gmail and Calendar
SCOPES = {
    "gmail": [
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.modify",
    ],
    "calendar": [
        "https://www.googleapis.com/auth/calendar",
        "https://www.googleapis.com/auth/calendar.events",
    ],
    "docs": [
        "https://www.googleapis.com/auth/documents",
    ],
    "sheets": [
        "https://www.googleapis.com/auth/spreadsheets",
    ],
    "slides": [
        "https://www.googleapis.com/auth/presentations",
    ],
    "drive": [
        "https://www.googleapis.com/auth/drive",
    ],
    "forms": [
        "https://www.googleapis.com/auth/forms.body",
    ],
    "meet": [
        "https://www.googleapis.com/auth/calendar.events",
    ],
}

# In-memory state storage (in production, use Redis or database)
_oauth_states: dict[str, dict] = {}


def get_all_google_scopes() -> list[str]:
    """Get all Google scopes for both Gmail and Calendar."""
    all_scopes = []
    for service_scopes in SCOPES.values():
        all_scopes.extend(service_scopes)
    # Add basic profile scope
    all_scopes.append("openid")
    all_scopes.append("https://www.googleapis.com/auth/userinfo.email")
    return list(set(all_scopes))


@router.get(
    "/google",
    summary="Initiate Google OAuth flow"
)
async def google_oauth_start(
    user_id: int = Query(..., description="User ID to associate with the OAuth"),
    service: str = Query("gmail", description="Service to connect: gmail or calendar")
):
    """
    Start the Google OAuth flow.
    
    Redirects the user to Google's OAuth consent screen.
    After consent, Google redirects back to /auth/google/callback
    """
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Google OAuth not configured. Please set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET."
        )
    
    # Validate service
    valid_services = ["gmail", "calendar", "docs", "sheets", "slides", "drive", "forms", "meet", "google"]
    if service not in valid_services:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Service must be one of: {', '.join(valid_services)}"
        )
    
    # Generate state token for CSRF protection
    state = secrets.token_urlsafe(32)
    
    # Store state with user info (expires in 10 minutes)
    _oauth_states[state] = {
        "user_id": user_id,
        "service": service,
        "created_at": datetime.utcnow().isoformat()
    }
    
    # Build OAuth URL
    # Request both Gmail and Calendar scopes so user only needs to auth once
    scopes = get_all_google_scopes()
    
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(scopes),
        "state": state,
        "access_type": "offline",  # Get refresh token
        "prompt": "consent",  # Force consent to get refresh token
    }
    
    auth_url = f"{GOOGLE_AUTH_URL}?{urlencode(params)}"
    
    return RedirectResponse(url=auth_url)


@router.get(
    "/google/callback",
    summary="Handle Google OAuth callback"
)
async def google_oauth_callback(
    code: str = Query(None, description="Authorization code from Google"),
    state: str = Query(None, description="State token for CSRF validation"),
    error: str = Query(None, description="Error from Google"),
    db: Session = Depends(get_db)
):
    """
    Handle the OAuth callback from Google.
    
    Exchanges the authorization code for access/refresh tokens
    and stores them in the database.
    """
    # Handle errors from Google
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
    service = state_data["service"]
    
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
                GOOGLE_TOKEN_URL,
                data={
                    "client_id": GOOGLE_CLIENT_ID,
                    "client_secret": GOOGLE_CLIENT_SECRET,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": GOOGLE_REDIRECT_URI,
                }
            )
            
            if response.status_code != 200:
                error_detail = response.json().get("error_description", "Token exchange failed")
                return RedirectResponse(
                    url=f"{FRONTEND_URL}/integrations/integrations-page?error={error_detail}"
                )
            
            tokens = response.json()
            
    except Exception as e:
        return RedirectResponse(
            url=f"{FRONTEND_URL}/integrations/integrations-page?error=token_exchange_failed"
        )
    
    # Store tokens as credentials
    credentials = {
        "access_token": tokens.get("access_token"),
        "refresh_token": tokens.get("refresh_token"),
        "token_type": tokens.get("token_type", "Bearer"),
        "expires_in": tokens.get("expires_in"),
        "scope": tokens.get("scope"),
        "obtained_at": datetime.utcnow().isoformat(),
    }
    
    # Verify user exists
    user = crud.get_user_by_id(db, user_id)
    if not user:
        return RedirectResponse(
            url=f"{FRONTEND_URL}/integrations/integrations-page?error=user_not_found"
        )
    
    # Store credentials for all Google services if user requested "google"
    all_google_services = ["gmail", "calendar", "docs", "sheets", "slides", "drive", "forms", "meet"]
    services_to_connect = all_google_services if service == "google" else [service]
    
    for svc in services_to_connect:
        try:
            # Check if integration already exists
            existing = crud.get_user_integration(db, user_id, svc)
            if existing:
                # Update existing integration
                crud.update_integration_credentials(db, existing.id, credentials)
            else:
                # Create new integration
                crud.add_integration(
                    db=db,
                    user_id=user_id,
                    service_name=svc,
                    api_key=None,
                    credentials=credentials
                )
        except Exception as e:
            print(f"Error storing {svc} integration: {e}")
    
    # Redirect back to frontend with success
    return RedirectResponse(
        url=f"{FRONTEND_URL}/integrations/integrations-page?success=google_connected&service={service}"
    )


async def refresh_google_token(refresh_token: str) -> dict | None:
    """
    Refresh an expired Google access token.
    
    Args:
        refresh_token: The refresh token from the original OAuth flow
        
    Returns:
        New token data or None if refresh failed
    """
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        return None
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "client_id": GOOGLE_CLIENT_ID,
                    "client_secret": GOOGLE_CLIENT_SECRET,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                }
            )
            
            if response.status_code != 200:
                return None
            
            tokens = response.json()
            return {
                "access_token": tokens.get("access_token"),
                "token_type": tokens.get("token_type", "Bearer"),
                "expires_in": tokens.get("expires_in"),
                "obtained_at": datetime.utcnow().isoformat(),
            }
            
    except Exception:
        return None


def is_token_expired(credentials: dict) -> bool:
    """Check if an OAuth token is expired."""
    if not credentials:
        return True
    
    obtained_at = credentials.get("obtained_at")
    expires_in = credentials.get("expires_in", 3600)
    
    if not obtained_at:
        return True
    
    try:
        obtained_dt = datetime.fromisoformat(obtained_at)
        expiry_dt = obtained_dt + timedelta(seconds=expires_in - 60)  # 60 second buffer
        return datetime.utcnow() > expiry_dt
    except:
        return True
