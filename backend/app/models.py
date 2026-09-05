"""
Database Models
SQLAlchemy ORM models for User and Integration tables
"""

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


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
    # Nullable because an authoring job has no pull request number when it
    # starts -- opening one is its whole job. Queuing with 0 as a sentinel is
    # the tempting alternative and something downstream reads it as a real PR
    # number within a release.
    pr_number = Column(Integer, nullable=True)
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
    # When the worker picked this job up. Without it a job that has been
    # running for five seconds is indistinguishable from one orphaned an hour
    # ago by a restart, and recovery cannot tell which to reclaim.
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    # How many times this job has been picked up. A job that kills the worker
    # would otherwise be reclaimed, crash, and be reclaimed again forever --
    # recovery turns one dropped job into an unkillable loop without this.
    attempts = Column(Integer, nullable=False, default=0)

    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    owner = relationship("User", back_populates="pr_jobs")

    def __repr__(self) -> str:
        return f"<PRJob(id={self.id}, repo={self.repo}, pr=#{self.pr_number}, status={self.status})>"


class IntegrationHealth(Base):
    """
    Whether one service is actually working, per user.

    The background loops swallow their own failures on purpose -- a dead Jira
    must not stop the analysis -- which leaves a persistently broken
    integration invisible. A Gmail token that expired on Monday is still
    failing on Friday, and the only symptom is that QA replies stopped
    arriving, which reads as nobody replying.

    One row per (user, service). Rewritten in place rather than appended to:
    the question is "is this working now", and a full attempt history would
    grow without bound for a poller that runs every few minutes.
    """

    __tablename__ = "integration_health"

    id = Column(Integer, primary_key=True, index=True)
    service_name = Column(String(64), nullable=False, index=True)

    last_success_at = Column(DateTime(timezone=True), nullable=True)
    last_failure_at = Column(DateTime(timezone=True), nullable=True)
    # Reset to zero on any success. One failure is normal; a streak is a
    # condition someone has to act on.
    consecutive_failures = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)

    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    def __repr__(self) -> str:
        return (
            f"<IntegrationHealth(service={self.service_name}, "
            f"failures={self.consecutive_failures})>"
        )


class SuppressedFinding(Base):
    """
    A finding someone dismissed as not worth reporting.

    Without this a false positive is permanent: the scan re-runs on every
    push, the finding comes back, and the only way to silence it is to stop
    reading the comment. That is the failure the confirmed/unverified split
    exists to avoid, arrived at from the other direction.

    Keyed by file and title rather than line, for the same reason
    `finding_diff` is: an edit above a finding shifts it, and a suppression
    keyed to a line would silently lapse the next time anyone touched the
    file. Normalised on write so matching is a plain equality check.

    Scoped to one pull request by default. A finding dismissed on someone
    else's PR says nothing about this one, and a repo-wide suppression is a
    bigger claim than "this instance is wrong" -- `scope` records which was
    meant.
    """

    __tablename__ = "suppressed_findings"

    id = Column(Integer, primary_key=True, index=True)
    repo = Column(String(255), nullable=False, index=True)
    # Null for a repo-wide suppression, which applies to every pull request.
    pr_number = Column(Integer, nullable=True, index=True)

    # Normalised identity: lowercased, whitespace-collapsed.
    file_path = Column(String(512), nullable=False)
    title = Column(String(512), nullable=False)

    # "pr" or "repo" -- what the person dismissing it meant to silence.
    scope = Column(String(16), nullable=False, default="pr")
    # GitHub login of whoever dismissed it, and why. Both are for the audit
    # trail: a suppression with no author is indistinguishable from a bug.
    suppressed_by = Column(String(255), nullable=True)
    reason = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    def __repr__(self) -> str:
        return (
            f"<SuppressedFinding(repo={self.repo}, pr=#{self.pr_number}, "
            f"title={self.title!r})>"
        )


class PRReport(Base):
    """
    The Google Doc holding one work item's written record.

    Keyed by `ticket_key` when the work has one, so a task spanning three pull
    requests -- the feature, the fix after QA rejected it, the follow-up --
    keeps one document rather than three. The argument is the same one that
    made this a document per pull request instead of per push, applied a level
    up: a new file per PR scatters the history and leaves every link already
    sent pointing at a partial record.

    Work with no ticket falls back to `(repo, pr_number)`, because a pull
    request without a tracker reference is ordinary and must still get a
    document.

    `repo` and `pr_number` record where the document started. They stay
    populated for the fallback lookup and to show which pull request first
    created it; they are not the identity once a ticket is known.
    """

    __tablename__ = "pr_reports"

    id = Column(Integer, primary_key=True, index=True)
    # Where the document started. Null when it was created from the ticket
    # itself, before any pull request existed -- the document belongs to the
    # work item, and a task can be written up while someone is still coding.
    repo = Column(String(255), nullable=True, index=True)
    pr_number = Column(Integer, nullable=True, index=True)
    # The work item this document belongs to. Nullable the other way round: a
    # pull request with no tracker reference still gets a document, keyed by
    # the PR instead. One of the two is always set.
    ticket_key = Column(String(64), nullable=True, index=True)

    # Google's document id. The URL is derived from it rather than stored, so
    # there is one source of truth for which document this is.
    document_id = Column(String(128), nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    def __repr__(self) -> str:
        return f"<PRReport({self.repo}#{self.pr_number} -> {self.document_id})>"


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
    # Work items this PR belongs to, newline-separated ("LOC-42").
    #
    # Denormalized from the analysis so the worklist can group pull requests
    # into tasks without parsing every stored result. A task that spans three
    # PRs should read as one thing that has been running for two weeks, not as
    # three unrelated young items.
    ticket_keys = Column(Text, nullable=True)
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


class CommunicationEvent(Base):
    """
    Every message Locus searched, sent, or received about one pull request.

    The dashboard could already say *that* Slack was searched and *that* the
    test team was emailed. It could not say what was searched for, what came
    back, or what was actually sent -- which is the first thing anyone asks
    when a run produces a surprising result, and the thing that decides
    whether the agent is trusted.

    One table rather than one per channel: the review loop and the QA loop
    both want a single time-ordered story, and joining three tables to build
    it would guarantee they drift.

    Bodies are stored verbatim, including inbound text written by anyone who
    can post in a channel or review a PR. Nothing here is fed back to a model
    with tools bound -- it is a record, and the UI renders it as plain text.
    """

    __tablename__ = "communication_events"

    id = Column(Integer, primary_key=True, index=True)
    repo = Column(String(255), nullable=False, index=True)
    pr_number = Column(Integer, nullable=False, index=True)
    # The work item this belongs to, when one is known -- "LOC-42", "#7".
    #
    # A ticket routinely spans several pull requests: the feature, the fix
    # after QA rejected it, the follow-up. Keyed only by PR, each of those
    # starts from an empty history and re-gathers everything. Nullable
    # because a PR with no ticket is ordinary and must keep working.
    ticket_key = Column(String(64), nullable=True, index=True)

    # review | qa | context -- which loop this belongs to. "context" is the
    # pre-review gathering pass, which searches but never sends.
    loop = Column(String(16), nullable=False, index=True)
    # searched | sent | received
    direction = Column(String(16), nullable=False)
    # slack | email | github
    channel = Column(String(16), nullable=False)

    # Who, in that channel's own terms: a Slack display name, an email
    # address, a GitHub login. Nullable because a search match may have none.
    participant = Column(String(255), nullable=True)
    # Where it went or came from: "#code-review", "qa@acme.com", "PR #42".
    target = Column(String(255), nullable=True)
    subject = Column(String(512), nullable=True)
    # The message itself. The point of the table.
    body = Column(Text, nullable=True)
    # What was searched for, when direction is "searched". Kept because a
    # search that returns nothing is only diagnosable if the query is visible.
    query = Column(String(512), nullable=True)
    permalink = Column(String(1024), nullable=True)
    # Free-form label the UI shows as a chip: a QA verdict, a review state.
    outcome = Column(String(32), nullable=True)
    # False when a send was attempted and rejected. A message that failed to
    # send is more important to show than one that succeeded.
    succeeded = Column(Integer, nullable=False, default=1)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    def __repr__(self) -> str:
        return (
            f"<CommunicationEvent({self.repo}#{self.pr_number} "
            f"{self.direction} {self.channel})>"
        )


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
    # Jira status to move tickets to. Forward-only; see merge_actions.
    jira_done_status = Column(String(64), nullable=False, default="Done")
    close_issues_on_merge = Column(Integer, nullable=False, default=1)
    # Hold the work item open until the testing team signs off, rather than
    # closing it at merge. See qa_feedback for why this is the safer default
    # for teams whose QA loop actually answers.
    close_on_qa_signoff = Column(Integer, nullable=False, default=0)
    # GitHub logins of the senior devs who review this repo, newline-separated.
    # Used to address review notifications; reviews from anyone else are still
    # recorded, since GitHub does not restrict who may review.
    reviewers = Column(Text, nullable=True)
    # Where each reviewer is actually reachable, one per line:
    #   github-login, @slack-handle, email@company.com
    # A GitHub login is not a Slack handle and not an address; without this
    # the UI can only say "a review was requested" and not who was reached.
    reviewer_contacts = Column(Text, nullable=True)
    # Channel for review-loop notifications. Separate from slack_channel: PR
    # summaries are for the team, a review request is for one person, and
    # collapsing them buries the request in the feed.
    review_slack_channel = Column(String(255), nullable=True)
    # Merge automatically once a review approves and the gate passes. Off by
    # default: this is the only path that writes to a default branch with no
    # human in the loop, and it must be turned on deliberately.
    auto_merge_on_approval = Column(Integer, nullable=False, default=0)
    merge_method = Column(String(16), nullable=False, default="squash")
    # Move the issue's GitHub Projects card as the pipeline advances. On by
    # default: unlike auto-merge this writes nothing to any branch, and a board
    # that silently disagrees with the pipeline is the problem it solves.
    project_board_sync = Column(Integer, nullable=False, default=1)
    # Stage -> column name, one "stage: column" per line. Blank means the
    # default map in project_board. A stage left out moves no card, which is
    # what makes a partial map safe to write.
    project_column_map = Column(Text, nullable=True)
    # Who writes the code for this repo's tickets: "assisted" (a person) or
    # "autonomous" (the authoring driver). NULL is how resolve_settings hears
    # "this repo says nothing" and falls through to the account defaults --
    # which is why this is nullable where the defaults column is not.
    authoring_mode = Column(String(16), nullable=True)
    # The first attempt plus this many reworks. NULL falls through.
    autonomous_max_rounds = Column(Integer, nullable=True)
    # Display only. resolve_settings is the sole arbiter of what a run does;
    # a preset expanded at read time would be a second resolution layer.
    preset_label = Column(String(64), nullable=True)
    # Where this repo is checked out locally. NULL falls back to
    # LOCUS_CODE_ROOT, and failing that to a managed clone.
    source_path = Column(Text, nullable=True)
    # Run once in the fresh worktree before the agent (uv sync, npm ci).
    prepare_command = Column(Text, nullable=True)
    # The authoring test gate. NULL means no gate.
    test_command = Column(Text, nullable=True)
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
    close_on_qa_signoff = Column(Integer, nullable=False, default=0)
    reviewers = Column(Text, nullable=True)  # newline-separated GitHub logins
    reviewer_contacts = Column(Text, nullable=True)
    review_slack_channel = Column(String(255), nullable=True)
    auto_merge_on_approval = Column(Integer, nullable=False, default=0)
    merge_method = Column(String(16), nullable=False, default="squash")
    project_board_sync = Column(Integer, nullable=False, default=1)
    project_column_map = Column(Text, nullable=True)
    # A defaults row that exists is a deliberate choice, so unlike the repo
    # columns these are NOT NULL -- they must never read back as "says
    # nothing". Assisted by default: a mode that writes code on its own has to
    # be turned on, never inherited.
    authoring_mode = Column(String(16), nullable=False, default="assisted")
    autonomous_max_rounds = Column(Integer, nullable=False, default=2)
    preset_label = Column(String(64), nullable=True)
    source_path = Column(Text, nullable=True)
    prepare_command = Column(Text, nullable=True)
    test_command = Column(Text, nullable=True)
    # Newline-separated Google Doc ids read as context on every run. Per-repo
    # docs describe one codebase; these are the standards that apply to all of
    # them, and without them an unregistered repo reviews against nothing.
    context_doc_ids = Column(Text, nullable=True)

    # ---- the agent runtime -------------------------------------------------
    #
    # How this account's authoring agent runs, as opposed to which tickets it
    # is allowed to write. These were environment variables, which made them
    # one operator's choice for every tenant on the deployment -- including
    # `authoring_context`, which decides whether internal Slack discussion may
    # be sent to a third party. That is a tenant's policy, not the operator's.
    #
    # Every column is nullable, and NULL means "inherit": the environment
    # variable first, then the code's constant. That is what keeps an existing
    # single-machine install working with nothing saved here, and it is why
    # `allow_in_place` is an Integer rather than a Boolean -- it has three
    # states, and NULL is one of them.
    #
    # Account-level only, deliberately. The repo registration already carries
    # the per-repo axis (mode, rounds, source_path, prepare and test commands);
    # these describe the agent itself, and a second copy per repo would be a
    # resolution layer with nothing to resolve.

    # opencode | none. NULL falls back to LOCUS_AUTHORING_DRIVER.
    authoring_driver = Column(String(32), nullable=True)
    # Pins OpenCode's model for reproducibility across attempts. Unset lets
    # OpenCode use its own.
    authoring_model = Column(Text, nullable=True)
    # The invocation template, e.g. "opencode run --prompt-file {prompt}".
    # A template rather than flags: OpenCode's CLI surface moves.
    authoring_command = Column(Text, nullable=True)
    # full | ticket_only -- how much of the brief leaves the machine.
    authoring_context = Column(String(16), nullable=True)

    # The bounds. Every one of these spends a reviewer's attention when it is
    # too loose, which is the scarce resource the whole mode consumes.
    authoring_timeout_seconds = Column(Integer, nullable=True)
    max_changed_files = Column(Integer, nullable=True)
    max_changed_lines = Column(Integer, nullable=True)
    max_open_autonomous_prs = Column(Integer, nullable=True)

    # Who the agent's commits are attributed to. Also how a human's commits on
    # a branch are told apart from a previous attempt's, so changing it while
    # an attempt is open makes the agent's own commits read as a person's.
    agent_commit_name = Column(String(120), nullable=True)
    agent_commit_email = Column(String(255), nullable=True)

    # Where repositories already sit, and where the agent is allowed to work.
    # Two different questions -- conflating them is how the agent ends up
    # editing Locus itself, which `workspace.check_not_locus` refuses whatever
    # is stored here.
    code_root = Column(Text, nullable=True)
    workspace_root = Column(Text, nullable=True)
    # Tri-state: NULL inherits LOCUS_ALLOW_IN_PLACE, 0 and 1 are choices.
    allow_in_place = Column(Integer, nullable=True)
    workspace_ttl_days = Column(Integer, nullable=True)

    # GitHub logins asked to review the pull requests the agent opens, one per
    # line. Deliberately separate from `reviewers`, which addresses the review
    # loop's Slack pings: that list names who is *expected* to review, and
    # turning it into a GitHub review request would start notifying people who
    # only ever consented to being mentioned. NULL means the agent opens the
    # pull request and requests nobody, which is what it did before this.
    autonomous_pr_reviewers = Column(Text, nullable=True)

    # ---- the calendar agent ------------------------------------------------
    # Per-user dials on a per-user agent. The sweep interval is how often this
    # account's calendars are checked; the loop still ticks on its own clock.
    calendar_sweep_minutes = Column(Integer, nullable=True)
    calendar_lookahead_days = Column(Integer, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # One row per user; the unique constraint is what makes "upsert by owner"
    # safe rather than silently accumulating rows.
    owner_id = Column(
        Integer, ForeignKey("users.id"), nullable=False, unique=True, index=True
    )

    def __repr__(self) -> str:
        return f"<PRAgentDefaults(owner_id={self.owner_id})>"


class WorkItemSettings(Base):
    """
    Per-work-item overrides of the authoring mode.

    The third and most specific source `resolve_settings` reads. Autonomy is a
    judgement about *this ticket* -- a dependency bump and a change to the
    credential path are not the same risk -- and an account-wide toggle forces
    the most dangerous ticket in the backlog to set policy for all of them,
    which is how teams end up leaving the mode off entirely.

    Deliberately narrow: only the authoring fields live here. Rows are sparse,
    so absence means "inherit", never "assisted".
    """

    __tablename__ = "work_item_settings"

    id = Column(Integer, primary_key=True, index=True)
    # Jira key ("LOC-42") or the "owner/repo#N" fallback worklist._task_key
    # already groups on. Same key space as PRReview.ticket_keys.
    ticket_key = Column(String(128), nullable=False, index=True)
    authoring_mode = Column(String(16), nullable=True)
    autonomous_max_rounds = Column(Integer, nullable=True)
    # Set when the bound was exhausted, or when a human took the branch over.
    # Distinct from someone choosing `assisted` by hand: this reads in the UI
    # as "handed back after N attempts", and it is what stops the next event
    # re-triggering the driver.
    handed_back_at = Column(DateTime(timezone=True), nullable=True)
    handed_back_reason = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    __table_args__ = (
        UniqueConstraint("owner_id", "ticket_key", name="uq_work_item_settings"),
    )

    def __repr__(self) -> str:
        return f"<WorkItemSettings(ticket_key={self.ticket_key}, mode={self.authoring_mode})>"


class AuthoringAttempt(Base):
    """
    One run of the authoring driver against one work item.

    Append-only, the same argument as `PRReviewRound`: a mutable counter can
    say the agent has tried three times but cannot say *why* it tried again,
    and "the agent has tried three things" and "the agent tried once and a
    reviewer pushed back twice" are different situations needing different
    responses from the person the work eventually returns to.

    Every outcome is recorded, including the ones that opened nothing -- a
    timeout, an oversized diff, a denylisted path. That is what makes the bound
    real: a failure that left no row would not consume an attempt, and a
    reliably-failing ticket would retry forever.
    """

    __tablename__ = "authoring_attempts"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    ticket_key = Column(String(128), nullable=False, index=True)
    repo = Column(String(255), nullable=True, index=True)
    # Null on every outcome that opened nothing, which is most of them.
    pr_number = Column(Integer, nullable=True)

    attempt = Column(Integer, nullable=False, default=1)
    # initial | changes_requested | qa_rejected
    trigger = Column(String(32), nullable=False, default="initial")

    driver = Column(String(64), nullable=False, default="none")
    # Recorded per attempt rather than read from config at display time.
    # "Which model wrote this, and how much of our internal discussion did it
    # see" is asked after the fact, when the config value has already moved on.
    model = Column(String(128), nullable=True)
    context_mode = Column(String(32), nullable=True)

    source_path = Column(Text, nullable=True)
    workspace_path = Column(Text, nullable=True)

    # running | finished. Written `running` before the driver is invoked and
    # updated when it returns.
    #
    # The row used to be inserted only on the way out, which had two costs. The
    # board could not say the agent was working -- a card sat on `assigned` for
    # the ten minutes a run takes, indistinguishable from one nobody had
    # started. And a process that died mid-run left no row at all, so the
    # attempt was never consumed: "every failure consumes an attempt" held for
    # every failure the driver reported and not for the one that killed it.
    #
    # `finished` is the default so rows written before this column existed read
    # correctly rather than appearing to be stuck mid-run forever.
    state = Column(String(16), nullable=False, default="finished", index=True)

    opened = Column(Integer, nullable=False, default=0)
    error = Column(Text, nullable=True)
    files_changed = Column(Integer, nullable=False, default=0)
    lines_changed = Column(Integer, nullable=False, default=0)
    duration_seconds = Column(Float, nullable=False, default=0.0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    # When the driver actually returned. Distinct from `created_at`, which is
    # now when it started -- the gap between them is how long the agent has
    # been working, which is what a live card counts up.
    finished_at = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return (
            f"<AuthoringAttempt(ticket={self.ticket_key}, attempt={self.attempt}, "
            f"state={self.state}, opened={bool(self.opened)})>"
        )


class TimeAgentSettings(Base):
    """
    The calendar agent's settings, one row per user.

    Per user rather than per repo, because a calendar belongs to a person.

    Four things are off by default, each for its own reason. `enabled`, because
    a feature that starts touching a calendar unasked is the worst first
    impression available. `auto_apply`, because a moved meeting is visible to
    everyone invited. Both auto-replies, because they post to real people --
    the same category as auto-merge, and they earn the same treatment.
    """

    __tablename__ = "time_agent_settings"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(
        Integer, ForeignKey("users.id"), nullable=False, unique=True, index=True
    )

    enabled = Column(Integer, nullable=False, default=0)
    # Propose versus act. With this off the proposal is stored and surfaced,
    # and POST /schedule/apply executes it unchanged.
    auto_apply = Column(Integer, nullable=False, default=0)
    auto_reply_invites = Column(Integer, nullable=False, default=0)
    auto_reply_busy = Column(Integer, nullable=False, default=0)

    # "HH:MM", interpreted in User.timezone through a real timezone library.
    # The default zone is UTC+05:30 and the half-hour offset breaks naive hour
    # arithmetic, which is why nothing here is an integer offset.
    working_hours_start = Column(String(5), nullable=False, default="09:30")
    working_hours_end = Column(String(5), nullable=False, default="18:30")
    protect_focus_blocks = Column(Integer, nullable=False, default=1)

    # "U04AB...", not a handle.
    #
    # A Slack mention arrives in message text as `<@U04AB…>` while
    # `reviewer_contacts` stores handles -- different namespaces that never
    # compare equal, which is why mention matching silently never fires
    # without this. Resolved once via auth.test.
    slack_member_id = Column(String(32), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def __repr__(self) -> str:
        return f"<TimeAgentSettings(owner_id={self.owner_id}, enabled={self.enabled})>"


class ScheduleProposalRecord(Base):
    """
    A reshuffle the calendar agent proposed, waiting for a human.

    Stored rather than sent, because with `auto_apply` off the proposal has to
    survive until somebody looks at it -- and `POST /schedule/apply` already
    exists as the confirm step, which is exactly the propose-only shape this
    needs.

    Anything with external attendees is reported blocked rather than moved, and
    that is `scheduler.classify_event`'s existing behaviour: this table records
    proposals, it does not weaken them.
    """

    __tablename__ = "schedule_proposals"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # What prompted it: a conflict found by the sweep, or an interruption.
    trigger = Column(String(255), nullable=False)
    # The serialized ScheduleProposal, so applying it later runs the same plan
    # that was shown rather than a freshly recomputed one.
    proposal_json = Column(Text, nullable=False)
    summary = Column(Text, nullable=True)

    # pending | applied | dismissed | superseded
    state = Column(String(16), nullable=False, default="pending", index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<ScheduleProposalRecord(owner_id={self.owner_id}, state={self.state})>"


class InterruptionEvent(Base):
    """
    Somebody reached the owner while they were booked, and what Locus said.

    This cannot live in `communication_events`: that table's `repo` and
    `pr_number` are NOT NULL, and an interruption has neither. Reusing it would
    mean inventing a sentinel repo, which the next reader takes for real.

    `importance_source` is what makes a wrong escalation debuggable. Two of the
    three are deterministic facts -- the sender is a reviewer mid-round, or the
    message names a work item the worklist reports blocked on you -- and only
    the third is a model's judgement. The UI says which, and the model-made one
    reads as weaker than the other two.
    """

    __tablename__ = "interruption_events"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    occurred_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    channel = Column(String(16), nullable=False, default="slack")
    participant = Column(String(255), nullable=True)
    thread_ts = Column(String(32), nullable=True, index=True)
    slack_channel = Column(String(64), nullable=True, index=True)

    # free | busy | focus | off_hours -- what the calendar said at the time.
    availability_state = Column(String(16), nullable=False, default="free")
    # important | routine
    importance = Column(String(16), nullable=False, default="routine")
    # reviewer | worklist | classifier
    importance_source = Column(String(16), nullable=False, default="classifier")

    replied = Column(Integer, nullable=False, default=0)
    # Stored **as sent**, passed to the log rather than reconstructed. A
    # reconstruction drifts from what the channel actually saw, which makes the
    # record worse than useless -- the same reason
    # `merge_actions._qa_email_text` exists.
    reply_body = Column(Text, nullable=True)
    proposal_id = Column(Integer, nullable=True)
    # A clipped quote of what they said, for the strip. Not the whole message:
    # this is a record of an interruption, not a second copy of Slack.
    excerpt = Column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<InterruptionEvent(owner_id={self.owner_id}, state={self.availability_state})>"


class LLMSetting(Base):
    """
    Which model backend one user's work runs on.

    The provider, the endpoint and the key used to be environment
    configuration, which is right for one machine and wrong for a product:
    two tenants of the same deployment cannot share a `.env`, and nobody
    should have to restart the backend to change a model id. One row per
    user, and the key is Fernet-encrypted at rest like every other
    credential in this schema.

    Every column is nullable and blank means "fall back to the environment",
    so an existing single-tenant deployment keeps working untouched and a
    user can override the endpoint without also having to restate the models.
    """

    __tablename__ = "llm_settings"

    id = Column(Integer, primary_key=True, index=True)
    # Unique: this is settings, not history. A second row would make "which
    # backend am I on" a question with two answers.
    owner_id = Column(
        Integer, ForeignKey("users.id"), nullable=False, unique=True, index=True
    )

    # local | openai | anthropic | gemini. Blank falls back to LLM_PROVIDER.
    provider = Column(String(32), nullable=True)
    # The OpenAI-compatible endpoint. Configurable for every provider, not
    # only the local one: self-hosted vLLM, Ollama, LiteLLM, OpenRouter and an
    # Azure deployment are all "OpenAI-compatible at some other URL", and
    # hard-coding one address is what made the local server special.
    base_url = Column(String(500), nullable=True)
    fast_model = Column(String(200), nullable=True)
    smart_model = Column(String(200), nullable=True)
    # Never returned by any endpoint -- the API reports whether one is set.
    encrypted_api_key = Column(Text, nullable=True)
    timeout_seconds = Column(Float, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    owner = relationship("User")

    def __repr__(self) -> str:
        return f"<LLMSetting(owner_id={self.owner_id}, provider={self.provider})>"
