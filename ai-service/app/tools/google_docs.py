"""
Google Docs Integration Service
LangChain tools for document management using direct HTTP API calls
"""

import httpx
from typing import Any
from datetime import datetime, timedelta
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

# Store credentials at module level for tool access
_docs_config: dict = {}

# Google Docs API base URL
DOCS_API_BASE = "https://docs.googleapis.com/v1/documents"

# Google OAuth token refresh URL
TOKEN_REFRESH_URL = "https://oauth2.googleapis.com/token"


class CreateDocInput(BaseModel):
    """Input schema for creating a document."""
    title: str = Field(description="Document title")
    content: str = Field(default="", description="Initial document content (plain text)")


class AppendToDocInput(BaseModel):
    """Input schema for appending content to a document."""
    document_id: str = Field(description="The document ID to append content to")
    content: str = Field(description="Content to append to the document")


def _is_token_expired() -> bool:
    """Check if the current access token is expired."""
    credentials = _docs_config.get("credentials", {})
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
    credentials = _docs_config.get("credentials", {})
    refresh_token = credentials.get("refresh_token")
    client_id = _docs_config.get("client_id")
    client_secret = _docs_config.get("client_secret")
    
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
            _docs_config["credentials"]["access_token"] = tokens.get("access_token")
            _docs_config["credentials"]["expires_in"] = tokens.get("expires_in", 3600)
            _docs_config["credentials"]["obtained_at"] = datetime.utcnow().isoformat()
            return True
    except Exception:
        return False


def _get_access_token() -> str | None:
    """Get a valid access token, refreshing if necessary."""
    if _is_token_expired():
        if not _refresh_token():
            return None
    
    return _docs_config.get("credentials", {}).get("access_token")


def _get_auth_headers() -> dict | None:
    """Get authorization headers for API requests."""
    access_token = _get_access_token()
    if not access_token:
        return None
    
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }


@tool("docs_create_document", args_schema=CreateDocInput)
def docs_create_document(title: str, content: str = "") -> str:
    """
    Create a new Google Doc.
    
    Use this when the user wants to create a document, write a doc, or start a new document.
    """
    try:
        headers = _get_auth_headers()
        if not headers:
            return "Error: Google Docs is not configured or token expired. Please reconnect your Google account."
        
        with httpx.Client() as client:
            # Create document
            create_response = client.post(
                DOCS_API_BASE,
                headers=headers,
                json={"title": title}
            )
            
            if create_response.status_code not in [200, 201]:
                error_detail = create_response.json().get("error", {}).get("message", "Unknown error")
                return f"❌ Failed to create document: {error_detail}"
            
            doc = create_response.json()
            doc_id = doc.get("documentId")
            
            # Add content if provided
            if content:
                update_response = client.post(
                    f"{DOCS_API_BASE}/{doc_id}:batchUpdate",
                    headers=headers,
                    json={
                        "requests": [
                            {
                                "insertText": {
                                    "location": {"index": 1},
                                    "text": content
                                }
                            }
                        ]
                    }
                )
                
                if update_response.status_code != 200:
                    return f"""✅ Document created but content could not be added.
📄 Title: {title}
🆔 Document ID: {doc_id}
🔗 https://docs.google.com/document/d/{doc_id}/edit"""
            
            return f"""✅ Document created successfully!
📄 Title: {title}
🆔 Document ID: {doc_id}
🔗 https://docs.google.com/document/d/{doc_id}/edit"""
                
    except Exception as e:
        return f"❌ Error creating document: {str(e)}"


@tool("docs_append_content", args_schema=AppendToDocInput)
def docs_append_content(document_id: str, content: str) -> str:
    """
    Append content to an existing Google Doc.
    
    Use this when the user wants to add text to a document or update a document.
    """
    try:
        headers = _get_auth_headers()
        if not headers:
            return "Error: Google Docs is not configured or token expired. Please reconnect your Google account."
        
        with httpx.Client() as client:
            # Get document to find end index
            get_response = client.get(
                f"{DOCS_API_BASE}/{document_id}",
                headers=headers
            )
            
            if get_response.status_code == 404:
                return f"❌ Document not found: {document_id}"
            elif get_response.status_code != 200:
                error_detail = get_response.json().get("error", {}).get("message", "Unknown error")
                return f"❌ Failed to access document: {error_detail}"
            
            doc = get_response.json()
            end_index = doc.get("body", {}).get("content", [{}])[-1].get("endIndex", 1) - 1
            
            # Append content
            update_response = client.post(
                f"{DOCS_API_BASE}/{document_id}:batchUpdate",
                headers=headers,
                json={
                    "requests": [
                        {
                            "insertText": {
                                "location": {"index": max(1, end_index)},
                                "text": f"\n{content}"
                            }
                        }
                    ]
                }
            )
            
            if update_response.status_code == 200:
                return f"""✅ Content appended successfully!
🆔 Document ID: {document_id}
🔗 https://docs.google.com/document/d/{document_id}/edit"""
            else:
                error_detail = update_response.json().get("error", {}).get("message", "Unknown error")
                return f"❌ Failed to append content: {error_detail}"
                
    except Exception as e:
        return f"❌ Error appending content: {str(e)}"


def get_docs_tools(credentials: dict[str, Any] = None) -> list[BaseTool]:
    """
    Get LangChain tools for Google Docs integration.
    
    Args:
        credentials: OAuth credentials dict containing access_token, refresh_token, etc.
        
    Returns:
        List of Google Docs tools
    """
    global _docs_config
    
    import os
    _docs_config = {
        "credentials": credentials,
        "client_id": os.getenv("GOOGLE_CLIENT_ID", ""),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET", ""),
    }
    
    return [
        docs_create_document,
        docs_append_content,
    ]
