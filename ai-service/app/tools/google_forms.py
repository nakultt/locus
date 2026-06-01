"""
Google Forms Integration Service
LangChain tools for form creation using direct HTTP API calls
"""

import httpx
from typing import Any
from datetime import datetime, timedelta
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

# Store credentials at module level for tool access
_forms_config: dict = {}

# Google Forms API base URL
FORMS_API_BASE = "https://forms.googleapis.com/v1/forms"

# Google OAuth token refresh URL
TOKEN_REFRESH_URL = "https://oauth2.googleapis.com/token"


class CreateFormInput(BaseModel):
    """Input schema for creating a form."""
    title: str = Field(description="Form title")
    questions: str = Field(
        description="Semicolon-separated questions. Prefix with type: '[choice]' for multiple choice, '[text]' for text (default). Example: '[choice]What color?:Red,Blue,Green;[text]Your name?'"
    )


def _is_token_expired() -> bool:
    """Check if the current access token is expired."""
    credentials = _forms_config.get("credentials", {})
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
    credentials = _forms_config.get("credentials", {})
    refresh_token = credentials.get("refresh_token")
    client_id = _forms_config.get("client_id")
    client_secret = _forms_config.get("client_secret")
    
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
            _forms_config["credentials"]["access_token"] = tokens.get("access_token")
            _forms_config["credentials"]["expires_in"] = tokens.get("expires_in", 3600)
            _forms_config["credentials"]["obtained_at"] = datetime.utcnow().isoformat()
            return True
    except Exception:
        return False


def _get_access_token() -> str | None:
    """Get a valid access token, refreshing if necessary."""
    if _is_token_expired():
        if not _refresh_token():
            return None
    
    return _forms_config.get("credentials", {}).get("access_token")


def _get_auth_headers() -> dict | None:
    """Get authorization headers for API requests."""
    access_token = _get_access_token()
    if not access_token:
        return None
    
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }


def _parse_question(question_str: str) -> dict:
    """Parse a question string into a form item."""
    question_str = question_str.strip()
    
    # Default to text question
    q_type = "text"
    options = []
    
    # Check for type prefix
    if question_str.startswith("[choice]"):
        q_type = "choice"
        question_str = question_str[8:].strip()
    elif question_str.startswith("[text]"):
        q_type = "text"
        question_str = question_str[6:].strip()
    
    # Parse options for choice questions
    if ":" in question_str and q_type == "choice":
        parts = question_str.split(":", 1)
        question_text = parts[0].strip()
        options = [opt.strip() for opt in parts[1].split(",") if opt.strip()]
    else:
        question_text = question_str
    
    # Build the item
    if q_type == "choice" and options:
        return {
            "title": question_text,
            "questionItem": {
                "question": {
                    "required": False,
                    "choiceQuestion": {
                        "type": "RADIO",
                        "options": [{"value": opt} for opt in options]
                    }
                }
            }
        }
    else:
        return {
            "title": question_text,
            "questionItem": {
                "question": {
                    "required": False,
                    "textQuestion": {
                        "paragraph": False
                    }
                }
            }
        }


@tool("forms_create_form", args_schema=CreateFormInput)
def forms_create_form(title: str, questions: str) -> str:
    """
    Create a new Google Form with questions.
    
    Use this when the user wants to create a form, survey, questionnaire, or poll.
    """
    try:
        headers = _get_auth_headers()
        if not headers:
            return "Error: Google Forms is not configured or token expired. Please reconnect your Google account."
        
        with httpx.Client() as client:
            # Create form
            create_response = client.post(
                FORMS_API_BASE,
                headers=headers,
                json={
                    "info": {"title": title}
                }
            )
            
            if create_response.status_code not in [200, 201]:
                error_detail = create_response.json().get("error", {}).get("message", "Unknown error")
                return f"❌ Failed to create form: {error_detail}"
            
            form = create_response.json()
            form_id = form.get("formId")
            
            # Parse and add questions
            if questions:
                question_list = [q.strip() for q in questions.split(";") if q.strip()]
                requests = []
                
                for i, q in enumerate(question_list):
                    item = _parse_question(q)
                    requests.append({
                        "createItem": {
                            "item": item,
                            "location": {"index": i}
                        }
                    })
                
                if requests:
                    update_response = client.post(
                        f"{FORMS_API_BASE}/{form_id}:batchUpdate",
                        headers=headers,
                        json={"requests": requests}
                    )
                    
                    if update_response.status_code != 200:
                        return f"""✅ Form created but questions could not be added.
📋 Title: {title}
🆔 Form ID: {form_id}
🔗 https://docs.google.com/forms/d/{form_id}/edit"""
            
            question_count = len([q for q in questions.split(";") if q.strip()]) if questions else 0
            return f"""✅ Form created successfully!
📋 Title: {title}
❓ Questions: {question_count}
🆔 Form ID: {form_id}
✏️ Edit: https://docs.google.com/forms/d/{form_id}/edit
📝 Share: https://docs.google.com/forms/d/{form_id}/viewform"""
                
    except Exception as e:
        return f"❌ Error creating form: {str(e)}"


def get_forms_tools(credentials: dict[str, Any] = None) -> list[BaseTool]:
    """
    Get LangChain tools for Google Forms integration.
    
    Args:
        credentials: OAuth credentials dict containing access_token, refresh_token, etc.
        
    Returns:
        List of Google Forms tools
    """
    global _forms_config
    
    import os
    _forms_config = {
        "credentials": credentials,
        "client_id": os.getenv("GOOGLE_CLIENT_ID", ""),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET", ""),
    }
    
    return [
        forms_create_form,
    ]
