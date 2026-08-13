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


class LinkedIssue(BaseModel):
    """A GitHub issue this PR closes or mentions."""
    number: int
    title: str
    state: str
    url: str
    author: str | None = None
    body: str | None = None
    relation: str = Field(
        "closes", description='"closes" for a real link, "mentions" for a #N reference'
    )


class RelatedDocument(BaseModel):
    """A Google Doc that appears to describe the work in a PR."""
    title: str
    url: str
    modified_at: str | None = None
    excerpt: str = Field("", description="Document text, truncated for the context budget")
    truncated: bool = False


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
    linked_issues: list[LinkedIssue] = []
    slack_threads: list[RelatedSlackThread] = []
    documents: list[RelatedDocument] = []
    files_changed: int = 0
    additions: int = 0
    deletions: int = 0


class ToolInvocation(BaseModel):
    """
    One external call the pipeline made.

    Recorded so a run's detail view can show exactly which tools ran, what was
    searched for, and what came back -- the difference between "no discussion
    found" and "search never ran".
    """
    service: str
    tool: str
    query: str | None = Field(None, description="Search terms or identifier used")
    result_count: int = 0
    succeeded: bool = True
    detail: str | None = None
    duration_ms: int | None = None


class StageState(str, Enum):
    """Lifecycle of one pipeline step."""
    pending = "pending"
    running = "running"
    done = "done"
    skipped = "skipped"
    failed = "failed"


class PipelineStage(BaseModel):
    """
    One step of the PR pipeline, as the dashboard shows it.

    The run detail lists these in order so it is visible what the agent read,
    what it wrote, and what it skipped -- rather than only the end result.
    """
    key: str
    label: str
    kind: str = Field("read", description='"read" or "write"')
    state: StageState = StageState.pending
    detail: str | None = Field(
        None, description="What happened, e.g. '2 tickets' or 'Slack not connected'"
    )


class MergeActionResult(BaseModel):
    """What happened after a pull request merged."""
    jira_transitioned: list[str] = []
    issues_closed: list[str] = []
    qa_notified: bool = False
    qa_brief: str | None = None
    qa_thread_ts: str | None = Field(
        None, description="Slack thread timestamp; ties later replies to this PR"
    )
    qa_email_message_id: str | None = Field(
        None, description="RFC Message-ID; matched against In-Reply-To on replies"
    )
    errors: list[str] = []


class PRAnalysisResult(BaseModel):
    """Result of the full PR analysis pipeline."""
    context: PRContext
    confirmed_findings: list[SecurityFinding] = []
    unverified_findings: list[SecurityFinding] = []
    summary: str = ""
    pr_comment_posted: bool = False
    slack_posted: bool = False
    doc_url: str | None = Field(
        None, description="Google Doc holding the full report, when exported"
    )
    tool_calls: list[ToolInvocation] = Field(
        default_factory=list,
        description="Every external lookup the pipeline made, in order",
    )
    stages: list[PipelineStage] = Field(
        default_factory=list,
        description="Each pipeline step and whether it ran, was skipped, or failed",
    )
    merge_actions: MergeActionResult | None = None
    errors: list[str] = []


class PRJobStatus(str, Enum):
    """Lifecycle of a queued PR analysis job."""
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class RepoRegister(BaseModel):
    """Register a repository for PR analysis."""
    repo: str = Field(..., description='Repository as "owner/name"', pattern=r"^[\w.-]+/[\w.-]+$")
    slack_channel: str | None = Field(
        None, description="Channel for PR summaries, e.g. #dev-updates"
    )
    export_to_docs: bool = Field(
        False, description="Also write each analysis to a Google Doc"
    )
    context_docs: list[str] = Field(
        default_factory=list,
        description="Google Doc URLs or ids to always feed the reviewer as context",
    )
    qa_emails: list[str] = Field(
        default_factory=list,
        description="Test team addresses notified when a PR merges",
    )
    jira_done_status: str = Field(
        "Done", description="Jira status to move tickets to on merge"
    )
    close_issues_on_merge: bool = Field(
        True, description="Close linked GitHub issues when the PR merges"
    )


class RepoRegistration(BaseModel):
    """A registered repository."""
    id: int
    repo: str
    slack_channel: str | None = None
    export_to_docs: bool = False
    context_docs: list[str] = []
    qa_emails: list[str] = []
    jira_done_status: str = "Done"
    close_issues_on_merge: bool = True
    enabled: bool = True
    webhook_url: str | None = Field(
        None, description="Payload URL to paste into GitHub"
    )
    webhook_secret: str | None = Field(
        None, description="Shown once at creation; not retrievable afterwards"
    )

    model_config = ConfigDict(from_attributes=True)


class RepoRegistrationList(BaseModel):
    """All repositories registered by a user."""
    repos: list[RepoRegistration]
    total: int


class PRJobResponse(BaseModel):
    """Status of a PR analysis job."""
    id: int
    status: PRJobStatus
    repo: str
    pr_number: int
    action: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
    error: str | None = None
    # Carried on the list response too, so the run list can show which steps
    # ran without expanding each row.
    stages: list[PipelineStage] = []

    model_config = ConfigDict(from_attributes=True)


class PRJobDetail(PRJobResponse):
    """A job plus its full analysis result, for the dashboard detail view."""
    result: PRAnalysisResult | None = None


class CapabilityStatus(BaseModel):
    """One concrete thing the pipeline can or cannot do."""
    key: str
    label: str
    available: bool
    required: bool = False
    hint: str = ""


class ServiceStatus(BaseModel):
    """A service and its individual capabilities."""
    key: str
    label: str
    connected: bool
    required: bool = False
    capabilities: list[CapabilityStatus] = []


class PRAgentSummary(BaseModel):
    """Headline counts for the PR agent dashboard."""
    total_jobs: int = 0
    completed: int = 0
    failed: int = 0
    running: int = 0
    queued: int = 0
    repos_registered: int = 0
    confirmed_findings: int = 0
    unverified_findings: int = 0
    # Which integrations the pipeline can currently draw on. GitHub is
    # required; the rest degrade to less context rather than failing.
    github_connected: bool = False
    jira_connected: bool = False
    slack_connected: bool = False
    slack_search_enabled: bool = False
    docs_connected: bool = False
    semgrep_available: bool = False
    gitleaks_available: bool = False
    services: list[ServiceStatus] = []
    public_base_url: str | None = None


# ============== Error Schemas ==============

class ErrorResponse(BaseModel):
    """Schema for error responses."""
    detail: str
    error_code: str | None = None
