"""
Google Drive Integration Service
LangChain tools for file management using direct HTTP API calls
"""

import httpx
import base64
from typing import Any
from datetime import datetime, timedelta
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

# Store credentials at module level for tool access
_drive_config: dict = {}

# Google Drive API base URL
DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"
DRIVE_UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"

# Google OAuth token refresh URL
TOKEN_REFRESH_URL = "https://oauth2.googleapis.com/token"


class UploadFileInput(BaseModel):
    """Input schema for uploading a file."""
    file_name: str = Field(description="Name of the file to create")
    mime_type: str = Field(
        default="text/plain",
        description="MIME type of the file (e.g., 'text/plain', 'application/pdf', 'image/png')"
    )
    content: str = Field(description="File content as text (for text files) or base64-encoded string (for binary)")


class ShareFileInput(BaseModel):
    """Input schema for sharing a file."""
    file_id: str = Field(description="The file ID to share")
    email: str = Field(description="Email address of the user to share with")
    role: str = Field(
        default="reader",
        description="Permission role: 'reader', 'writer', or 'commenter'"
    )


class ListFilesInput(BaseModel):
    """Input schema for listing files."""
    query: str = Field(default="", description="Search query (optional). Example: 'name contains \"report\"'")
    max_results: int = Field(default=10, description="Maximum number of files to return")


def _is_token_expired() -> bool:
    """Check if the current access token is expired."""
    credentials = _drive_config.get("credentials", {})
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
    credentials = _drive_config.get("credentials", {})
    refresh_token = credentials.get("refresh_token")
    client_id = _drive_config.get("client_id")
    client_secret = _drive_config.get("client_secret")
    
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
            _drive_config["credentials"]["access_token"] = tokens.get("access_token")
            _drive_config["credentials"]["expires_in"] = tokens.get("expires_in", 3600)
            _drive_config["credentials"]["obtained_at"] = datetime.utcnow().isoformat()
            return True
    except Exception:
        return False


def _get_access_token() -> str | None:
    """Get a valid access token, refreshing if necessary."""
    if _is_token_expired():
        if not _refresh_token():
            return None
    
    return _drive_config.get("credentials", {}).get("access_token")


def _get_auth_headers() -> dict | None:
    """Get authorization headers for API requests."""
    access_token = _get_access_token()
    if not access_token:
        return None
    
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }


@tool("drive_upload_file", args_schema=UploadFileInput)
def drive_upload_file(file_name: str, mime_type: str = "text/plain", content: str = "") -> str:
    """
    Upload a file to Google Drive.
    
    Use this when the user wants to upload a file, save a file to drive, or create a file in drive.
    """
    try:
        access_token = _get_access_token()
        if not access_token:
            return "Error: Google Drive is not configured or token expired. Please reconnect your Google account."
        
        with httpx.Client() as client:
            # Create file metadata
            metadata = {
                "name": file_name,
                "mimeType": mime_type
            }
            
            # Prepare content
            if mime_type.startswith("text/"):
                file_content = content.encode("utf-8")
            else:
                # Assume base64 encoded for binary
                try:
                    file_content = base64.b64decode(content)
                except:
                    file_content = content.encode("utf-8")
            
            # Use multipart upload
            boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
            
            body = (
                f"--{boundary}\r\n"
                f"Content-Type: application/json; charset=UTF-8\r\n\r\n"
                f'{{"name": "{file_name}", "mimeType": "{mime_type}"}}\r\n'
                f"--{boundary}\r\n"
                f"Content-Type: {mime_type}\r\n\r\n"
            ).encode("utf-8") + file_content + f"\r\n--{boundary}--".encode("utf-8")
            
            response = client.post(
                f"{DRIVE_UPLOAD_URL}?uploadType=multipart",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": f"multipart/related; boundary={boundary}"
                },
                content=body
            )
            
            if response.status_code in [200, 201]:
                result = response.json()
                file_id = result.get("id")
                return f"""✅ File uploaded successfully!
📁 Name: {file_name}
🆔 File ID: {file_id}
🔗 https://drive.google.com/file/d/{file_id}/view"""
            else:
                error_detail = response.json().get("error", {}).get("message", "Unknown error")
                return f"❌ Failed to upload file: {error_detail}"
                
    except Exception as e:
        return f"❌ Error uploading file: {str(e)}"


@tool("drive_share_file", args_schema=ShareFileInput)
def drive_share_file(file_id: str, email: str, role: str = "reader") -> str:
    """
    Share a Google Drive file with a user.
    
    Use this when the user wants to share a file, give access to a document, or collaborate on a file.
    """
    try:
        headers = _get_auth_headers()
        if not headers:
            return "Error: Google Drive is not configured or token expired. Please reconnect your Google account."
        
        # Validate role
        valid_roles = ["reader", "writer", "commenter"]
        if role not in valid_roles:
            role = "reader"
        
        with httpx.Client() as client:
            response = client.post(
                f"{DRIVE_API_BASE}/files/{file_id}/permissions",
                headers=headers,
                params={"sendNotificationEmail": "true"},
                json={
                    "type": "user",
                    "role": role,
                    "emailAddress": email
                }
            )
            
            if response.status_code in [200, 201]:
                return f"""✅ File shared successfully!
📁 File ID: {file_id}
👤 Shared with: {email}
🔐 Role: {role}"""
            elif response.status_code == 404:
                return f"❌ File not found: {file_id}"
            else:
                error_detail = response.json().get("error", {}).get("message", "Unknown error")
                return f"❌ Failed to share file: {error_detail}"
                
    except Exception as e:
        return f"❌ Error sharing file: {str(e)}"


@tool("drive_list_files", args_schema=ListFilesInput)
def drive_list_files(query: str = "", max_results: int = 10) -> str:
    """
    List files in Google Drive.
    
    Use this when the user wants to see their files, search for documents, or find files in drive.
    """
    try:
        headers = _get_auth_headers()
        if not headers:
            return "Error: Google Drive is not configured or token expired. Please reconnect your Google account."
        
        with httpx.Client() as client:
            params = {
                "pageSize": max_results,
                "fields": "files(id, name, mimeType, modifiedTime, webViewLink)"
            }
            
            if query:
                params["q"] = query
            
            response = client.get(
                f"{DRIVE_API_BASE}/files",
                headers=headers,
                params=params
            )
            
            if response.status_code == 200:
                files = response.json().get("files", [])
                
                if not files:
                    return "📂 No files found."
                
                output = f"📂 Found {len(files)} file(s):\n\n"
                for f in files:
                    name = f.get("name", "Unknown")
                    file_id = f.get("id", "N/A")
                    mime = f.get("mimeType", "unknown")
                    link = f.get("webViewLink", "")
                    output += f"• {name}\n  Type: {mime}\n  ID: {file_id}\n"
                    if link:
                        output += f"  🔗 {link}\n"
                    output += "\n"
                
                return output
            else:
                error_detail = response.json().get("error", {}).get("message", "Unknown error")
                return f"❌ Failed to list files: {error_detail}"
                
    except Exception as e:
        return f"❌ Error listing files: {str(e)}"


def get_drive_tools(credentials: dict[str, Any] = None) -> list[BaseTool]:
    """
    Get LangChain tools for Google Drive integration.
    
    Args:
        credentials: OAuth credentials dict containing access_token, refresh_token, etc.
        
    Returns:
        List of Google Drive tools
    """
    global _drive_config
    
    import os
    _drive_config = {
        "credentials": credentials,
        "client_id": os.getenv("GOOGLE_CLIENT_ID", ""),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET", ""),
    }
    
    return [
        drive_upload_file,
        drive_share_file,
        drive_list_files,
    ]
