"""
Google Slides Integration Service
LangChain tools for presentation management using direct HTTP API calls
"""

import httpx
from typing import Any
from datetime import datetime, timedelta
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

# Store credentials at module level for tool access
_slides_config: dict = {}

# Google Slides API base URL
SLIDES_API_BASE = "https://slides.googleapis.com/v1/presentations"

# Google OAuth token refresh URL
TOKEN_REFRESH_URL = "https://oauth2.googleapis.com/token"


class CreatePresentationInput(BaseModel):
    """Input schema for creating a presentation."""
    title: str = Field(description="Presentation title")
    bullet_points: str = Field(
        default="",
        description="Semicolon-separated bullet points for slides. Use '|' to separate slides. Example: 'Point 1;Point 2|Point 3;Point 4' creates 2 slides"
    )


def _is_token_expired() -> bool:
    """Check if the current access token is expired."""
    credentials = _slides_config.get("credentials", {})
    if not credentials:
        return True
    
    obtained_at = credentials.get("obtained_at")
    expires_in = credentials.get("expires_in", 3600)
    
    if not obtained_at:
        return True
    
    try:
        obtained_dt = datetime.fromisoformat(obtained_at)
        expiry_dt = obtained_dt + timedelta(seconds=expires_in - 60)
        return datetime.utcnow() > expiry_dt
    except:
        return True


def _refresh_token() -> bool:
    """Refresh the access token using the refresh token."""
    credentials = _slides_config.get("credentials", {})
    refresh_token = credentials.get("refresh_token")
    client_id = _slides_config.get("client_id")
    client_secret = _slides_config.get("client_secret")
    
    if not refresh_token or not client_id or not client_secret:
        return False
    
    try:
        with httpx.Client() as client:
            response = client.post(
                TOKEN_REFRESH_URL,
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                }
            )
            
            if response.status_code != 200:
                return False
            
            tokens = response.json()
            _slides_config["credentials"]["access_token"] = tokens.get("access_token")
            _slides_config["credentials"]["expires_in"] = tokens.get("expires_in", 3600)
            _slides_config["credentials"]["obtained_at"] = datetime.utcnow().isoformat()
            return True
    except Exception:
        return False


def _get_access_token() -> str | None:
    """Get a valid access token, refreshing if necessary."""
    if _is_token_expired():
        if not _refresh_token():
            return None
    
    return _slides_config.get("credentials", {}).get("access_token")


def _get_auth_headers() -> dict | None:
    """Get authorization headers for API requests."""
    access_token = _get_access_token()
    if not access_token:
        return None
    
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }


@tool("slides_create_presentation", args_schema=CreatePresentationInput)
def slides_create_presentation(title: str, bullet_points: str = "") -> str:
    """
    Create a new Google Slides presentation.
    
    Use this when the user wants to create a presentation, make slides, or build a deck.
    """
    try:
        headers = _get_auth_headers()
        if not headers:
            return "Error: Google Slides is not configured or token expired. Please reconnect your Google account."
        
        with httpx.Client() as client:
            # Create presentation
            create_response = client.post(
                SLIDES_API_BASE,
                headers=headers,
                json={"title": title}
            )
            
            if create_response.status_code not in [200, 201]:
                error_detail = create_response.json().get("error", {}).get("message", "Unknown error")
                return f"❌ Failed to create presentation: {error_detail}"
            
            presentation = create_response.json()
            presentation_id = presentation.get("presentationId")
            
            # Parse and add slides with bullet points
            if bullet_points:
                slides = bullet_points.split("|")
                requests = []
                
                for i, slide_content in enumerate(slides):
                    points = [p.strip() for p in slide_content.split(";") if p.strip()]
                    if not points:
                        continue
                    
                    # Create a new slide
                    slide_id = f"slide_{i}"
                    requests.append({
                        "createSlide": {
                            "objectId": slide_id,
                            "slideLayoutReference": {
                                "predefinedLayout": "TITLE_AND_BODY"
                            }
                        }
                    })
                
                if requests:
                    # Add slides
                    batch_response = client.post(
                        f"{SLIDES_API_BASE}/{presentation_id}:batchUpdate",
                        headers=headers,
                        json={"requests": requests}
                    )
                    
                    if batch_response.status_code == 200:
                        # Now add text to each slide
                        text_requests = []
                        for i, slide_content in enumerate(slides):
                            points = [p.strip() for p in slide_content.split(";") if p.strip()]
                            if not points:
                                continue
                            
                            slide_id = f"slide_{i}"
                            body_text = "\n• " + "\n• ".join(points)
                            
                            # Get the body shape ID from the created slide
                            get_response = client.get(
                                f"{SLIDES_API_BASE}/{presentation_id}",
                                headers=headers
                            )
                            
                            if get_response.status_code == 200:
                                pres_data = get_response.json()
                                for slide in pres_data.get("slides", []):
                                    if slide.get("objectId") == slide_id:
                                        for element in slide.get("pageElements", []):
                                            shape = element.get("shape", {})
                                            if shape.get("shapeType") == "TEXT_BOX":
                                                placeholder = shape.get("placeholder", {})
                                                if placeholder.get("type") == "BODY":
                                                    text_requests.append({
                                                        "insertText": {
                                                            "objectId": element.get("objectId"),
                                                            "text": body_text,
                                                            "insertionIndex": 0
                                                        }
                                                    })
                        
                        if text_requests:
                            client.post(
                                f"{SLIDES_API_BASE}/{presentation_id}:batchUpdate",
                                headers=headers,
                                json={"requests": text_requests}
                            )
            
            slide_count = len(bullet_points.split("|")) if bullet_points else 0
            return f"""✅ Presentation created successfully!
🎨 Title: {title}
📊 Slides: {slide_count + 1} (including title slide)
🆔 Presentation ID: {presentation_id}
🔗 https://docs.google.com/presentation/d/{presentation_id}/edit"""
                
    except Exception as e:
        return f"❌ Error creating presentation: {str(e)}"


def get_slides_tools(credentials: dict[str, Any] = None) -> list[BaseTool]:
    """
    Get LangChain tools for Google Slides integration.
    
    Args:
        credentials: OAuth credentials dict containing access_token, refresh_token, etc.
        
    Returns:
        List of Google Slides tools
    """
    global _slides_config
    
    import os
    _slides_config = {
        "credentials": credentials,
        "client_id": os.getenv("GOOGLE_CLIENT_ID", ""),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET", ""),
    }
    
    return [
        slides_create_presentation,
    ]
