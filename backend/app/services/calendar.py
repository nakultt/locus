"""
Google Calendar Integration Service
LangChain tools for calendar management using direct HTTP API calls
"""

import httpx
from typing import Any, Optional
from datetime import datetime, timedelta
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

# Store credentials at module level for tool access
_calendar_config: dict = {}

# Google Calendar API base URL
CALENDAR_API_BASE = "https://www.googleapis.com/calendar/v3/calendars/primary"

# Google OAuth token refresh URL
TOKEN_REFRESH_URL = "https://oauth2.googleapis.com/token"


class CreateEventInput(BaseModel):
    """Input schema for creating a calendar event."""
    title: str = Field(description="Event title/name")
    start_datetime: str = Field(description="Start datetime in ISO format (e.g., '2025-12-18T14:00:00') or natural language like 'tomorrow at 2pm'")
    end_datetime: str = Field(default="", description="End datetime in ISO format. If not provided, defaults to 1 hour after start.")
    attendees: str = Field(default="", description="Comma-separated email addresses of attendees (optional)")


class UpdateEventInput(BaseModel):
    """Input schema for updating a calendar event."""
    event_id: str = Field(description="The ID of the event to update")
    title: str = Field(default="", description="New event title (optional)")
    start_datetime: str = Field(default="", description="New start datetime in ISO format (optional)")
    end_datetime: str = Field(default="", description="New end datetime in ISO format (optional)")


class DeleteEventInput(BaseModel):
    """Input schema for deleting a calendar event."""
    event_id: str = Field(description="The ID of the event to delete")


def _is_token_expired() -> bool:
    """Check if the current access token is expired."""
    credentials = _calendar_config.get("credentials", {})
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


def _refresh_token() -> bool:
    """Refresh the access token using the refresh token."""
    credentials = _calendar_config.get("credentials", {})
    refresh_token = credentials.get("refresh_token")
    client_id = _calendar_config.get("client_id")
    client_secret = _calendar_config.get("client_secret")
    
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
            # Update credentials with new access token
            _calendar_config["credentials"]["access_token"] = tokens.get("access_token")
            _calendar_config["credentials"]["expires_in"] = tokens.get("expires_in", 3600)
            _calendar_config["credentials"]["obtained_at"] = datetime.utcnow().isoformat()
            return True
    except Exception:
        return False


def _get_access_token() -> str | None:
    """Get a valid access token, refreshing if necessary."""
    if _is_token_expired():
        if not _refresh_token():
            return None
    
    return _calendar_config.get("credentials", {}).get("access_token")


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


@tool("calendar_create_event", args_schema=CreateEventInput)
def calendar_create_event(
    title: str,
    start_datetime: str,
    end_datetime: str = "",
    attendees: str = ""
) -> str:
    """
    Create a new calendar event.
    
    Use this when the user wants to schedule a meeting, create an event, or add something to their calendar.
    """
    try:
        headers = _get_auth_headers()
        if not headers:
            return "Error: Google Calendar is not configured or token expired. Please reconnect your Google account."
        
        # Parse start time
        start_dt = _parse_datetime(start_datetime)
        
        # Parse end time or default to 1 hour after start
        if end_datetime:
            end_dt = _parse_datetime(end_datetime)
        else:
            end_dt = start_dt + timedelta(hours=1)
        
        # Build event payload
        event = {
            "summary": title,
            "start": {
                "dateTime": start_dt.isoformat(),
                "timeZone": "UTC"
            },
            "end": {
                "dateTime": end_dt.isoformat(),
                "timeZone": "UTC"
            }
        }
        
        # Add attendees if provided
        if attendees:
            event["attendees"] = [
                {"email": email.strip()} 
                for email in attendees.split(",") 
                if email.strip()
            ]
        
        # Create event via Calendar API
        with httpx.Client() as client:
            response = client.post(
                f"{CALENDAR_API_BASE}/events",
                headers=headers,
                json=event,
                params={"sendUpdates": "all"} if attendees else {}
            )
            
            if response.status_code in [200, 201]:
                result = response.json()
                return f"""✅ Event created successfully!
📅 {title}
🕐 {start_dt.strftime('%B %d, %Y at %I:%M %p')} - {end_dt.strftime('%I:%M %p')}
🆔 Event ID: {result.get('id', 'N/A')}
🔗 {result.get('htmlLink', 'Link not available')}"""
            else:
                error_detail = response.json().get("error", {}).get("message", "Unknown error")
                return f"❌ Failed to create event: {error_detail}"
                
    except Exception as e:
        return f"❌ Error creating event: {str(e)}"


@tool("calendar_update_event", args_schema=UpdateEventInput)
def calendar_update_event(
    event_id: str,
    title: str = "",
    start_datetime: str = "",
    end_datetime: str = ""
) -> str:
    """
    Update an existing calendar event.
    
    Use this when the user wants to modify, reschedule, or rename an existing event.
    """
    try:
        headers = _get_auth_headers()
        if not headers:
            return "Error: Google Calendar is not configured or token expired. Please reconnect your Google account."
        
        # Build update payload with only provided fields
        update_data = {}
        
        if title:
            update_data["summary"] = title
        
        if start_datetime:
            start_dt = _parse_datetime(start_datetime)
            update_data["start"] = {
                "dateTime": start_dt.isoformat(),
                "timeZone": "UTC"
            }
        
        if end_datetime:
            end_dt = _parse_datetime(end_datetime)
            update_data["end"] = {
                "dateTime": end_dt.isoformat(),
                "timeZone": "UTC"
            }
        
        if not update_data:
            return "❌ No update fields provided. Please specify at least one field to update (title, start_datetime, or end_datetime)."
        
        # Update event via Calendar API (PATCH)
        with httpx.Client() as client:
            response = client.patch(
                f"{CALENDAR_API_BASE}/events/{event_id}",
                headers=headers,
                json=update_data
            )
            
            if response.status_code == 200:
                result = response.json()
                return f"""✅ Event updated successfully!
📅 {result.get('summary', 'N/A')}
🆔 Event ID: {event_id}
🔗 {result.get('htmlLink', 'Link not available')}"""
            elif response.status_code == 404:
                return f"❌ Event not found with ID: {event_id}"
            else:
                error_detail = response.json().get("error", {}).get("message", "Unknown error")
                return f"❌ Failed to update event: {error_detail}"
                
    except Exception as e:
        return f"❌ Error updating event: {str(e)}"


@tool("calendar_delete_event", args_schema=DeleteEventInput)
def calendar_delete_event(event_id: str) -> str:
    """
    Delete a calendar event.
    
    Use this when the user wants to cancel, remove, or delete an event from their calendar.
    """
    try:
        headers = _get_auth_headers()
        if not headers:
            return "Error: Google Calendar is not configured or token expired. Please reconnect your Google account."
        
        # Delete event via Calendar API
        with httpx.Client() as client:
            response = client.delete(
                f"{CALENDAR_API_BASE}/events/{event_id}",
                headers=headers
            )
            
            if response.status_code in [200, 204]:
                return f"""✅ Event deleted successfully!
🆔 Deleted Event ID: {event_id}"""
            elif response.status_code == 404:
                return f"❌ Event not found with ID: {event_id}"
            else:
                error_detail = response.json().get("error", {}).get("message", "Unknown error")
                return f"❌ Failed to delete event: {error_detail}"
                
    except Exception as e:
        return f"❌ Error deleting event: {str(e)}"


def get_calendar_tools(credentials: dict[str, Any] = None) -> list[BaseTool]:
    """
    Get LangChain tools for Google Calendar integration.
    
    Args:
        credentials: OAuth credentials dict containing access_token, refresh_token, etc.
        
    Returns:
        List of Calendar tools
    """
    global _calendar_config
    
    import os
    _calendar_config = {
        "credentials": credentials,
        "client_id": os.getenv("GOOGLE_CLIENT_ID", ""),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET", ""),
    }
    
    return [
        calendar_create_event,
        calendar_update_event,
        calendar_delete_event,
    ]
