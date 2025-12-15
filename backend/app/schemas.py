"""
Pydantic Schemas
Request/Response validation models
"""

from datetime import datetime
from typing import Optional, Any
from pydantic import BaseModel, EmailStr, Field


# ============== User Schemas ==============

class UserCreate(BaseModel):
    """Schema for user registration."""
    email: EmailStr
    password: str = Field(..., min_length=6, description="Password must be at least 6 characters")


class UserResponse(BaseModel):
    """Schema for user response (excludes password)."""
    id: int
    email: str
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class UserLogin(BaseModel):
    """Schema for user login."""
    email: EmailStr
    password: str


# ============== Integration Schemas ==============

class IntegrationCreate(BaseModel):
    """Schema for connecting a new integration."""
    user_id: int
    service_name: str = Field(
        ...,
        description="Service name: jira, gmail, calendar, slack, notion"
    )
    api_key: Optional[str] = Field(None, description="API key for simple auth")
    credentials: Optional[dict[str, Any]] = Field(
        None,
        description="OAuth credentials or complex auth config"
    )


class IntegrationResponse(BaseModel):
    """Schema for integration response."""
    id: int
    service_name: str
    owner_id: int
    created_at: Optional[datetime] = None
    is_connected: bool = True

    class Config:
        from_attributes = True


class IntegrationList(BaseModel):
    """Schema for listing user integrations."""
    integrations: list[IntegrationResponse]
    total: int


# ============== Chat Schemas ==============

class ChatRequest(BaseModel):
    """Schema for chat message request."""
    user_id: int
    message: str = Field(..., min_length=1, description="User's natural language command")


class ActionResult(BaseModel):
    """Schema for individual action result."""
    service: str
    action: str
    success: bool
    result: Optional[Any] = None
    error: Optional[str] = None


class ChatResponse(BaseModel):
    """Schema for chat response."""
    message: str
    actions_taken: list[ActionResult] = []
    raw_response: Optional[str] = None


# ============== Error Schemas ==============

class ErrorResponse(BaseModel):
    """Schema for error responses."""
    detail: str
    error_code: Optional[str] = None
