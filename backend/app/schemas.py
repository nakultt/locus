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
    timezone: str | None = Field(
        None,
        description="IANA timezone, e.g. Asia/Kolkata. Defaults to Asia/Kolkata.",
    )


class UserUpdate(BaseModel):
    """Schema for updating user details."""
    email: EmailStr | None = None
    password: str | None = Field(None, min_length=6, description="New password")
    name: str | None = None
    timezone: str | None = None


class UserResponse(BaseModel):
    """Schema for user response (excludes password)."""
    id: int
    email: str
    name: str | None = None
    created_at: datetime | None = None
    timezone: str | None = None
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


class SuggestedFix(BaseModel):
    """
    Replacement code that would resolve a finding.

    Always model-generated, including on a Semgrep or Gitleaks finding. The
    scanner confirms the *problem* deterministically; nothing confirms the
    *fix*, so a suggestion attached to a confirmed finding does not inherit
    that confirmation and must never be rendered as though it did.

    `replacement` holds the literal lines that replace `start_line..end_line`
    in `file_path`, ready for GitHub's ```suggestion block -- which renders an
    "Apply" button, so the text has to be exactly what belongs in the file.
    Indentation is therefore significant and is preserved verbatim.

    A fix that cannot be expressed as a line-range replacement -- one spanning
    several files, or requiring a new import elsewhere -- sets `replacement`
    to None and explains itself in `explanation` instead. Rendering an
    incomplete suggestion behind an Apply button is worse than rendering
    prose, because one click commits it.
    """
    # None when the fix cannot be expressed as an in-place line replacement.
    replacement: str | None = None
    # The inclusive line range `replacement` substitutes for. Both required
    # for a suggestion block: GitHub anchors it to a range, and a wrong range
    # silently applies the fix to the wrong code.
    start_line: int | None = None
    end_line: int | None = None
    # Why this fixes it, and anything the replacement cannot carry -- a new
    # dependency, a migration, a change needed in another file.
    explanation: str = ""


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

    # The fix, as code. Model-generated even here: the scanner confirms the
    # problem, nothing confirms the fix. See `SuggestedFix`.
    suggested_fix: SuggestedFix | None = None


class ReviewPriority(str, Enum):
    """
    How much a review finding should block the merge.

    Kept separate from SecuritySeverity: a P1 is "do not merge this", which is
    a judgement about this change, not a CVSS-style severity rating.
    """
    p1 = "p1"  # Breaks something, or contradicts a stated requirement.
    p2 = "p2"  # Should be fixed, but does not block the merge.
    p3 = "p3"  # Style, naming, nits.


class ReviewFinding(BaseModel):
    """
    A non-security code review finding.

    Security issues go through SecurityFinding, which has a scanner backing it.
    These are model judgements about correctness, requirements, and quality --
    always reported as the reviewer's opinion, never as confirmed defects.
    """
    priority: ReviewPriority
    title: str
    file_path: str
    line: int | None = None
    description: str
    category: str = Field(
        "correctness",
        description="correctness, requirements, quality, or testing",
    )
    # Replacement code resolving this finding, when the model could express
    # one. Advisory like the finding itself.
    suggested_fix: SuggestedFix | None = None


class RelatedTicket(BaseModel):
    """A ticket linked to a PR."""
    key: str
    summary: str | None = None
    status: str | None = None
    assignee: str | None = None
    url: str | None = None
    source: str = Field("jira", description="jira or linear")
    description: str | None = Field(
        None,
        description=(
            "The ticket's own body -- the fullest statement of what the work "
            "is supposed to do, and the thing a reviewer or tester most needs "
            "when they were not in the conversation."
        ),
    )


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
    matches: list[str] = Field(
        default_factory=list,
        description=(
            "What the search actually matched, one short line each. A count "
            "alone cannot be sanity-checked; these let a reader see whether "
            "the query found the right thing."
        ),
    )


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
    qa_slack_text: str | None = Field(
        None, description="Exactly what was posted to Slack, for the timeline"
    )
    qa_email_subject: str | None = None
    qa_email_body: str | None = None
    qa_email_to: list[str] = []
    qa_channel_id: str | None = Field(
        None,
        description=(
            "Channel id Slack resolved the post to. Inbound events identify "
            "channels by id, never by the '#name' typed at registration."
        ),
    )
    qa_email_message_id: str | None = Field(
        None, description="RFC Message-ID; matched against In-Reply-To on replies"
    )
    board_moves: list[str] = Field(
        default_factory=list,
        description=(
            "Project board cards moved, one line per issue. Empty when the "
            "issue is on no board or the card was already in place."
        ),
    )
    errors: list[str] = []


class IntegrationHealthEntry(BaseModel):
    """
    Whether one integration is working, as far as the loops can tell.

    `healthy` is a streak judgement, not a live probe: one failed poll is
    ordinary (a token refresh races, a request times out), and only a run of
    them is a condition someone has to act on.
    """
    service: str
    healthy: bool
    consecutive_failures: int = 0
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    last_error: str | None = None


class FindingDeltaSummary(BaseModel):
    """
    What moved between the previous analysis of a pull request and this one.

    Findings are identified by file and title rather than line number: an edit
    above a finding shifts it, and a shifted finding is the same finding.

    "Resolved" means the finding is no longer reported, which is not the same
    as fixed -- deleting the file resolves one too. The rendering says so.
    """
    resolved: list[str] = []
    persisting: list[str] = []
    introduced: list[str] = []


class PRAnalysisResult(BaseModel):
    """Result of the full PR analysis pipeline."""
    context: PRContext
    confirmed_findings: list[SecurityFinding] = []
    unverified_findings: list[SecurityFinding] = []
    review_findings: list[ReviewFinding] = Field(
        default_factory=list,
        description="Non-security review findings, ordered P1 first",
    )
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
    # How this run's findings compare with the previous run's on the same pull
    # request. Rendered into the comment so a re-review can start from what
    # moved. Empty on a first analysis, which has nothing to compare against.
    delta: FindingDeltaSummary | None = None
    # How many findings were withheld because someone dismissed them. Reported
    # in the comment rather than silently applied: a scanner that quietly stops
    # mentioning things is worse than one that never mentioned them.
    suppressed_count: int = 0
    errors: list[str] = []


class PRJobStatus(str, Enum):
    """Lifecycle of a queued PR analysis job."""
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class ReviewState(str, Enum):
    """
    Where a pull request sits in the senior-dev loop.

    Only `approved` clears the merge gate. `changes_requested` is not terminal
    -- it is the state the loop spends most of its time in, and the one a push
    from the author moves back out of.
    """
    awaiting_review = "awaiting_review"
    changes_requested = "changes_requested"
    approved = "approved"
    merged = "merged"


class ReviewOutcome(str, Enum):
    """What happened in one leg of the loop."""
    review_requested = "review_requested"
    approved = "approved"
    changes_requested = "changes_requested"
    commented = "commented"
    # The author pushed after changes were requested: a new round begins.
    resubmitted = "resubmitted"


class ReviewRound(BaseModel):
    """One completed leg, as stored."""
    model_config = ConfigDict(from_attributes=True)

    round_number: int
    outcome: ReviewOutcome
    reviewer: str | None = None
    body: str | None = None
    head_sha: str | None = None
    created_at: datetime | None = None


class PRReviewSummary(BaseModel):
    """A pull request's current position in the review loop."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    repo: str
    pr_number: int
    pr_url: str | None = None
    pr_title: str | None = None
    author: str | None = None
    state: ReviewState
    round_number: int
    last_reviewer: str | None = None
    updated_at: datetime | None = None


class PRReviewDetail(PRReviewSummary):
    """The same, plus the full round history and the outstanding asks."""
    pending_asks: list[str] = Field(
        default_factory=list,
        description="Model-written checklist from the last changes-requested review",
    )
    rounds: list[ReviewRound] = Field(default_factory=list)


class PRReviewList(BaseModel):
    """The review queue, with a count per state for the dashboard header."""
    reviews: list[PRReviewSummary] = []
    total: int = 0
    awaiting_review: int = 0
    changes_requested: int = 0
    approved: int = 0


class ReviewerContact(BaseModel):
    """Where one reviewer is reachable, beyond their GitHub login."""
    login: str
    slack: str | None = None
    email: str | None = None


class CommunicationEvent(BaseModel):
    """One message searched, sent, or received about a pull request."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    loop: str = Field(..., description='"review", "qa", or "context"')
    direction: str = Field(..., description='"searched", "sent", or "received"')
    channel: str = Field(..., description='"slack", "email", or "github"')
    participant: str | None = None
    target: str | None = None
    subject: str | None = None
    body: str | None = None
    query: str | None = None
    permalink: str | None = None
    outcome: str | None = None
    succeeded: bool = True
    created_at: datetime | None = None

    # True when this message was found on a sibling pull request for the same
    # work item and reused as context, rather than found on this one. The
    # reviewer was given it either way, so it belongs on the timeline -- but
    # labelled, so it does not read as discussion about this pull request.
    inherited: bool = False


class PRActivity(BaseModel):
    """
    Everything that happened on one pull request, both loops together.

    The review state and QA state are included alongside the message log so
    the UI can render "what is happening now" and "what happened" from one
    request rather than stitching three.
    """
    repo: str
    pr_number: int
    pr_url: str | None = None
    pr_title: str | None = None

    review: PRReviewDetail | None = None
    reviewer_contacts: list[ReviewerContact] = []

    # QA side. Absent until the PR merges and the test team is notified.
    qa_notified: bool = False
    qa_resolved: bool | None = None
    qa_channel: str | None = None
    qa_recipients: list[str] = []

    events: list[CommunicationEvent] = []


class WorklistKind(str, Enum):
    """What kind of attention an item needs."""
    changes_requested = "changes_requested"
    qa_rejected = "qa_rejected"
    qa_unanswered = "qa_unanswered"
    approved_not_merged = "approved_not_merged"
    delivery_failed = "delivery_failed"
    awaiting_review = "awaiting_review"


class WorklistItem(BaseModel):
    """One thing a person can act on, with the words that prompted it."""
    kind: WorklistKind
    blocked_on_you: bool
    repo: str
    pr_number: int
    pr_url: str | None = None
    headline: str
    detail: list[str] = Field(
        default_factory=list,
        description="Model-written checklist; for scanning, not for acting",
    )
    quotes: list[str] = Field(
        default_factory=list,
        description="The asker's own words, which is what someone acts on",
    )
    actor: str | None = None
    age_hours: float = 0.0
    round_number: int = 1
    from_human: bool = Field(
        True,
        description="A person asked, rather than a model producing a finding",
    )


class WorklistTask(BaseModel):
    """
    One work item, and everything outstanding across the PRs that touch it.

    Grouped by task rather than pull request: a ticket spanning three PRs is
    one thing that has been running for two weeks, not three young items.
    """
    key: str
    repo: str
    title: str | None = None
    pull_requests: list[int] = Field(default_factory=list)
    items: list[WorklistItem] = Field(default_factory=list)
    needs_you: bool = False
    age_hours: float = 0.0
    round_number: int = 1


class Worklist(BaseModel):
    """The two sections the dashboard renders."""
    needs_you: list[WorklistTask] = []
    waiting_on_others: list[WorklistTask] = []
    total_needs_you: int = 0


class TaskSource(str, Enum):
    """Where an assigned work item came from."""
    github = "github"
    jira = "jira"


class AssignedItem(BaseModel):
    """
    One issue or ticket assigned to the user, as the source reported it.

    Deliberately source-shaped rather than normalized into `RelatedTicket`:
    that type describes a ticket found *from* a pull request, where this
    describes work that may have no pull request at all yet.
    """
    source: TaskSource
    key: str = Field(..., description='Jira key, or "owner/repo#N" for a GitHub issue')
    title: str
    url: str
    state: str | None = None
    status: str | None = Field(None, description="Jira status name, or GitHub state")
    assignee: str | None = None
    repo: str | None = Field(None, description="Only set for GitHub issues")
    number: int | None = Field(None, description="Only set for GitHub issues")
    issue_type: str | None = None
    priority: str | None = None
    body: str | None = None
    updated_at: datetime | None = None


class LinkedBranch(BaseModel):
    """
    A branch linked to an issue through GitHub's Development panel.

    Only branches linked affirmatively -- via the "create a branch" button or
    the `createLinkedBranch` mutation -- appear here. A branch that merely
    happens to name the issue is not one of these, and is not treated as one.
    """
    name: str
    repo: str | None = None


class LinkedPullRequest(BaseModel):
    """
    A pull request GitHub reports as closing an issue.

    Distinct from `TaskPullRequest`, which describes a PR Locus has analyzed
    and holds review state for. This is the raw edge as GitHub reports it, and
    may name a pull request Locus has never seen.
    """
    repo: str
    pr_number: int
    title: str | None = None
    url: str | None = None
    state: str | None = None
    is_draft: bool = False
    merged: bool = False


class IssueLinks(BaseModel):
    """What GitHub's link graph says is being done about one issue."""
    branches: list[LinkedBranch] = Field(default_factory=list)
    pull_requests: list[LinkedPullRequest] = Field(default_factory=list)


class TaskStage(str, Enum):
    """
    How far along the automated pipeline one task has travelled.

    This is the spine of the task card: everything between `assigned` and
    `done` is automated, so a stage that has not been reached is a statement
    about where the work actually is, not about what Locus failed to do.

    `blocked` is deliberately not a stage -- a task is blocked *at* a stage,
    and collapsing the two would lose where it stalled.
    """
    assigned = "assigned"
    branch_created = "branch_created"
    in_progress = "in_progress"
    analyzed = "analyzed"
    in_review = "in_review"
    changes_requested = "changes_requested"
    approved = "approved"
    merged = "merged"
    testing = "testing"
    done = "done"


# Display order. The card renders every stage, so one not yet reached reads as
# "not there yet" rather than being absent from the picture entirely.
TASK_STAGE_ORDER: list[TaskStage] = [
    TaskStage.assigned,
    TaskStage.branch_created,
    TaskStage.in_progress,
    TaskStage.analyzed,
    TaskStage.in_review,
    TaskStage.changes_requested,
    TaskStage.approved,
    TaskStage.merged,
    TaskStage.testing,
    TaskStage.done,
]


class TaskStageStatus(BaseModel):
    """One step of the task pipeline, as the card's stepper renders it."""
    stage: TaskStage
    label: str
    state: StageState = StageState.pending
    detail: str | None = None


class TaskPullRequest(BaseModel):
    """A pull request opened against a task, with its review position."""
    repo: str
    pr_number: int
    url: str | None = None
    title: str | None = None
    author: str | None = None
    review_state: ReviewState | None = None
    round_number: int = 1
    last_reviewer: str | None = None


class TaskCard(BaseModel):
    """
    One assigned work item and everything Locus knows about its progress.

    The card is keyed by work item rather than pull request for the same
    reason `WorklistTask` is: one ticket routinely spans several pull
    requests, and a per-PR card shows a two-week round trip as three young
    items.
    """
    key: str
    source: TaskSource
    title: str
    url: str
    status: str | None = None
    assignee: str | None = None
    issue_type: str | None = None
    priority: str | None = None
    updated_at: datetime | None = None

    # The requirement in the words of whoever filed it. Carried on the card
    # because it is what the report document is written from, and because a
    # task with no pull request yet has nothing else describing what it is.
    description: str | None = None

    stage: TaskStage = TaskStage.assigned
    stages: list[TaskStageStatus] = Field(default_factory=list)
    pull_requests: list[TaskPullRequest] = Field(default_factory=list)

    # Branches linked through GitHub's Development panel. Carried on the card
    # because a linked branch with no pull request yet is the only evidence
    # that work has started, and without it the card reads as untouched.
    linked_branches: list[LinkedBranch] = Field(default_factory=list)

    # Reused verbatim from `worklist.build` so the board and the worklist
    # cannot disagree about what needs attention.
    items: list[WorklistItem] = Field(default_factory=list)
    needs_you: bool = False
    blocked_reason: str | None = None
    age_hours: float = 0.0
    round_number: int = 1


class TaskBoard(BaseModel):
    """Every assigned task, ordered by whether it is waiting on you."""
    needs_you: list[TaskCard] = []
    in_flight: list[TaskCard] = []
    total: int = 0

    # Which sources actually answered. A source that failed is reported rather
    # than rendered as "nothing assigned", which would read as an empty queue.
    github_available: bool = True
    jira_available: bool = True
    unavailable: list[str] = []


class TaskDetail(BaseModel):
    """
    One task's full pipeline: every stage, every message, every round.

    Returned as a single payload rather than stitched client-side for the same
    reason `PRActivity` is -- the UI shows these interleaved on one timeline,
    and separate requests would let the halves disagree about ordering.
    """
    card: TaskCard

    # The analysis of the most recent pull request on this task. Findings are
    # never carried across rounds; this is whatever the latest run produced.
    analysis: PRAnalysisResult | None = None
    job_status: str | None = None
    job_error: str | None = None

    reviews: list[PRReviewDetail] = []
    reviewer_contacts: list[ReviewerContact] = []

    qa_notified: bool = False
    qa_resolved: bool | None = None
    qa_channel: str | None = None
    qa_recipients: list[str] = []

    # Every message searched, sent and received for this work item, across
    # every pull request that touched it.
    events: list[CommunicationEvent] = []

    # The task's report document. Null when Docs is not connected -- the task
    # renders without a link rather than the view failing.
    doc_url: str | None = None


class AuthoringMode(str, Enum):
    """
    Who writes the code for a work item.

    `assisted` is a person; `autonomous` hands the ticket to the authoring
    driver, which opens a pull request that flows through the same analysis,
    review and QA pipeline. Assisted is the fallback everywhere -- a mode that
    writes code on its own is never inherited by accident.
    """
    assisted = "assisted"
    autonomous = "autonomous"


class MergeMethod(str, Enum):
    """How an auto-merge lands the branch. Mirrors GitHub's own options."""
    squash = "squash"
    merge = "merge"
    rebase = "rebase"


class MergeGateResult(BaseModel):
    """
    Why an approved PR was or was not merged automatically.

    Blockers are surfaced rather than swallowed: a PR that stays open after an
    approval, with no explanation, reads as the feature being broken.
    """
    attempted: bool = False
    merged: bool = False
    blockers: list[str] = []
    detail: str | None = None


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
    close_on_qa_signoff: bool = Field(
        False,
        description=(
            "Hold the ticket and linked issues open until the testing team "
            "signs off, instead of closing them at merge"
        ),
    )
    reviewers: list[str] = Field(
        default_factory=list,
        description="GitHub logins of the senior devs who review this repo",
    )
    reviewer_contacts: str | None = Field(
        None,
        description=(
            "Where each reviewer is reachable, one per line: "
            "github-login, @slack-handle, email@company.com"
        ),
    )
    review_slack_channel: str | None = Field(
        None,
        description=(
            "Channel for review requests and changes-requested pings. "
            "Falls back to slack_channel when unset."
        ),
    )
    auto_merge_on_approval: bool = Field(
        False,
        description=(
            "Merge automatically once approved and the merge gate passes. "
            "Off unless turned on deliberately."
        ),
    )
    merge_method: MergeMethod = Field(
        MergeMethod.squash, description="How an auto-merge lands the commits"
    )
    project_board_sync: bool = Field(
        True,
        description=(
            "Move each linked issue's GitHub Projects card as the pipeline "
            "advances. Needs the 'project' OAuth scope, which 'repo' does not "
            "imply."
        ),
    )
    project_column_map: str | None = Field(
        None,
        description=(
            "Stage to column, one 'stage: column' per line. Blank uses the "
            "default map; a stage left out of a non-empty map moves no card."
        ),
    )
    authoring_mode: AuthoringMode = Field(
        AuthoringMode.assisted,
        description=(
            "Who writes the code for this repo's tickets. Autonomous sends "
            "the brief to the configured authoring model, which is remote."
        ),
    )
    autonomous_max_rounds: int = Field(
        2,
        ge=0,
        le=10,
        description="The first attempt plus this many reworks before handing back",
    )
    preset_label: str | None = Field(
        None, description="Display only; the resolver decides what a run does"
    )
    source_path: str | None = Field(
        None,
        description=(
            "Where this repo is checked out locally. Blank falls back to "
            "LOCUS_CODE_ROOT, and failing that to a managed clone."
        ),
    )
    prepare_command: str | None = Field(
        None,
        description="Run once in the fresh worktree before the agent (uv sync, npm ci)",
    )
    test_command: str | None = Field(
        None, description="The authoring test gate. Blank means no gate."
    )


class PRAgentDefaultsUpdate(BaseModel):
    """
    Account-wide fallbacks applied to every repo that does not override them.

    These exist so a repo nobody registered still exports its report and
    emails the test team, instead of quietly doing neither.
    """
    slack_channel: str | None = Field(
        None, description="Default channel for PR summaries, e.g. #dev-updates"
    )
    export_to_docs: bool = Field(
        False, description="Write every analysis to a Google Doc by default"
    )
    qa_emails: list[str] = Field(
        default_factory=list,
        description="Test team addresses notified on merge, for every repo",
    )
    jira_done_status: str = Field(
        "Done", description="Jira status to move tickets to on merge"
    )
    close_issues_on_merge: bool = Field(
        True, description="Close linked GitHub issues when a PR merges"
    )
    close_on_qa_signoff: bool = Field(
        False,
        description=(
            "Hold work items open until the testing team signs off, for every "
            "repo"
        ),
    )
    reviewers: list[str] = Field(
        default_factory=list,
        description="Default senior-dev GitHub logins, for every repo",
    )
    reviewer_contacts: str | None = Field(
        None, description="Default reviewer contact lines"
    )
    review_slack_channel: str | None = Field(
        None, description="Default channel for review-loop notifications"
    )
    auto_merge_on_approval: bool = Field(
        False, description="Auto-merge approved PRs by default"
    )
    merge_method: MergeMethod = Field(
        MergeMethod.squash, description="Default auto-merge method"
    )
    project_board_sync: bool = Field(
        True, description="Keep GitHub Projects cards in step, for every repo"
    )
    project_column_map: str | None = Field(
        None, description="Default stage-to-column map, one entry per line"
    )
    authoring_mode: AuthoringMode = Field(
        AuthoringMode.assisted,
        description=(
            "Who writes the code for this repo's tickets. Autonomous sends "
            "the brief to the configured authoring model, which is remote."
        ),
    )
    autonomous_max_rounds: int = Field(
        2,
        ge=0,
        le=10,
        description="The first attempt plus this many reworks before handing back",
    )
    preset_label: str | None = Field(
        None, description="Display only; the resolver decides what a run does"
    )
    source_path: str | None = Field(
        None,
        description=(
            "Where this repo is checked out locally. Blank falls back to "
            "LOCUS_CODE_ROOT, and failing that to a managed clone."
        ),
    )
    prepare_command: str | None = Field(
        None,
        description="Run once in the fresh worktree before the agent (uv sync, npm ci)",
    )
    test_command: str | None = Field(
        None, description="The authoring test gate. Blank means no gate."
    )
    context_docs: list[str] = Field(
        default_factory=list,
        description=(
            "Google Docs read as context on every run, for every repo. These "
            "accumulate with a repo's own rather than being overridden by them"
        ),
    )


class PRAgentDefaults(PRAgentDefaultsUpdate):
    """Stored account-wide fallbacks."""
    model_config = ConfigDict(from_attributes=True)


class EffectiveSetting(BaseModel):
    """One resolved setting and which layer supplied it."""
    value: object = None
    source: str = Field(
        "unset", description='"repo", "defaults", or "unset"'
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
    close_on_qa_signoff: bool = False
    reviewers: list[str] = []
    reviewer_contacts: str | None = None
    review_slack_channel: str | None = None
    auto_merge_on_approval: bool = False
    merge_method: MergeMethod = MergeMethod.squash
    project_board_sync: bool = True
    project_column_map: str | None = None
    authoring_mode: AuthoringMode = AuthoringMode.assisted
    autonomous_max_rounds: int = 2
    preset_label: str | None = None
    source_path: str | None = None
    prepare_command: str | None = None
    test_command: str | None = None
    enabled: bool = True
    webhook_url: str | None = Field(
        None, description="Payload URL to paste into GitHub"
    )
    webhook_secret: str | None = Field(
        None, description="Shown once at creation; not retrievable afterwards"
    )

    model_config = ConfigDict(from_attributes=True)


class WorkItemModeUpdate(BaseModel):
    """
    An authoring override for one work item.

    Every field is optional and `None` means "inherit" rather than "assisted".
    Rows here are sparse by design: an absent row is the ordinary case, and
    clearing every field deletes it rather than storing a row of nulls that
    reads as a deliberate choice.
    """
    authoring_mode: AuthoringMode | None = Field(
        None, description="Null clears the override and inherits from the repo"
    )
    autonomous_max_rounds: int | None = Field(
        None, ge=0, le=10, description="Null inherits the repo or account bound"
    )


class WorkItemMode(BaseModel):
    """
    The authoring mode a run on this work item would actually use.

    `source` is the layer that supplied it -- "work_item", "repo", "defaults",
    "unset", or "handed_back" -- so a mode the user did not expect can be
    traced to the setting responsible rather than guessed at.
    """
    task_key: str
    authoring_mode: AuthoringMode
    autonomous_max_rounds: int
    source: str
    rounds_source: str
    # The stored override, if there is one. Distinct from the resolved value:
    # the UI renders the toggle from this and the caption from `source`.
    override: AuthoringMode | None = None
    handed_back: bool = False
    handed_back_reason: str | None = None
    handed_back_at: datetime | None = None
    preset_label: str | None = None


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
    # The searches behind those steps. A count like "2 thread(s)" cannot be
    # sanity-checked without seeing the query and what it matched.
    tool_calls: list[ToolInvocation] = []

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


# ============== Adaptive Scheduler ==============

class EventClass(str, Enum):
    """
    How movable a calendar event is.

    Drives the solver: flexible time moves before a team meeting, and a
    hard-fixed event never moves at all.
    """
    HARD_FIXED = "hard_fixed"
    SOFT_FIXED = "soft_fixed"
    FLEXIBLE = "flexible"


class ScheduledEvent(BaseModel):
    """One event on the calendar, as the solver sees it."""
    event_id: str
    title: str
    start: datetime
    end: datetime
    attendee_count: int = 1
    has_external_attendees: bool = False
    event_class: EventClass | None = Field(
        None, description="Explicit classification; inferred when absent"
    )

    @property
    def duration_minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)


class ScheduleMove(BaseModel):
    """A proposed change to one event."""
    event_id: str
    title: str
    from_start: datetime | None = Field(
        None, description="Current start; absent for a newly added block"
    )
    to_start: datetime
    duration_minutes: int
    event_class: EventClass
    attendee_count: int = 1
    reason: str = ""


class ScheduleProposal(BaseModel):
    """
    A plan the user must approve before anything changes.

    Never applied automatically for events with other attendees: moving one
    sends invite updates to everyone on it.
    """
    trigger: str = Field(..., description="What prompted the plan")
    timezone: str
    moves: list[ScheduleMove] = []
    additions: list[ScheduleMove] = []
    blocked: list[str] = Field(
        default_factory=list,
        description="Conflicts the solver could not resolve, and why",
    )
    summary: str = ""

    @property
    def requires_approval(self) -> bool:
        """Any move touching another person needs a human decision."""
        return any(m.attendee_count > 1 for m in self.moves)


class SchedulePlanRequest(BaseModel):
    """Ask for a plan without applying it."""
    title: str = Field(..., description="What is being scheduled")
    start: str = Field(..., description="Natural language, e.g. 'tomorrow at 3pm'")
    duration_minutes: int = Field(60, ge=5, le=720)
    attendees: int = Field(1, ge=1, description="How many people are invited")


class ScheduleApplyRequest(BaseModel):
    """Apply a previously reviewed plan."""
    moves: list[ScheduleMove]
    additions: list[ScheduleMove] = []


class DeadlineCreate(BaseModel):
    """Register a due date the scheduler must protect."""
    key: str = Field(..., description="Ticket key or label, e.g. LOC-431")
    title: str
    due_at: datetime
    estimated_minutes: int = Field(60, ge=5, le=2400)
    source: str = Field("manual", description="jira, linear, or manual")
    url: str | None = None


class DeadlineResponse(BaseModel):
    """A tracked deadline."""
    id: int
    key: str
    title: str
    due_at: datetime
    estimated_minutes: int
    source: str
    url: str | None = None
    completed: bool = False

    model_config = ConfigDict(from_attributes=True)


class EventConstraintSet(BaseModel):
    """Override how movable a specific event is."""
    event_id: str
    event_class: EventClass
    note: str | None = None
