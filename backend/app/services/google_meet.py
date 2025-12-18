"""
Google Meet Integration Service
LangChain tools for creating meetings via Calendar API with conferenceData
"""

import httpx
import uuid
from typing import Any
from datetime import datetime, timedelta
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

# Store credentials at module level for tool access
_meet_config: dict = {}

# Google Calendar API base URL (Meet uses Calendar API)
CALENDAR_API_BASE = "https://www.googleapis.com/calendar/v3/calendars/primary"

# Google OAuth token refresh URL
TOKEN_REFRESH_URL = "https://oauth2.googleapis.com/token"


class CreateMeetingInput(BaseModel):
    """Input schema for creating a meeting with video conferencing."""
    title: str = Field(description="Meeting title")
    start_time: str = Field(description="Start datetime in ISO format (e.g., '2025-12-18T14:00:00') or natural language like 'tomorrow at 2pm'")
    end_time: str = Field(default="", description="End datetime in ISO format. If not provided, defaults to 1 hour after start.")
    attendees: str = Field(default="", description="Comma-separated email addresses of attendees (optional)")
    description: str = Field(default="", description="Meeting description/agenda (optional)")


def _is_token_expired() -> bool:
    """Check if the current access token is expired."""
    credentials = _meet_config.get("credentials", {})
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
    credentials = _meet_config.get("credentials", {})
    refresh_token = credentials.get("refresh_token")
    client_id = _meet_config.get("client_id")
    client_secret = _meet_config.get("client_secret")
    
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
            _meet_config["credentials"]["access_token"] = tokens.get("access_token")
            _meet_config["credentials"]["expires_in"] = tokens.get("expires_in", 3600)
            _meet_config["credentials"]["obtained_at"] = datetime.utcnow().isoformat()
            return True
    except Exception:
        return False


def _get_access_token() -> str | None:
    """Get a valid access token, refreshing if necessary."""
    if _is_token_expired():
        if not _refresh_token():
            return None
    
    return _meet_config.get("credentials", {}).get("access_token")


def _get_auth_headers() -> dict | None:
    """Get authorization headers for API requests."""
    access_token = _get_access_token()
    if not access_token:
        return None
    
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }


def _parse_datetime(dt_string: str) -> datetime:
    """Parse datetime string to datetime object."""
    dt_string = dt_string.strip()
    
    # Handle natural language
    if "tomorrow" in dt_string.lower():
        base = datetime.now() + timedelta(days=1)
        if "2pm" in dt_string.lower() or "14:00" in dt_string:
            return base.replace(hour=14, minute=0, second=0, microsecond=0)
        elif "3pm" in dt_string.lower() or "15:00" in dt_string:
            return base.replace(hour=15, minute=0, second=0, microsecond=0)
        elif "10am" in dt_string.lower() or "10:00" in dt_string:
            return base.replace(hour=10, minute=0, second=0, microsecond=0)
        else:
            return base.replace(hour=9, minute=0, second=0, microsecond=0)
    
    if "today" in dt_string.lower():
        base = datetime.now()
        if "2pm" in dt_string.lower() or "14:00" in dt_string:
            return base.replace(hour=14, minute=0, second=0, microsecond=0)
        elif "3pm" in dt_string.lower() or "15:00" in dt_string:
            return base.replace(hour=15, minute=0, second=0, microsecond=0)
        else:
            return base.replace(hour=9, minute=0, second=0, microsecond=0)
    
    # Try ISO format
    for fmt in ["%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"]:
        try:
            return datetime.strptime(dt_string, fmt)
        except ValueError:
            continue
    
    # Default: 1 hour from now
    return datetime.now() + timedelta(hours=1)


@tool("meet_create_meeting", args_schema=CreateMeetingInput)
def meet_create_meeting(
    title: str,
    start_time: str,
    end_time: str = "",
    attendees: str = "",
    description: str = ""
) -> str:
    """
    Create a Google Meet video meeting.
    
    Use this when the user wants to schedule a video call, create a meeting link, or set up a Google Meet.
    """
    try:
        headers = _get_auth_headers()
        if not headers:
            return "Error: Google Meet is not configured or token expired. Please reconnect your Google account."
        
        # Parse times
        start_dt = _parse_datetime(start_time)
        
        if end_time:
            end_dt = _parse_datetime(end_time)
        else:
            end_dt = start_dt + timedelta(hours=1)
        
        # Build event with conferenceData
        event = {
            "summary": title,
            "description": description,
            "start": {
                "dateTime": start_dt.isoformat(),
                "timeZone": "UTC"
            },
            "end": {
                "dateTime": end_dt.isoformat(),
                "timeZone": "UTC"
            },
            "conferenceData": {
                "createRequest": {
                    "requestId": str(uuid.uuid4()),
                    "conferenceSolutionKey": {
                        "type": "hangoutsMeet"
                    }
                }
            }
        }
        
        # Add attendees if provided
        if attendees:
            event["attendees"] = [
                {"email": email.strip()} 
                for email in attendees.split(",") 
                if email.strip()
            ]
        
        with httpx.Client() as client:
            response = client.post(
                f"{CALENDAR_API_BASE}/events",
                headers=headers,
                params={
                    "conferenceDataVersion": 1,
                    "sendUpdates": "all" if attendees else "none"
                },
                json=event
            )
            
            if response.status_code in [200, 201]:
                result = response.json()
                event_id = result.get("id")
                
                # Extract Meet link
                conference_data = result.get("conferenceData", {})
                entry_points = conference_data.get("entryPoints", [])
                meet_link = next(
                    (ep.get("uri") for ep in entry_points if ep.get("entryPointType") == "video"),
                    None
                )
                
                attendee_list = ", ".join([a["email"] for a in result.get("attendees", [])]) or "None"
                
                output = f"""✅ Meeting created successfully!
🎥 Title: {title}
🕐 {start_dt.strftime('%B %d, %Y at %I:%M %p')} - {end_dt.strftime('%I:%M %p')} UTC
👥 Attendees: {attendee_list}
🆔 Event ID: {event_id}"""
                
                if meet_link:
                    output += f"\n📹 Meet Link: {meet_link}"
                
                output += f"\n📅 Calendar: {result.get('htmlLink', 'N/A')}"
                
                return output
            else:
                error_detail = response.json().get("error", {}).get("message", "Unknown error")
                return f"❌ Failed to create meeting: {error_detail}"
                
    except Exception as e:
        return f"❌ Error creating meeting: {str(e)}"


def get_meet_tools(credentials: dict[str, Any] = None) -> list[BaseTool]:
    """
    Get LangChain tools for Google Meet integration.
    
    Args:
        credentials: OAuth credentials dict containing access_token, refresh_token, etc.
        
    Returns:
        List of Google Meet tools
    """
    global _meet_config
    
    import os
    _meet_config = {
        "credentials": credentials,
        "client_id": os.getenv("GOOGLE_CLIENT_ID", ""),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET", ""),
    }
    
    return [
        meet_create_meeting,
    ]
