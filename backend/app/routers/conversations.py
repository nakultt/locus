"""
Conversations Router
Manage chat conversations and message history
"""

import json
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import schemas, crud
from app.database import get_db

router = APIRouter()


@router.post(
    "/conversations",
    response_model=schemas.ConversationResponse,
    summary="Create a new conversation"
)
async def create_conversation(
    request: schemas.ConversationCreate,
    db: Session = Depends(get_db)
) -> schemas.ConversationResponse:
    """Create a new conversation for a user."""
    # Validate user exists
    user = crud.get_user_by_id(db, request.user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    conversation = crud.create_conversation(
        db=db,
        user_id=request.user_id,
        title=request.title or "New Chat"
    )
    return conversation


@router.get(
    "/conversations/{user_id}",
    response_model=schemas.ConversationList,
    summary="Get user's conversations"
)
async def get_user_conversations(
    user_id: int,
    db: Session = Depends(get_db)
) -> schemas.ConversationList:
    """Get all conversations for a user, ordered by most recent."""
    # Validate user exists
    user = crud.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    conversations = crud.get_user_conversations(db, user_id)
    return schemas.ConversationList(
        conversations=conversations,
        total=len(conversations)
    )


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=list[schemas.MessageResponse],
    summary="Get messages for a conversation"
)
async def get_conversation_messages(
    conversation_id: int,
    db: Session = Depends(get_db)
) -> list[schemas.MessageResponse]:
    """Get all messages for a conversation."""
    conversation = crud.get_conversation(db, conversation_id)
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found"
        )
    
    messages = crud.get_conversation_messages(db, conversation_id)
    
    # Convert messages to response format with parsed actions
    result = []
    for msg in messages:
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
            created_at=msg.created_at
        ))
    
    return result


@router.put(
    "/conversations/{conversation_id}",
    response_model=schemas.ConversationResponse,
    summary="Update conversation title"
)
async def update_conversation(
    conversation_id: int,
    request: schemas.ConversationUpdate,
    db: Session = Depends(get_db)
) -> schemas.ConversationResponse:
    """Update a conversation's title."""
    conversation = crud.update_conversation_title(
        db=db,
        conversation_id=conversation_id,
        title=request.title
    )
    
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found"
        )
    
    return conversation


@router.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a conversation"
)
async def delete_conversation(
    conversation_id: int,
    db: Session = Depends(get_db)
):
    """Delete a conversation and all its messages."""
    deleted = crud.delete_conversation(db, conversation_id)
    
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found"
        )
    
    return None
