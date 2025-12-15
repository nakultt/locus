"""
Chat Router
Natural language command processing via LangChain agent
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import schemas, crud
from app.database import get_db
from app.services.agent import process_chat_message

router = APIRouter()


@router.post(
    "/chat",
    response_model=schemas.ChatResponse,
    summary="Process natural language commands"
)
async def chat(
    request: schemas.ChatRequest,
    db: Session = Depends(get_db)
) -> schemas.ChatResponse:
    """
    Process a natural language message and execute actions across integrated tools.
    
    Example messages:
    - "Create a Jira ticket for login bug"
    - "Send an email to john@example.com about the meeting"
    - "Schedule a meeting tomorrow at 2pm"
    - "Post 'Build complete' to #dev-updates on Slack"
    - "What's in my Notion project docs?"
    
    The system will:
    1. Parse the intent from the message
    2. Identify required integrations
    3. Execute actions using connected tools
    4. Return structured results
    """
    # Validate user exists
    user = crud.get_user_by_id(db, request.user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Get user's connected integrations
    integrations = crud.get_user_integrations(db, request.user_id)
    if not integrations:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No integrations connected. Please connect at least one service first."
        )
    
    # Build integration credentials map
    integration_configs: dict[str, dict] = {}
    for integration in integrations:
        config = {}
        
        # Get decrypted API key
        api_key = crud.get_integration_key(db, request.user_id, integration.service_name)
        if api_key:
            config["api_key"] = api_key
        
        # Get decrypted credentials
        credentials = crud.get_integration_credentials(db, request.user_id, integration.service_name)
        if credentials:
            config["credentials"] = credentials
        
        if config:
            integration_configs[integration.service_name] = config
    
    try:
        # Process message through LangChain agent
        result = await process_chat_message(
            message=request.message,
            integration_configs=integration_configs
        )
        return result
    except ValueError as e:
        # Specific integration not connected
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        # General error
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing request: {str(e)}"
        )


@router.get(
    "/supported-commands",
    summary="Get list of supported commands"
)
async def supported_commands() -> dict:
    """Get examples of supported natural language commands."""
    return {
        "services": {
            "jira": {
                "description": "Atlassian Jira for issue tracking",
                "example_commands": [
                    "Create a Jira ticket for [issue description]",
                    "Search for Jira issues about [topic]",
                    "What are my open Jira tickets?"
                ]
            },
            "gmail": {
                "description": "Gmail for email management",
                "example_commands": [
                    "Send an email to [recipient] about [subject]",
                    "Check my unread emails",
                    "Draft an email to [recipient]"
                ]
            },
            "calendar": {
                "description": "Google Calendar for scheduling",
                "example_commands": [
                    "Schedule a meeting [when] with [who]",
                    "What's on my calendar today?",
                    "Create an event for [description] on [date]"
                ]
            },
            "slack": {
                "description": "Slack for team communication",
                "example_commands": [
                    "Send '[message]' to #[channel]",
                    "Post an update to #[channel]",
                    "Message [person] on Slack"
                ]
            },
            "notion": {
                "description": "Notion for documentation",
                "example_commands": [
                    "Search my Notion for [topic]",
                    "What's in my [page name] Notion page?",
                    "Find Notion docs about [subject]"
                ]
            }
        }
    }
