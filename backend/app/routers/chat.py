"""
Chat Router
Natural language command processing via LangChain agent
"""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app import crud, models, schemas
from app.database import get_db
from app.dependencies import get_current_user, get_integration_configs
from app.services.agent import process_chat_message, process_chat_message_streaming
from app.services.llm import check_llm_available

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/chat",
    response_model=schemas.ChatResponse,
    summary="Process natural language commands"
)
async def chat(
    request: schemas.ChatRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
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
    # Get or create conversation
    conversation_id = request.conversation_id
    if conversation_id:
        # Validate conversation exists and belongs to user
        conversation = crud.get_conversation(db, conversation_id)
        if not conversation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found"
            )
        if conversation.owner_id != current_user.id:
            # 404 rather than 403: a 403 confirms the id exists.
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found"
            )
    else:
        # Create new conversation with first few words of message as title
        title = request.message[:50] + "..." if len(request.message) > 50 else request.message
        conversation = crud.create_conversation(db, current_user.id, title)
        conversation_id = conversation.id
    
    # Load prior turns BEFORE saving the current one, otherwise the new message
    # is replayed to the agent twice.
    history = [
        (m.role, m.content)
        for m in crud.get_conversation_messages(db, conversation_id)
    ]

    # Save user message to database
    crud.add_message(
        db=db,
        conversation_id=conversation_id,
        role="user",
        content=request.message
    )
    
    # Get user's connected integrations
    integrations = crud.get_user_integrations(db, current_user.id)
    if not integrations:
        # Save error as assistant message
        error_msg = "No integrations connected. Please connect at least one service first."
        crud.add_message(
            db=db,
            conversation_id=conversation_id,
            role="assistant",
            content=error_msg
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_msg
        )
    
    integration_configs = get_integration_configs(db, current_user.id)
    
    # Verify the local model server is up with a model loaded
    llm_ready, llm_message = await check_llm_available()
    if not llm_ready:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=llm_message
        )

    try:
        # Process message through LangChain agent
        result = await process_chat_message(
            message=request.message,
            integration_configs=integration_configs,
            smart_mode=request.smart_mode,
            history=history,
            timezone=current_user.timezone,
        )
        
        # Save assistant response to database
        actions_json = None
        if result.actions_taken:
            actions_json = json.dumps([action.model_dump() for action in result.actions_taken])
        
        crud.add_message(
            db=db,
            conversation_id=conversation_id,
            role="assistant",
            content=result.message,
            actions_json=actions_json
        )
        
        # Return response with conversation_id
        return schemas.ChatResponse(
            message=result.message,
            actions_taken=result.actions_taken,
            raw_response=result.raw_response,
            conversation_id=conversation_id
        )
    except ValueError as e:
        # Specific integration not connected
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        ) from e
    except Exception as e:
        # General error
        # Log the detail server-side; upstream API errors can carry internals
        # that should not be returned to the client.
        logger.exception("Chat processing failed for user %s", current_user.id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error processing request. Check server logs for details."
        ) from e


@router.post(
    "/chat/stream",
    summary="Process commands with real-time task updates"
)
async def chat_stream(
    request: schemas.ChatRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Process a natural language message with streaming task updates.
    
    Returns Server-Sent Events (SSE) for real-time progress:
    - planning: Initial analysis status
    - plan: Full task plan with all identified tasks
    - task_started: When each task begins
    - task_completed: When each task finishes successfully
    - task_failed: When a task fails
    - complete: Final response with all results
    - error: If something goes wrong
    """
    # Validate user exists
    user = crud.get_user_by_id(db, current_user.id)
    if not user:
        async def error_generator():
            yield f"data: {json.dumps({'event_type': 'error', 'data': {'message': 'User not found'}})}\n\n"
        return StreamingResponse(
            error_generator(),
            media_type="text/event-stream"
        )
    
    # Get or create conversation
    conversation_id = request.conversation_id
    if conversation_id:
        # Validate conversation exists and belongs to user
        conversation = crud.get_conversation(db, conversation_id)
        if not conversation:
            async def error_generator():
                yield f"data: {json.dumps({'event_type': 'error', 'data': {'message': 'Conversation not found'}})}\n\n"
            return StreamingResponse(
                error_generator(),
                media_type="text/event-stream"
            )
        if conversation.owner_id != current_user.id:
            async def error_generator():
                yield f"data: {json.dumps({'event_type': 'error', 'data': {'message': 'Conversation does not belong to user'}})}\n\n"
            return StreamingResponse(
                error_generator(),
                media_type="text/event-stream"
            )
    else:
        # Create new conversation with first few words of message as title
        title = request.message[:50] + "..." if len(request.message) > 50 else request.message
        conversation = crud.create_conversation(db, current_user.id, title)
        conversation_id = conversation.id
    
    # Load prior turns BEFORE saving the current one, otherwise the new message
    # is replayed to the agent twice.
    history = [
        (m.role, m.content)
        for m in crud.get_conversation_messages(db, conversation_id)
    ]

    # Save user message to database
    crud.add_message(
        db=db,
        conversation_id=conversation_id,
        role="user",
        content=request.message
    )
    
    # Get user's connected integrations
    integrations = crud.get_user_integrations(db, current_user.id)
    if not integrations:
        # Save error as assistant message
        error_msg = "No integrations connected. Please connect at least one service first."
        crud.add_message(
            db=db,
            conversation_id=conversation_id,
            role="assistant",
            content=error_msg
        )
        async def error_generator():
            yield f"data: {json.dumps({'event_type': 'error', 'data': {'message': error_msg}})}\n\n"
        return StreamingResponse(
            error_generator(),
            media_type="text/event-stream"
        )
    
    integration_configs = get_integration_configs(db, current_user.id)
    
    # Verify the local model server is up with a model loaded
    llm_ready, llm_message = await check_llm_available()
    if not llm_ready:
        async def error_generator():
            yield f"data: {json.dumps({'event_type': 'error', 'data': {'message': llm_message}})}\n\n"
        return StreamingResponse(
            error_generator(),
            media_type="text/event-stream"
        )
    
    async def event_generator():
        """Generate SSE events from the streaming chat processor."""
        final_message = ""
        actions_taken = []
        
        try:
            async for event in process_chat_message_streaming(
                message=request.message,
                integration_configs=integration_configs,
                history=history,
                timezone=current_user.timezone,
            ):
                # Capture final message and actions from complete event
                if event.get("event_type") == "complete":
                    data = event.get("data", {})
                    final_message = data.get("message", "")
                    actions_taken = data.get("actions_taken", [])
                
                # Include conversation_id in events
                if "data" not in event:
                    event["data"] = {}
                event["data"]["conversation_id"] = conversation_id
                
                yield f"data: {json.dumps(event)}\n\n"
            
            # Save assistant response to database after streaming completes
            actions_json = None
            if actions_taken:
                actions_json = json.dumps(actions_taken)
            
            crud.add_message(
                db=db,
                conversation_id=conversation_id,
                role="assistant",
                content=final_message or "Task completed.",
                actions_json=actions_json
            )
            
        except Exception as e:
            # Save error as assistant message
            error_msg = str(e)
            crud.add_message(
                db=db,
                conversation_id=conversation_id,
                role="assistant",
                content=f"Error: {error_msg}"
            )
            yield f"data: {json.dumps({'event_type': 'error', 'data': {'message': error_msg, 'conversation_id': conversation_id}})}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        }
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
