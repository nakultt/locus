"""
Google Sheets Integration Service
LangChain tools for spreadsheet management using direct HTTP API calls
"""

import httpx
from typing import Any
from datetime import datetime, timedelta
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

# Store credentials at module level for tool access
_sheets_config: dict = {}

# Google Sheets API base URL
SHEETS_API_BASE = "https://sheets.googleapis.com/v4/spreadsheets"

# Google OAuth token refresh URL
TOKEN_REFRESH_URL = "https://oauth2.googleapis.com/token"


class AddRowInput(BaseModel):
    """Input schema for adding a row to a spreadsheet."""
    spreadsheet_id: str = Field(description="The spreadsheet ID")
    sheet_name: str = Field(default="Sheet1", description="The name of the sheet/tab (default: Sheet1)")
    values: str = Field(description="Comma-separated values for the row (e.g., 'John,Doe,john@email.com')")


class CreateSpreadsheetInput(BaseModel):
    """Input schema for creating a spreadsheet."""
    title: str = Field(description="Spreadsheet title")
    headers: str = Field(default="", description="Comma-separated header values (optional)")


def _is_token_expired() -> bool:
    """Check if the current access token is expired."""
    credentials = _sheets_config.get("credentials", {})
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
    credentials = _sheets_config.get("credentials", {})
    refresh_token = credentials.get("refresh_token")
    client_id = _sheets_config.get("client_id")
    client_secret = _sheets_config.get("client_secret")
    
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
            _sheets_config["credentials"]["access_token"] = tokens.get("access_token")
            _sheets_config["credentials"]["expires_in"] = tokens.get("expires_in", 3600)
            _sheets_config["credentials"]["obtained_at"] = datetime.utcnow().isoformat()
            return True
    except Exception:
        return False


def _get_access_token() -> str | None:
    """Get a valid access token, refreshing if necessary."""
    if _is_token_expired():
        if not _refresh_token():
            return None
    
    return _sheets_config.get("credentials", {}).get("access_token")


def _get_auth_headers() -> dict | None:
    """Get authorization headers for API requests."""
    access_token = _get_access_token()
    if not access_token:
        return None
    
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }


@tool("sheets_add_row", args_schema=AddRowInput)
def sheets_add_row(spreadsheet_id: str, sheet_name: str = "Sheet1", values: str = "") -> str:
    """
    Add a row to a Google Sheets spreadsheet.
    
    Use this when the user wants to add data to a spreadsheet, insert a row, or log data.
    """
    try:
        headers = _get_auth_headers()
        if not headers:
            return "Error: Google Sheets is not configured or token expired. Please reconnect your Google account."
        
        # Parse values
        row_values = [v.strip() for v in values.split(",")]
        
        with httpx.Client() as client:
            # Append row to spreadsheet
            response = client.post(
                f"{SHEETS_API_BASE}/{spreadsheet_id}/values/{sheet_name}:append",
                headers=headers,
                params={
                    "valueInputOption": "USER_ENTERED",
                    "insertDataOption": "INSERT_ROWS"
                },
                json={
                    "values": [row_values]
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                updated_range = result.get("updates", {}).get("updatedRange", "N/A")
                return f"""✅ Row added successfully!
📊 Spreadsheet ID: {spreadsheet_id}
📋 Sheet: {sheet_name}
📍 Updated Range: {updated_range}
🔗 https://docs.google.com/spreadsheets/d/{spreadsheet_id}"""
            elif response.status_code == 404:
                return f"❌ Spreadsheet not found: {spreadsheet_id}"
            else:
                error_detail = response.json().get("error", {}).get("message", "Unknown error")
                return f"❌ Failed to add row: {error_detail}"
                
    except Exception as e:
        return f"❌ Error adding row: {str(e)}"


@tool("sheets_create_spreadsheet", args_schema=CreateSpreadsheetInput)
def sheets_create_spreadsheet(title: str, headers: str = "") -> str:
    """
    Create a new Google Sheets spreadsheet.
    
    Use this when the user wants to create a new spreadsheet or start a new sheet.
    """
    try:
        auth_headers = _get_auth_headers()
        if not auth_headers:
            return "Error: Google Sheets is not configured or token expired. Please reconnect your Google account."
        
        with httpx.Client() as client:
            # Create spreadsheet
            create_response = client.post(
                SHEETS_API_BASE,
                headers=auth_headers,
                json={
                    "properties": {"title": title},
                    "sheets": [{"properties": {"title": "Sheet1"}}]
                }
            )
            
            if create_response.status_code not in [200, 201]:
                error_detail = create_response.json().get("error", {}).get("message", "Unknown error")
                return f"❌ Failed to create spreadsheet: {error_detail}"
            
            sheet = create_response.json()
            spreadsheet_id = sheet.get("spreadsheetId")
            
            # Add headers if provided
            if headers:
                header_values = [h.strip() for h in headers.split(",")]
                client.post(
                    f"{SHEETS_API_BASE}/{spreadsheet_id}/values/Sheet1:append",
                    headers=auth_headers,
                    params={"valueInputOption": "USER_ENTERED"},
                    json={"values": [header_values]}
                )
            
            return f"""✅ Spreadsheet created successfully!
📊 Title: {title}
🆔 Spreadsheet ID: {spreadsheet_id}
🔗 https://docs.google.com/spreadsheets/d/{spreadsheet_id}"""
                
    except Exception as e:
        return f"❌ Error creating spreadsheet: {str(e)}"


def get_sheets_tools(credentials: dict[str, Any] = None) -> list[BaseTool]:
    """
    Get LangChain tools for Google Sheets integration.
    
    Args:
        credentials: OAuth credentials dict containing access_token, refresh_token, etc.
        
    Returns:
        List of Google Sheets tools
    """
    global _sheets_config
    
    import os
    _sheets_config = {
        "credentials": credentials,
        "client_id": os.getenv("GOOGLE_CLIENT_ID", ""),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET", ""),
    }
    
    return [
        sheets_add_row,
        sheets_create_spreadsheet,
    ]
