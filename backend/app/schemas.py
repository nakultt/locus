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


class UserResponse(BaseModel):
    """Schema for user response (excludes password)."""
    id: int
    email: str
    name: Optional[str] = None
    created_at: Optional[datetime] = None
    token: Optional[str] = Field(None, description="JWT access token")

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


# ============== Error Schemas ==============

class ErrorResponse(BaseModel):
    """Schema for error responses."""
    detail: str
    error_code: Optional[str] = None
