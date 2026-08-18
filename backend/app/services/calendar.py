"""
Google Calendar Integration Service
LangChain tools for calendar management using direct HTTP API calls
"""

from datetime import datetime, timedelta
from typing import Any

import httpx
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from app.services.credential_context import CredentialProxy
from app.services.datetimes import (
    DEFAULT_TIMEZONE,
    next_working_slot,
    now_in,
    parse_datetime,
    resolve_timezone,
    to_google_datetime,
)

# Store credentials at module level for tool access
# Task-local so concurrent users cannot see each other's credentials.
# See app/services/credential_context.py.
_calendar_config = CredentialProxy("calendar")

# Google Calendar API base URL
CALENDAR_API_BASE = "https://www.googleapis.com/calendar/v3/calendars/primary"

# Google OAuth token refresh URL
TOKEN_REFRESH_URL = "https://oauth2.googleapis.com/token"


class CreateEventInput(BaseModel):
    """Input schema for creating a calendar event."""
    title: str = Field(description="Event title/name")
    # The user's own words are preferred over ISO: this is parsed against the
    # real clock in the user's zone, whereas a model converting to ISO itself
    # has repeatedly resolved "tomorrow" to today or to its training cutoff.
    start_datetime: str = Field(description="Start time, preferably in the user's own words: 'tomorrow at 11pm', 'next Friday 2pm', 'in 2 hours'. Pass the phrasing through verbatim -- do NOT convert it to an absolute date yourself. ISO format ('2026-08-18T14:00:00') is accepted only when the user gave an explicit calendar date.")
    end_datetime: str = Field(default="", description="End time, same format as start. Leave empty to default to 1 hour after start.")
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
    """
    Parse a datetime in the connected user's timezone.

    Delegates to app.services.datetimes, which understands full natural
    language. The old implementation recognised only "2pm", "3pm" and "10am"
    and silently returned 9am for everything else.

    Falls back to the next working slot when no time can be read, rather than
    inventing 9am today.
    """
    tz_name = _calendar_config.get("timezone") or DEFAULT_TIMEZONE

    parsed = parse_datetime(dt_string, tz_name)
    if parsed is not None:
        return parsed

    return next_working_slot(now_in(tz_name) + timedelta(hours=1))


class ListEventsInput(BaseModel):
    """Input schema for listing calendar events."""
    start: str = Field(default="today", description="Start of the range, e.g. 'today' or 'monday'")
    end: str = Field(default="in 7 days", description="End of the range")


class MoveEventInput(BaseModel):
    """Input schema for moving an event."""
    event_id: str = Field(description="Google Calendar event id")
    new_start: str = Field(description="New start time, e.g. 'tomorrow at 3pm'")
    duration_minutes: int = Field(default=0, description="New duration; 0 keeps the current one")


@tool("calendar_list_events", args_schema=ListEventsInput)
def calendar_list_events(start: str = "today", end: str = "in 7 days") -> str:
    """
    List calendar events in a time range.

    Use this before scheduling anything, to see what is already booked.
    """
    events, error = fetch_events(start, end)
    if error:
        return f"Error: {error}"
    if not events:
        return f"No events between {start} and {end}."

    tz_name = _calendar_config.get("timezone") or DEFAULT_TIMEZONE
    lines = []
    for event in events:
        begins = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date", "")
        try:
            moment = datetime.fromisoformat(begins).astimezone(resolve_timezone(tz_name))
            when = moment.strftime("%a %d %b %H:%M")
        except ValueError:
            when = begins

        attendees = len(event.get("attendees", []) or [])
        lines.append(
            f"{when} - {event.get('summary', '(no title)')}"
            f"{f' ({attendees} attendees)' if attendees else ''}"
            f" [id: {event.get('id')}]"
        )

    # The zone is named once in the header rather than on every row. These
    # times are already converted into it; without saying which zone, a model
    # reading this list has no way to tell and neither does the user.
    return (
        f"Events between {start} and {end} (times in {tz_name}):\n"
        + "\n".join(lines)
    )


@tool("calendar_move_event", args_schema=MoveEventInput)
def calendar_move_event(event_id: str, new_start: str, duration_minutes: int = 0) -> str:
    """
    Move an event to a new time, keeping its attendees and details.

    Use this to resolve a scheduling conflict. Attendees are notified by Google.
    """
    headers = _get_auth_headers()
    if not headers:
        return "Error: Google Calendar is not configured or the token expired."

    tz_name = _calendar_config.get("timezone") or DEFAULT_TIMEZONE
    start_dt = parse_datetime(new_start, tz_name)
    if start_dt is None:
        return f"Error: could not understand the time '{new_start}'."

    try:
        existing = httpx.get(
            f"{CALENDAR_API_BASE}/events/{event_id}",
            headers=headers,
            timeout=30,
        )
        if existing.status_code != 200:
            return f"Error: event {event_id} not found."

        event = existing.json()

        if duration_minutes <= 0:
            # Preserve the original length rather than assuming an hour.
            try:
                old_start = datetime.fromisoformat(event["start"]["dateTime"])
                old_end = datetime.fromisoformat(event["end"]["dateTime"])
                duration_minutes = int((old_end - old_start).total_seconds() // 60) or 60
            except (KeyError, ValueError):
                duration_minutes = 60

        end_dt = start_dt + timedelta(minutes=duration_minutes)
        event["start"] = to_google_datetime(start_dt, tz_name)
        event["end"] = to_google_datetime(end_dt, tz_name)

        updated = httpx.put(
            f"{CALENDAR_API_BASE}/events/{event_id}",
            headers=headers,
            json=event,
            timeout=30,
        )
        if updated.status_code != 200:
            return f"Error moving event: {updated.status_code}"

        return (
            f"Moved '{event.get('summary', 'event')}' to "
            f"{start_dt.strftime('%a %d %b %H:%M')} ({tz_name})."
        )
    except Exception as e:
        return f"Error moving event: {e}"


def fetch_events(start: str, end: str) -> tuple[list[dict], str | None]:
    """
    Fetch events in a range.

    Shared by the tool above and the scheduler, which needs the raw objects
    rather than formatted text.

    Returns:
        (events, error message or None)
    """
    headers = _get_auth_headers()
    if not headers:
        return [], "Google Calendar is not configured or the token expired"

    tz_name = _calendar_config.get("timezone") or DEFAULT_TIMEZONE
    now = now_in(tz_name)

    start_dt = parse_datetime(start, tz_name) or now
    end_dt = parse_datetime(end, tz_name) or (start_dt + timedelta(days=7))

    try:
        response = httpx.get(
            f"{CALENDAR_API_BASE}/events",
            headers=headers,
            params={
                "timeMin": start_dt.isoformat(),
                "timeMax": end_dt.isoformat(),
                "singleEvents": "true",
                "orderBy": "startTime",
                "maxResults": 100,
            },
            timeout=30,
        )
        if response.status_code != 200:
            return [], f"Calendar API returned {response.status_code}"
        return response.json().get("items", []), None
    except Exception as e:
        return [], str(e)


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

        tz_name = _calendar_config.get("timezone") or DEFAULT_TIMEZONE

        # Parse start time
        start_dt = _parse_datetime(start_datetime)
        
        # Parse end time or default to 1 hour after start
        if end_datetime:
            end_dt = _parse_datetime(end_datetime)
        else:
            end_dt = start_dt + timedelta(hours=1)
        
        # Build event payload. The zone travels with the timestamp rather than
        # being converted to UTC, so a recurring event stays correct across a
        # DST shift.
        event = {
            "summary": title,
            "start": to_google_datetime(start_dt, tz_name),
            "end": to_google_datetime(end_dt, tz_name),
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
🕐 {start_dt.strftime('%B %d, %Y at %I:%M %p')} - {end_dt.strftime('%I:%M %p')} ({tz_name})
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
        
        tz_name = _calendar_config.get("timezone") or DEFAULT_TIMEZONE

        if start_datetime:
            update_data["start"] = to_google_datetime(
                _parse_datetime(start_datetime), tz_name
            )

        if end_datetime:
            update_data["end"] = to_google_datetime(
                _parse_datetime(end_datetime), tz_name
            )
        
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


def get_calendar_tools(
    credentials: dict[str, Any] = None,
    timezone: str | None = None,
) -> list[BaseTool]:
    """
    Get LangChain tools for Google Calendar integration.

    Args:
        credentials: OAuth credentials dict containing access_token, refresh_token
        timezone: The user's IANA timezone. Times are parsed and sent in this
            zone; without it every event lands at the server's UTC offset.

    Returns:
        List of Calendar tools
    """
    
    import os
    _calendar_config.set({
        "timezone": timezone or DEFAULT_TIMEZONE,
        "credentials": credentials,
        "client_id": os.getenv("GOOGLE_CLIENT_ID", ""),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET", ""),
    })
    
    return [
        calendar_list_events,
        calendar_move_event,
        calendar_create_event,
        calendar_update_event,
        calendar_delete_event,
    ]
