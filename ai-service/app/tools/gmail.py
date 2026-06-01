"""
Gmail Integration Service
LangChain tools for email management using direct HTTP API calls
"""

import base64
import httpx
from email.mime.text import MIMEText
from typing import Any
from datetime import datetime, timedelta
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

# Store credentials at module level for tool access
_gmail_config: dict = {}

# Gmail API base URL
GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"

# Google OAuth token refresh URL
TOKEN_REFRESH_URL = "https://oauth2.googleapis.com/token"


class SendEmailInput(BaseModel):
    """Input schema for sending an email."""
    to: str = Field(description="Recipient email address")
    subject: str = Field(description="Email subject line")
    body: str = Field(description="Email body content")


class ReadEmailsInput(BaseModel):
    """Input schema for reading latest emails."""
    max_results: int = Field(default=5, description="Maximum number of emails to retrieve (default: 5)")


def _is_token_expired() -> bool:
    """Check if the current access token is expired."""
    credentials = _gmail_config.get("credentials", {})
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
    credentials = _gmail_config.get("credentials", {})
    refresh_token = credentials.get("refresh_token")
    client_id = _gmail_config.get("client_id")
    client_secret = _gmail_config.get("client_secret")
    
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
            _gmail_config["credentials"]["access_token"] = tokens.get("access_token")
            _gmail_config["credentials"]["expires_in"] = tokens.get("expires_in", 3600)
            _gmail_config["credentials"]["obtained_at"] = datetime.utcnow().isoformat()
            return True
    except Exception:
        return False


def _get_access_token() -> str | None:
    """Get a valid access token, refreshing if necessary."""
    if _is_token_expired():
        if not _refresh_token():
            return None
    
    return _gmail_config.get("credentials", {}).get("access_token")


def _get_auth_headers() -> dict | None:
    """Get authorization headers for API requests."""
    access_token = _get_access_token()
    if not access_token:
        return None
    
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }


@tool("gmail_send_email", args_schema=SendEmailInput)
def gmail_send_email(to: str, subject: str, body: str) -> str:
    """
    Send an email via Gmail.
    
    Use this when the user wants to send an email, message someone, or email a contact.
    """
    try:
        headers = _get_auth_headers()
        if not headers:
            return "Error: Gmail is not configured or token expired. Please reconnect your Gmail account."
        
        # Build RFC 2822 email message
        message = MIMEText(body)
        message["to"] = to
        message["subject"] = subject
        
        # Base64url encode the message
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
        
        # Send via Gmail API
        with httpx.Client() as client:
            response = client.post(
                f"{GMAIL_API_BASE}/messages/send",
                headers=headers,
                json={"raw": raw}
            )
            
            if response.status_code == 200:
                result = response.json()
                return f"""✅ Email sent successfully!
To: {to}
Subject: {subject}
Message ID: {result.get('id', 'N/A')}"""
            else:
                error_detail = response.json().get("error", {}).get("message", "Unknown error")
                return f"❌ Failed to send email: {error_detail}"
                
    except Exception as e:
        return f"❌ Error sending email: {str(e)}"


@tool("gmail_read_latest_emails", args_schema=ReadEmailsInput)
def gmail_read_latest_emails(max_results: int = 5) -> str:
    """
    Read the latest emails from Gmail inbox.
    
    Use this when the user wants to check their emails, see recent messages, or read their inbox.
    """
    try:
        headers = _get_auth_headers()
        if not headers:
            return "Error: Gmail is not configured or token expired. Please reconnect your Gmail account."
        
        with httpx.Client() as client:
            # Get list of messages
            list_response = client.get(
                f"{GMAIL_API_BASE}/messages",
                headers=headers,
                params={"maxResults": max_results}
            )
            
            if list_response.status_code != 200:
                error_detail = list_response.json().get("error", {}).get("message", "Unknown error")
                return f"❌ Failed to fetch emails: {error_detail}"
            
            messages = list_response.json().get("messages", [])
            
            if not messages:
                return "📭 No emails found in your inbox."
            
            output = f"📬 Latest {len(messages)} email(s):\n\n"
            
            # Fetch details for each message
            for msg in messages:
                msg_response = client.get(
                    f"{GMAIL_API_BASE}/messages/{msg['id']}",
                    headers=headers,
                    params={"format": "metadata", "metadataHeaders": ["From", "Subject"]}
                )
                
                if msg_response.status_code == 200:
                    msg_data = msg_response.json()
                    
                    # Extract headers
                    headers_list = msg_data.get("payload", {}).get("headers", [])
                    headers_dict = {h["name"]: h["value"] for h in headers_list}
                    
                    sender = headers_dict.get("From", "Unknown sender")
                    subject = headers_dict.get("Subject", "No subject")
                    snippet = msg_data.get("snippet", "")[:100]
                    
                    output += f"• From: {sender}\n"
                    output += f"  Subject: {subject}\n"
                    output += f"  Preview: {snippet}...\n\n"
            
            return output
            
    except Exception as e:
        return f"❌ Error reading emails: {str(e)}"


def get_gmail_tools(credentials: dict[str, Any] = None, api_key: str = "") -> list[BaseTool]:
    """
    Get LangChain tools for Gmail integration.
    
    Args:
        credentials: OAuth credentials dict containing access_token, refresh_token, etc.
        api_key: Not used (kept for compatibility)
        
    Returns:
        List of Gmail tools
    """
    global _gmail_config
    
    import os
    _gmail_config = {
        "credentials": credentials,
        "client_id": os.getenv("GOOGLE_CLIENT_ID", ""),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET", ""),
    }
    
    return [
        gmail_send_email,
        gmail_read_latest_emails,
    ]
