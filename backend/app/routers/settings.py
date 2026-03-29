"""
User Settings Router
Handles user settings including Gemini API key management
"""

from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app import crud, schemas

router = APIRouter()


@router.post(
    "/gemini-key",
    response_model=schemas.GeminiKeyStatus,
    summary="Set user's Gemini API key"
)
async def set_gemini_key(
    request: schemas.GeminiKeySet,
    db: Session = Depends(get_db)
) -> schemas.GeminiKeyStatus:
    """
    Set or update user's Gemini API key.
    The key is encrypted before storage.
    """
    success = crud.set_user_gemini_key(db, request.user_id, request.api_key)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    return schemas.GeminiKeyStatus(
        has_key=True,
        message="Gemini API key saved successfully"
    )


@router.get(
    "/gemini-key/{user_id}",
    response_model=schemas.GeminiKeyStatus,
    summary="Check if user has Gemini API key"
)
async def check_gemini_key(
    user_id: int,
    db: Session = Depends(get_db)
) -> schemas.GeminiKeyStatus:
    """
    Check if a user has configured their Gemini API key.
    Does not return the actual key for security.
    """
    user = crud.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    has_key = crud.has_gemini_key(db, user_id)
    
    return schemas.GeminiKeyStatus(
        has_key=has_key,
        message="Gemini API key is configured" if has_key else "No Gemini API key configured"
    )


@router.delete(
    "/gemini-key/{user_id}",
    response_model=schemas.GeminiKeyStatus,
    summary="Delete user's Gemini API key"
)
async def delete_gemini_key(
    user_id: int,
    db: Session = Depends(get_db)
) -> schemas.GeminiKeyStatus:
    """
    Delete user's Gemini API key.
    """
    user = crud.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    crud.delete_user_gemini_key(db, user_id)
    
    return schemas.GeminiKeyStatus(
        has_key=False,
        message="Gemini API key deleted"
    )
