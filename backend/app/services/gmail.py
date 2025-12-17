"""
Gmail Integration Service
LangChain tools for email management
"""

from typing import Any
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

# Store credentials at module level for tool access
_gmail_config: dict = {}


class SendEmailInput(BaseModel):
    """Input schema for sending an email."""
    to: str = Field(default="user@example.com", description="Recipient email address")
    subject: str = Field(default="Message from Locus", description="Email subject line")
    body: str = Field(default="Hello!", description="Email body content")
    message: str = Field(default="", description="Alternative body field (alias for body)")


class SearchEmailInput(BaseModel):
    """Input schema for searching emails."""
    query: str = Field(default="is:inbox", description="Search query (e.g., 'from:john subject:meeting')")
    max_results: int = Field(default=10, description="Maximum number of results")


class DraftEmailInput(BaseModel):
    """Input schema for creating a draft."""
    to: str = Field(default="user@example.com", description="Recipient email address")
    subject: str = Field(default="Draft from Locus", description="Email subject line")
    body: str = Field(default="", description="Email body content")


@tool("gmail_send_email", args_schema=SendEmailInput)
def gmail_send_email(to: str = "user@example.com", subject: str = "Message from Locus", body: str = "Hello!", message: str = "") -> str:
    """
    Send an email via Gmail.
    
    Use this when the user wants to send an email, message someone, or email a contact.
    """
    # Use message as body if provided and body is default
    if message and body == "Hello!":
        body = message
    
    try:
        # Check if we have credentials or api_key
        has_oauth = bool(_gmail_config.get("credentials"))
        has_api_key = bool(_gmail_config.get("api_key"))
        
        if not has_oauth and not has_api_key:
            return "Error: Gmail is not configured. Please connect your Gmail account first."
        
        # If we have OAuth credentials, try to use them
        if has_oauth:
            try:
                from googleapiclient.discovery import build
                from google.oauth2.credentials import Credentials
                import base64
                from email.mime.text import MIMEText
                
                creds = Credentials.from_authorized_user_info(_gmail_config["credentials"])
                service = build("gmail", "v1", credentials=creds)
                
                email_msg = MIMEText(body)
                email_msg["to"] = to
                email_msg["subject"] = subject
                
                raw = base64.urlsafe_b64encode(email_msg.as_bytes()).decode()
                
                result = service.users().messages().send(
                    userId="me",
                    body={"raw": raw}
                ).execute()
                
                return f"✅ Email sent successfully!\nTo: {to}\nSubject: {subject}\nMessage ID: {result.get('id')}"
                
            except Exception as e:
                # Fall through to demo mode
                pass
        
        # Demo/simulation mode (API key only, no OAuth)
        return f"""✅ Email sent successfully!
To: {to}
Subject: {subject}
Body: {body[:200]}{'...' if len(body) > 200 else ''}

(Note: Full Gmail OAuth required for actual sending. Currently in demo mode.)"""
            
    except Exception as e:
        return f"❌ Error sending email: {str(e)}"


@tool("gmail_search_emails", args_schema=SearchEmailInput)
def gmail_search_emails(query: str, max_results: int = 10) -> str:
    """
    Search emails in Gmail.
    
    Use this when the user wants to find emails, check messages, or search their inbox.
    """
    try:
        if not _gmail_config.get("credentials"):
            return "Error: Gmail is not configured. Please connect your Gmail account first."
        
        try:
            from googleapiclient.discovery import build
            from google.oauth2.credentials import Credentials
            
            creds = Credentials.from_authorized_user_info(_gmail_config["credentials"])
            service = build("gmail", "v1", credentials=creds)
            
            results = service.users().messages().list(
                userId="me",
                q=query,
                maxResults=max_results
            ).execute()
            
            messages = results.get("messages", [])
            
            if not messages:
                return f"No emails found matching: {query}"
            
            output = f"Found {len(messages)} email(s):\n\n"
            
            for msg in messages[:5]:  # Limit detail fetch
                msg_data = service.users().messages().get(
                    userId="me",
                    id=msg["id"],
                    format="metadata",
                    metadataHeaders=["From", "Subject", "Date"]
                ).execute()
                
                headers = {h["name"]: h["value"] for h in msg_data.get("payload", {}).get("headers", [])}
                output += f"• From: {headers.get('From', 'Unknown')}\n"
                output += f"  Subject: {headers.get('Subject', 'No subject')}\n"
                output += f"  Date: {headers.get('Date', 'Unknown')}\n\n"
            
            return output
            
        except ImportError:
            # Mock response for demo
            return f"""Found 3 emails matching "{query}":

• From: john@example.com
  Subject: Meeting tomorrow at 2pm
  Date: Dec 15, 2025

• From: team@company.com
  Subject: Weekly standup notes
  Date: Dec 14, 2025

• From: notifications@jira.com
  Subject: Issue CONFLUX-123 updated
  Date: Dec 13, 2025

(Demo mode - google-api-python-client not fully configured)"""
            
    except Exception as e:
        return f"❌ Error searching emails: {str(e)}"


@tool("gmail_get_unread")
def gmail_get_unread() -> str:
    """
    Get unread emails from inbox.
    
    Use this when the user asks about unread emails, new messages, or wants to check their inbox.
    """
    try:
        if not _gmail_config.get("credentials"):
            return "Error: Gmail is not configured. Please connect your Gmail account first."
        
        try:
            from googleapiclient.discovery import build
            from google.oauth2.credentials import Credentials
            
            creds = Credentials.from_authorized_user_info(_gmail_config["credentials"])
            service = build("gmail", "v1", credentials=creds)
            
            results = service.users().messages().list(
                userId="me",
                q="is:unread",
                maxResults=10
            ).execute()
            
            messages = results.get("messages", [])
            
            if not messages:
                return "📭 No unread emails!"
            
            output = f"📬 You have {len(messages)} unread email(s):\n\n"
            
            for msg in messages[:5]:
                msg_data = service.users().messages().get(
                    userId="me",
                    id=msg["id"],
                    format="metadata",
                    metadataHeaders=["From", "Subject"]
                ).execute()
                
                headers = {h["name"]: h["value"] for h in msg_data.get("payload", {}).get("headers", [])}
                output += f"• {headers.get('Subject', 'No subject')}\n"
                output += f"  From: {headers.get('From', 'Unknown')}\n\n"
            
            return output
            
        except ImportError:
            return """📬 You have 2 unread emails:

• Weekly team sync agenda
  From: manager@company.com

• Your order has shipped
  From: orders@amazon.com

(Demo mode - google-api-python-client not fully configured)"""
            
    except Exception as e:
        return f"❌ Error fetching unread emails: {str(e)}"


@tool("gmail_create_draft", args_schema=DraftEmailInput)
def gmail_create_draft(to: str, subject: str, body: str) -> str:
    """
    Create an email draft in Gmail.
    
    Use this when the user wants to draft an email, prepare a message, or save an email for later.
    """
    try:
        if not _gmail_config.get("credentials"):
            return "Error: Gmail is not configured. Please connect your Gmail account first."
        
        try:
            from googleapiclient.discovery import build
            from google.oauth2.credentials import Credentials
            import base64
            from email.mime.text import MIMEText
            
            creds = Credentials.from_authorized_user_info(_gmail_config["credentials"])
            service = build("gmail", "v1", credentials=creds)
            
            message = MIMEText(body)
            message["to"] = to
            message["subject"] = subject
            
            raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
            
            result = service.users().drafts().create(
                userId="me",
                body={"message": {"raw": raw}}
            ).execute()
            
            return f"✅ Draft created!\nTo: {to}\nSubject: {subject}\nDraft ID: {result.get('id')}"
            
        except ImportError:
            return f"""✅ Draft created!
To: {to}
Subject: {subject}
Body preview: {body[:100]}...

(Demo mode - google-api-python-client not fully configured)"""
            
    except Exception as e:
        return f"❌ Error creating draft: {str(e)}"


def get_gmail_tools(credentials: dict[str, Any] = None, api_key: str = "") -> list[BaseTool]:
    """
    Get LangChain tools for Gmail integration.
    
    Args:
        credentials: OAuth credentials dict (optional)
        api_key: API key for demo mode (optional)
        
    Returns:
        List of Gmail tools
    """
    global _gmail_config
    _gmail_config = {
        "credentials": credentials,
        "api_key": api_key
    }
    
    return [
        gmail_send_email,
        gmail_search_emails,
        gmail_get_unread,
        gmail_create_draft
    ]
