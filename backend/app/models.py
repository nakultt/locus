"""
Database Models
SQLAlchemy ORM models for User and Integration tables
"""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class User(Base):
    """User account model."""
    
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=True)
    hashed_password = Column(String(255), nullable=False)
    # IANA timezone, e.g. "Asia/Kolkata". Drives calendar parsing and scheduling.
    timezone = Column(String(64), nullable=False, default="Asia/Kolkata")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationship: User has many Integrations
    integrations = relationship("Integration", back_populates="owner", cascade="all, delete-orphan")
    # Relationship: User has many Conversations
    conversations = relationship("Conversation", back_populates="owner", cascade="all, delete-orphan")
    # Relationship: User has many PR analysis jobs
    pr_jobs = relationship("PRJob", back_populates="owner", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<User(id={self.id}, email={self.email})>"


class Integration(Base):
    """Third-party service integration model."""
    
    __tablename__ = "integrations"

    id = Column(Integer, primary_key=True, index=True)
    service_name = Column(String(50), nullable=False, index=True)  # jira, gmail, slack, notion, calendar
    encrypted_api_key = Column(Text, nullable=True)  # For simple API key auth
    encrypted_credentials = Column(Text, nullable=True)  # For OAuth/complex credentials (JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Foreign Key to User
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    # Relationship: Integration belongs to User
    owner = relationship("User", back_populates="integrations")

    def __repr__(self) -> str:
        return f"<Integration(id={self.id}, service={self.service_name}, owner_id={self.owner_id})>"


class Conversation(Base):
    """Chat conversation model."""
    
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False, default="New Chat")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Foreign Key to User
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    # Relationships
    owner = relationship("User", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan", order_by="Message.created_at")

    def __repr__(self) -> str:
        return f"<Conversation(id={self.id}, title={self.title}, owner_id={self.owner_id})>"


class Message(Base):
    """Chat message model."""
    
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    role = Column(String(20), nullable=False)  # "user" or "assistant"
    content = Column(Text, nullable=False)
    actions_json = Column(Text, nullable=True)  # Serialized ActionResult list as JSON
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Foreign Key to Conversation
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False)

    # Relationship
    conversation = relationship("Conversation", back_populates="messages")

    def __repr__(self) -> str:
        return f"<Message(id={self.id}, role={self.role}, conversation_id={self.conversation_id})>"


class PRJob(Base):
    """
    A queued pull-request analysis job.

    GitHub webhooks time out at 10s but the analysis pipeline takes 30-60s, so
    the webhook persists a job here and returns 200 immediately. A worker picks
    it up. Persisting (rather than using FastAPI BackgroundTasks) means jobs
    survive a restart and can be retried.
    """

    __tablename__ = "pr_jobs"

    id = Column(Integer, primary_key=True, index=True)
    repo = Column(String(255), nullable=False, index=True)  # "owner/name"
    pr_number = Column(Integer, nullable=False)
    action = Column(String(32), nullable=False)  # opened, synchronize, reopened
    head_sha = Column(String(64), nullable=True)
    # Event fields the job needs but the PR number cannot supply -- a review's
    # verdict, reviewer, and body. Stored rather than re-fetched because the
    # review that fired the webhook may already have been superseded by the
    # time the worker gets to it.
    payload_json = Column(Text, nullable=True)

    status = Column(String(20), nullable=False, default="queued", index=True)
    result_json = Column(Text, nullable=True)  # Serialized PRAnalysisResult
    error = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    owner = relationship("User", back_populates="pr_jobs")

    def __repr__(self) -> str:
        return f"<PRJob(id={self.id}, repo={self.repo}, pr=#{self.pr_number}, status={self.status})>"


class QAThread(Base):
    """
    A QA notification Locus posted, and the PR state it refers to.

    Slack replies arrive carrying only a channel and a thread timestamp, so the
    work items to reopen have to be recorded when the notification is sent --
    there is no way to recover them from the reply itself.
    """

    __tablename__ = "qa_threads"

    id = Column(Integer, primary_key=True, index=True)
    repo = Column(String(255), nullable=False, index=True)
    pr_number = Column(Integer, nullable=False)
    pr_url = Column(String(512), nullable=False)

    # Slack correlation: channel id plus the parent message timestamp.
    slack_channel = Column(String(64), nullable=True, index=True)
    slack_thread_ts = Column(String(32), nullable=True, index=True)
    # Email correlation, for the Gmail fallback.
    email_message_id = Column(String(512), nullable=True, index=True)

    # What to reopen if a tester reports a failure, as JSON lists.
    ticket_keys_json = Column(Text, nullable=True)
    issue_numbers_json = Column(Text, nullable=True)

    resolved = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    def __repr__(self) -> str:
        return f"<QAThread(repo={self.repo}, pr=#{self.pr_number})>"


class PRReview(Base):
    """
    Where a pull request stands in the senior-dev review loop.

    One row per (repo, pr_number). GitHub reports each review as an isolated
    event -- there is no "this PR is on its third round" anywhere in the
    payload -- so the round count and the current state have to be accumulated
    here as events arrive.

    `state` is what gates the merge; `round_number` is what makes a stalled
    back-and-forth visible. A PR on round five is a conversation that is not
    converging, which is exactly what nobody notices without a record.
    """

    __tablename__ = "pr_reviews"

    id = Column(Integer, primary_key=True, index=True)
    repo = Column(String(255), nullable=False, index=True)  # "owner/name"
    pr_number = Column(Integer, nullable=False, index=True)
    pr_url = Column(String(512), nullable=True)
    pr_title = Column(String(512), nullable=True)
    # GitHub login of whoever opened the PR -- the dev the loop returns to.
    author = Column(String(255), nullable=True)

    # awaiting_review | changes_requested | approved | merged
    state = Column(String(32), nullable=False, default="awaiting_review", index=True)
    # Increments on every changes_requested -> re-review cycle. Starts at 1.
    round_number = Column(Integer, nullable=False, default=1)
    # Most recent reviewer to act, for "who is this waiting on".
    last_reviewer = Column(String(255), nullable=True)
    # Model-written checklist of what the reviewer asked for, refreshed each
    # time changes are requested. Advisory only; the review body is canonical.
    pending_asks = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    rounds = relationship(
        "PRReviewRound",
        back_populates="review",
        cascade="all, delete-orphan",
        order_by="PRReviewRound.round_number",
    )

    def __repr__(self) -> str:
        return (
            f"<PRReview(repo={self.repo}, pr=#{self.pr_number}, "
            f"state={self.state}, round={self.round_number})>"
        )


class PRReviewRound(Base):
    """
    One completed leg of the review loop, appended and never rewritten.

    Kept as history rather than folded into PRReview because "what did the
    senior dev ask for in round two" is the question that gets asked when a
    change regresses, and a mutable current-state row cannot answer it.
    """

    __tablename__ = "pr_review_rounds"

    id = Column(Integer, primary_key=True, index=True)
    review_id = Column(Integer, ForeignKey("pr_reviews.id"), nullable=False, index=True)

    round_number = Column(Integer, nullable=False)
    # approved | changes_requested | commented | review_requested | resubmitted
    outcome = Column(String(32), nullable=False)
    reviewer = Column(String(255), nullable=True)
    # Reviewer's own words. Untrusted: anyone who can review can write here.
    body = Column(Text, nullable=True)
    # Head commit the review applied to, so a later push is visibly newer.
    head_sha = Column(String(64), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    review = relationship("PRReview", back_populates="rounds")

    def __repr__(self) -> str:
        return f"<PRReviewRound(review_id={self.review_id}, round={self.round_number}, outcome={self.outcome})>"


class Deadline(Base):
    """
    A due date the scheduler must protect.

    Sourced from Jira due dates, Linear targets, or entered by hand. The
    scheduler will not push work past one of these; if it cannot fit the work
    beforehand it reports that rather than silently missing it.
    """

    __tablename__ = "deadlines"

    id = Column(Integer, primary_key=True, index=True)
    # Ticket key, issue reference, or a free-text label.
    key = Column(String(128), nullable=False, index=True)
    title = Column(String(512), nullable=False)
    due_at = Column(DateTime(timezone=True), nullable=False, index=True)
    # Work still needed, so a slot of the right size can be found.
    estimated_minutes = Column(Integer, nullable=False, default=60)
    source = Column(String(32), nullable=False, default="manual")  # jira, linear, manual
    url = Column(String(512), nullable=True)
    completed = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    def __repr__(self) -> str:
        return f"<Deadline(key={self.key}, due={self.due_at})>"


class EventConstraint(Base):
    """
    How movable a specific calendar event is.

    The scheduler infers a class from attendee count, but that guess is wrong
    often enough to need an override: a solo block can be immovable, and a
    six-person meeting can be trivially rescheduled.
    """

    __tablename__ = "event_constraints"

    id = Column(Integer, primary_key=True, index=True)
    # Google Calendar event id.
    event_id = Column(String(256), nullable=False, index=True)
    # hard_fixed | soft_fixed | flexible
    event_class = Column(String(16), nullable=False)
    note = Column(String(512), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    def __repr__(self) -> str:
        return f"<EventConstraint(event={self.event_id}, class={self.event_class})>"


class RepoWebhook(Base):
    """
    Per-repo webhook registration.

    The `webhook_secret` is what proves an inbound POST /webhooks/github really
    came from GitHub, via HMAC-SHA256 over the raw body. It is encrypted at
    rest like any other credential.
    """

    __tablename__ = "repo_webhooks"

    id = Column(Integer, primary_key=True, index=True)
    repo = Column(String(255), nullable=False, index=True)  # "owner/name"
    encrypted_secret = Column(Text, nullable=False)
    slack_channel = Column(String(255), nullable=True)  # Where to post summaries
    # Write each analysis to a Google Doc as a durable record.
    export_to_docs = Column(Integer, nullable=False, default=0)
    # Google Doc ids pinned to this repo, newline-separated. Their text is fed
    # to the reviewer as context on every analysis.
    context_doc_ids = Column(Text, nullable=True)
    # Test team addresses emailed when a PR merges, newline-separated.
    qa_emails = Column(Text, nullable=True)
    # Jira status to move tickets to on merge. Forward-only; see merge_actions.
    jira_done_status = Column(String(64), nullable=False, default="Done")
    close_issues_on_merge = Column(Integer, nullable=False, default=1)
    # GitHub logins of the senior devs who review this repo, newline-separated.
    # Used to address review notifications; reviews from anyone else are still
    # recorded, since GitHub does not restrict who may review.
    reviewers = Column(Text, nullable=True)
    # Channel for review-loop notifications. Separate from slack_channel: PR
    # summaries are for the team, a review request is for one person, and
    # collapsing them buries the request in the feed.
    review_slack_channel = Column(String(255), nullable=True)
    enabled = Column(Integer, nullable=False, default=1)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    def __repr__(self) -> str:
        return f"<RepoWebhook(repo={self.repo}, owner_id={self.owner_id})>"


class PRAgentDefaults(Base):
    """
    Account-wide fallbacks for the PR agent, one row per user.

    Every setting here also exists per repo. A repo that sets a value wins;
    otherwise this fills in. Without it, a repo that was never registered --
    or registered before a setting existed -- silently does nothing on merge,
    which reads as the feature being broken rather than unconfigured.

    Nullable columns mean "not set", which is what lets a per-repo blank fall
    through to here rather than overriding with emptiness.
    """

    __tablename__ = "pr_agent_defaults"

    id = Column(Integer, primary_key=True, index=True)

    slack_channel = Column(String(255), nullable=True)
    export_to_docs = Column(Integer, nullable=False, default=0)
    qa_emails = Column(Text, nullable=True)  # newline-separated
    jira_done_status = Column(String(64), nullable=False, default="Done")
    close_issues_on_merge = Column(Integer, nullable=False, default=1)
    reviewers = Column(Text, nullable=True)  # newline-separated GitHub logins
    review_slack_channel = Column(String(255), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # One row per user; the unique constraint is what makes "upsert by owner"
    # safe rather than silently accumulating rows.
    owner_id = Column(
        Integer, ForeignKey("users.id"), nullable=False, unique=True, index=True
    )

    def __repr__(self) -> str:
        return f"<PRAgentDefaults(owner_id={self.owner_id})>"
