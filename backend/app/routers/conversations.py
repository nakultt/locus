"""
Conversations Router
Chat history, scoped to the authenticated user.

Every lookup is filtered by owner. Previously these routes took a conversation
id with no ownership check, so any caller could read, retitle, or delete
another user's chats.
"""

import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import crud, models, schemas
from app.core.database import get_db
from app.core.dependencies import get_current_user

router = APIRouter()


def _owned_conversation(
    db: Session, conversation_id: int, user_id: int
) -> models.Conversation:
    """
    Fetch a conversation the caller owns.

    Returns 404 rather than 403 for someone else's conversation: a 403 would
    confirm the id exists, letting a caller enumerate other users' chats.
    """
    conversation = crud.get_conversation(db, conversation_id)
    if not conversation or conversation.owner_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )
    return conversation


@router.post(
    "/conversations",
    response_model=schemas.ConversationResponse,
    summary="Create a new conversation",
)
async def create_conversation(
    request: schemas.ConversationCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> schemas.ConversationResponse:
    """Create a conversation owned by the authenticated user."""
    return crud.create_conversation(
        db=db, user_id=current_user.id, title=request.title or "New Chat"
    )


@router.get(
    "/conversations",
    response_model=schemas.ConversationList,
    summary="Your conversations",
)
async def get_conversations(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> schemas.ConversationList:
    """List the authenticated user's conversations, most recent first."""
    conversations = crud.get_user_conversations(db, current_user.id)
    return schemas.ConversationList(
        conversations=conversations, total=len(conversations)
    )


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=list[schemas.MessageResponse],
    summary="Messages in a conversation",
)
async def get_conversation_messages(
    conversation_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[schemas.MessageResponse]:
    """Get all messages in one of the caller's conversations."""
    _owned_conversation(db, conversation_id, current_user.id)

    result = []
    for msg in crud.get_conversation_messages(db, conversation_id):
        actions_taken = None
        if msg.actions_json:
            try:
                actions_taken = json.loads(msg.actions_json)
            except json.JSONDecodeError:
                actions_taken = None

        result.append(schemas.MessageResponse(
            id=msg.id,
            conversation_id=msg.conversation_id,
            role=msg.role,
            content=msg.content,
            actions_taken=actions_taken,
            created_at=msg.created_at,
        ))

    return result


@router.put(
    "/conversations/{conversation_id}",
    response_model=schemas.ConversationResponse,
    summary="Rename a conversation",
)
async def update_conversation(
    conversation_id: int,
    request: schemas.ConversationUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> schemas.ConversationResponse:
    """Rename one of the caller's conversations."""
    _owned_conversation(db, conversation_id, current_user.id)
    return crud.update_conversation_title(
        db=db, conversation_id=conversation_id, title=request.title
    )


@router.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a conversation",
)
async def delete_conversation(
    conversation_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Delete one of the caller's conversations and all its messages."""
    _owned_conversation(db, conversation_id, current_user.id)
    crud.delete_conversation(db, conversation_id)
