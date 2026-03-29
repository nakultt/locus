"""
Pydantic Schemas
Request/Response validation models
"""

from datetime import datetime
from typing import Optional, Any
from enum import Enum
from pydantic import BaseModel, EmailStr, Field


# ============== User Schemas ==============

class UserCreate(BaseModel):
    """Schema for user registration."""
    email: EmailStr
    password: str = Field(..., min_length=6, description="Password must be at least 6 characters")
    name: Optional[str] = Field(None, description="User's display name")


class UserUpdate(BaseModel):
    """Schema for updating user details."""
    email: Optional[EmailStr] = None
    password: Optional[str] = Field(None, min_length=6, description="New password")
    name: Optional[str] = None


class UserResponse(BaseModel):
    """Schema for user response (excludes password)."""
    id: int
    email: str
    name: Optional[str] = None
    created_at: Optional[datetime] = None
    token: Optional[str] = Field(None, description="JWT access token")
    has_gemini_key: bool = Field(False, description="Whether user has configured Gemini API key")

    class Config:
        from_attributes = True


class UserLogin(BaseModel):
    """Schema for user login."""
    email: EmailStr
    password: str
    remember_me: bool = Field(False, description="Keep user logged in for 30 days")


class GeminiKeySet(BaseModel):
    """Schema for setting Gemini API key."""
    user_id: int
    api_key: str = Field(..., min_length=1, description="Google Gemini API key")


class GeminiKeyStatus(BaseModel):
    """Schema for Gemini key status response."""
    has_key: bool
    message: str


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
    smart_mode: bool = Field(False, description="Use higher intelligence model when enabled")
    conversation_id: Optional[int] = Field(None, description="Existing conversation ID, or None to create new")


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
    conversation_id: Optional[int] = None


# ============== Streaming Task Schemas ==============

class TaskStatusEnum(str, Enum):
    """Status of a task in the execution plan."""
    pending = "pending"
    in_progress = "in_progress"
    completed = "completed"
    failed = "failed"


class TaskUpdate(BaseModel):
    """Real-time update for a single task."""
    task_id: str
    service: str
    action: str
    description: str
    status: TaskStatusEnum
    tool_name: Optional[str] = None
    result: Optional[str] = None
    error: Optional[str] = None
    depends_on: list[str] = []


class StreamEvent(BaseModel):
    """Server-Sent Event payload."""
    event_type: str  # "plan", "task_started", "task_completed", "task_failed", "complete", "error"
    data: Any


class TaskPlanResponse(BaseModel):
    """Initial plan response showing all extracted tasks."""
    tasks: list[TaskUpdate]
    total: int
    completed: int = 0
    failed: int = 0
    current_task_id: Optional[str] = None


# ============== Conversation Schemas ==============

class ConversationCreate(BaseModel):
    """Schema for creating a new conversation."""
    user_id: int
    title: Optional[str] = Field("New Chat", description="Conversation title")


class ConversationResponse(BaseModel):
    """Schema for conversation response."""
    id: int
    title: str
    owner_id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ConversationList(BaseModel):
    """Schema for listing conversations."""
    conversations: list[ConversationResponse]
    total: int


class MessageResponse(BaseModel):
    """Schema for message response."""
    id: int
    conversation_id: int
    role: str
    content: str
    actions_taken: Optional[list[ActionResult]] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ConversationUpdate(BaseModel):
    """Schema for updating conversation."""
    title: str


# ============== Error Schemas ==============

class ErrorResponse(BaseModel):
    """Schema for error responses."""
    detail: str
    error_code: Optional[str] = None
