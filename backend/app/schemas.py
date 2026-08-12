"""
Pydantic Schemas
Request/Response validation models
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field

# ============== User Schemas ==============

class UserCreate(BaseModel):
    """Schema for user registration."""
    email: EmailStr
    password: str = Field(..., min_length=6, description="Password must be at least 6 characters")
    name: str | None = Field(None, description="User's display name")


class UserUpdate(BaseModel):
    """Schema for updating user details."""
    email: EmailStr | None = None
    password: str | None = Field(None, min_length=6, description="New password")
    name: str | None = None


class UserResponse(BaseModel):
    """Schema for user response (excludes password)."""
    id: int
    email: str
    name: str | None = None
    created_at: datetime | None = None
    token: str | None = Field(None, description="JWT access token")

    model_config = ConfigDict(from_attributes=True)


class UserLogin(BaseModel):
    """Schema for user login."""
    email: EmailStr
    password: str
    remember_me: bool = Field(False, description="Keep user logged in for 30 days")


class LLMStatus(BaseModel):
    """Status of the local model backend."""
    available: bool = Field(..., description="Whether a text model is loaded and ready")
    message: str = Field(..., description="Human-readable status or remediation hint")
    provider: str | None = None
    base_url: str | None = None
    fast_model: str | None = None
    smart_model: str | None = None


# ============== Integration Schemas ==============

class IntegrationCreate(BaseModel):
    """Schema for connecting a new integration."""
    user_id: int
    service_name: str = Field(
        ...,
        description="Service name: jira, gmail, calendar, slack, notion"
    )
    api_key: str | None = Field(None, description="API key for simple auth")
    credentials: dict[str, Any] | None = Field(
        None,
        description="OAuth credentials or complex auth config"
    )


class IntegrationResponse(BaseModel):
    """Schema for integration response."""
    id: int
    service_name: str
    owner_id: int
    created_at: datetime | None = None
    is_connected: bool = True

    model_config = ConfigDict(from_attributes=True)


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
    conversation_id: int | None = Field(None, description="Existing conversation ID, or None to create new")


class ActionResult(BaseModel):
    """Schema for individual action result."""
    service: str
    action: str
    success: bool
    result: Any | None = None
    error: str | None = None


class ChatResponse(BaseModel):
    """Schema for chat response."""
    message: str
    actions_taken: list[ActionResult] = []
    raw_response: str | None = None
    conversation_id: int | None = None


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
    tool_name: str | None = None
    result: str | None = None
    error: str | None = None
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
    current_task_id: str | None = None


# ============== Conversation Schemas ==============

class ConversationCreate(BaseModel):
    """Schema for creating a new conversation."""
    user_id: int
    title: str | None = Field("New Chat", description="Conversation title")


class ConversationResponse(BaseModel):
    """Schema for conversation response."""
    id: int
    title: str
    owner_id: int
    created_at: datetime
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


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
    actions_taken: list[ActionResult] | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ConversationUpdate(BaseModel):
    """Schema for updating conversation."""
    title: str


# ============== PR Context Agent Schemas ==============

class SecuritySeverity(str, Enum):
    """Severity of a security finding."""
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"
    info = "info"


class FindingSource(str, Enum):
    """
    Where a finding came from.

    `semgrep` findings are deterministic rule matches and are reported as
    confirmed. `llm` findings are model-generated and reported as unverified;
    the two are never merged into one list, because a wrong "confirmed
    vulnerability" on someone's PR destroys trust in the tool.
    """
    semgrep = "semgrep"
    gitleaks = "gitleaks"
    llm = "llm"


class SecurityFinding(BaseModel):
    """A single security finding against a PR diff."""
    source: FindingSource
    severity: SecuritySeverity
    title: str
    file_path: str
    line: int | None = None
    description: str
    rule_id: str | None = None
    # Deliberately no `secret_value` field. Detected credentials are reported
    # by location only; echoing them into a PR comment widens the exposure.


class RelatedTicket(BaseModel):
    """A ticket linked to a PR."""
    key: str
    summary: str | None = None
    status: str | None = None
    assignee: str | None = None
    url: str | None = None
    source: str = Field("jira", description="jira or linear")


class RelatedSlackThread(BaseModel):
    """A Slack thread linked to a PR."""
    channel: str
    permalink: str | None = None
    message_count: int = 0
    summary: str | None = None
    participants: list[str] = []


class PRContext(BaseModel):
    """Everything gathered about a pull request."""
    repo: str
    pr_number: int
    title: str
    author: str
    url: str
    branch: str | None = None
    ticket_keys: list[str] = []
    tickets: list[RelatedTicket] = []
    slack_threads: list[RelatedSlackThread] = []
    files_changed: int = 0
    additions: int = 0
    deletions: int = 0


class PRAnalysisResult(BaseModel):
    """Result of the full PR analysis pipeline."""
    context: PRContext
    confirmed_findings: list[SecurityFinding] = []
    unverified_findings: list[SecurityFinding] = []
    summary: str = ""
    pr_comment_posted: bool = False
    slack_posted: bool = False
    errors: list[str] = []


class PRJobStatus(str, Enum):
    """Lifecycle of a queued PR analysis job."""
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class PRJobResponse(BaseModel):
    """Status of a PR analysis job."""
    id: int
    status: PRJobStatus
    repo: str
    pr_number: int
    created_at: datetime
    completed_at: datetime | None = None
    error: str | None = None

    model_config = ConfigDict(from_attributes=True)


# ============== Error Schemas ==============

class ErrorResponse(BaseModel):
    """Schema for error responses."""
    detail: str
    error_code: str | None = None
