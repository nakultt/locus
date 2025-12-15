"""
Google Calendar Integration Service
LangChain tools for calendar management
"""

from typing import Any
from datetime import datetime, timedelta
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

# Store credentials at module level for tool access
_calendar_config: dict = {}


class CreateEventInput(BaseModel):
    """Input schema for creating a calendar event."""
    summary: str = Field(description="Event title/name")
    description: str = Field(default="", description="Event description")
    start_time: str = Field(description="Start time (e.g., '2025-12-16 14:00' or 'tomorrow at 2pm')")
    duration_minutes: int = Field(default=60, description="Duration in minutes")
    attendees: str = Field(default="", description="Comma-separated email addresses of attendees")


class ViewEventsInput(BaseModel):
    """Input schema for viewing calendar events."""
    days: int = Field(default=7, description="Number of days to look ahead")


@tool("calendar_create_event", args_schema=CreateEventInput)
def calendar_create_event(
    summary: str,
    description: str = "",
    start_time: str = "",
    duration_minutes: int = 60,
    attendees: str = ""
) -> str:
    """
    Create a new calendar event.
    
    Use this when the user wants to schedule a meeting, create an event, or add something to their calendar.
    """
    try:
        if not _calendar_config.get("credentials"):
            return "Error: Google Calendar is not configured. Please connect your Google account first."
        
        # Parse start time (simplified parsing)
        try:
            if "tomorrow" in start_time.lower():
                start_dt = datetime.now() + timedelta(days=1)
                start_dt = start_dt.replace(hour=14, minute=0, second=0)  # Default 2pm
            elif "today" in start_time.lower():
                start_dt = datetime.now()
                start_dt = start_dt.replace(hour=14, minute=0, second=0)
            else:
                # Try parsing as datetime
                for fmt in ["%Y-%m-%d %H:%M", "%Y-%m-%d", "%d/%m/%Y %H:%M"]:
                    try:
                        start_dt = datetime.strptime(start_time, fmt)
                        break
                    except ValueError:
                        continue
                else:
                    start_dt = datetime.now() + timedelta(hours=1)
        except:
            start_dt = datetime.now() + timedelta(hours=1)
        
        end_dt = start_dt + timedelta(minutes=duration_minutes)
        
        try:
            from googleapiclient.discovery import build
            from google.oauth2.credentials import Credentials
            
            creds = Credentials.from_authorized_user_info(_calendar_config["credentials"])
            service = build("calendar", "v3", credentials=creds)
            
            event = {
                "summary": summary,
                "description": description,
                "start": {
                    "dateTime": start_dt.isoformat(),
                    "timeZone": "UTC"
                },
                "end": {
                    "dateTime": end_dt.isoformat(),
                    "timeZone": "UTC"
                }
            }
            
            if attendees:
                event["attendees"] = [
                    {"email": email.strip()} 
                    for email in attendees.split(",")
                ]
            
            result = service.events().insert(
                calendarId="primary",
                body=event,
                sendUpdates="all"
            ).execute()
            
            return f"""✅ Event created!
📅 {summary}
🕐 {start_dt.strftime('%B %d, %Y at %I:%M %p')}
⏱️ Duration: {duration_minutes} minutes
🔗 {result.get('htmlLink', 'Link not available')}"""
            
        except ImportError:
            # Mock response for demo
            return f"""✅ Event created!
📅 {summary}
🕐 {start_dt.strftime('%B %d, %Y at %I:%M %p')}
⏱️ Duration: {duration_minutes} minutes
{"👥 Attendees: " + attendees if attendees else ""}

(Demo mode - google-api-python-client not fully configured)"""
            
    except Exception as e:
        return f"❌ Error creating event: {str(e)}"


@tool("calendar_view_upcoming", args_schema=ViewEventsInput)
def calendar_view_upcoming(days: int = 7) -> str:
    """
    View upcoming calendar events.
    
    Use this when the user asks about their schedule, upcoming meetings, or what's on their calendar.
    """
    try:
        if not _calendar_config.get("credentials"):
            return "Error: Google Calendar is not configured. Please connect your Google account first."
        
        try:
            from googleapiclient.discovery import build
            from google.oauth2.credentials import Credentials
            
            creds = Credentials.from_authorized_user_info(_calendar_config["credentials"])
            service = build("calendar", "v3", credentials=creds)
            
            now = datetime.utcnow().isoformat() + "Z"
            end = (datetime.utcnow() + timedelta(days=days)).isoformat() + "Z"
            
            events_result = service.events().list(
                calendarId="primary",
                timeMin=now,
                timeMax=end,
                maxResults=20,
                singleEvents=True,
                orderBy="startTime"
            ).execute()
            
            events = events_result.get("items", [])
            
            if not events:
                return f"📅 No events scheduled for the next {days} days."
            
            output = f"📅 Upcoming events (next {days} days):\n\n"
            
            for event in events:
                start = event["start"].get("dateTime", event["start"].get("date"))
                summary = event.get("summary", "No title")
                
                # Parse and format time
                try:
                    dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                    time_str = dt.strftime("%b %d, %I:%M %p")
                except:
                    time_str = start
                
                output += f"• {time_str}: {summary}\n"
            
            return output
            
        except ImportError:
            # Mock response for demo
            return f"""📅 Upcoming events (next {days} days):

• Dec 16, 10:00 AM: Team Standup
• Dec 16, 02:00 PM: Project Review Meeting
• Dec 17, 11:00 AM: 1:1 with Manager
• Dec 18, 03:00 PM: Sprint Planning
• Dec 20, 09:00 AM: Client Demo

(Demo mode - google-api-python-client not fully configured)"""
            
    except Exception as e:
        return f"❌ Error fetching calendar: {str(e)}"


@tool("calendar_today")
def calendar_today() -> str:
    """
    Get today's calendar events.
    
    Use this when the user asks about today's schedule, today's meetings, or "what's on for today".
    """
    try:
        if not _calendar_config.get("credentials"):
            return "Error: Google Calendar is not configured. Please connect your Google account first."
        
        try:
            from googleapiclient.discovery import build
            from google.oauth2.credentials import Credentials
            
            creds = Credentials.from_authorized_user_info(_calendar_config["credentials"])
            service = build("calendar", "v3", credentials=creds)
            
            today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            tomorrow = today + timedelta(days=1)
            
            events_result = service.events().list(
                calendarId="primary",
                timeMin=today.isoformat() + "Z",
                timeMax=tomorrow.isoformat() + "Z",
                singleEvents=True,
                orderBy="startTime"
            ).execute()
            
            events = events_result.get("items", [])
            
            if not events:
                return "📅 No events scheduled for today. Your calendar is clear!"
            
            output = f"📅 Today's schedule ({today.strftime('%B %d, %Y')}):\n\n"
            
            for event in events:
                start = event["start"].get("dateTime", event["start"].get("date"))
                summary = event.get("summary", "No title")
                
                try:
                    dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                    time_str = dt.strftime("%I:%M %p")
                except:
                    time_str = "All day"
                
                output += f"• {time_str}: {summary}\n"
            
            return output
            
        except ImportError:
            today = datetime.now()
            return f"""📅 Today's schedule ({today.strftime('%B %d, %Y')}):

• 09:00 AM: Daily Standup
• 11:00 AM: Design Review
• 02:00 PM: Sprint Planning
• 04:00 PM: Code Review Session

(Demo mode - google-api-python-client not fully configured)"""
            
    except Exception as e:
        return f"❌ Error fetching today's events: {str(e)}"


def get_calendar_tools(credentials: dict[str, Any]) -> list[BaseTool]:
    """
    Get LangChain tools for Google Calendar integration.
    
    Args:
        credentials: OAuth credentials dict
        
    Returns:
        List of Calendar tools
    """
    global _calendar_config
    _calendar_config = {"credentials": credentials}
    
    return [
        calendar_create_event,
        calendar_view_upcoming,
        calendar_today
    ]
