"""
Database Models
SQLAlchemy ORM models for User and Integration tables
"""

from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime
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
    encrypted_gemini_key = Column(Text, nullable=True)  # User's own Gemini API key (encrypted)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationship: User has many Integrations
    integrations = relationship("Integration", back_populates="owner", cascade="all, delete-orphan")
    # Relationship: User has many Conversations
    conversations = relationship("Conversation", back_populates="owner", cascade="all, delete-orphan")

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


class Repository(Base):
    """GitHub repository model for incident analysis."""
    
    __tablename__ = "repositories"

    id = Column(Integer, primary_key=True, index=True)
    owner = Column(String(255), nullable=False)
    name = Column(String(255), nullable=False)
    default_branch = Column(String(100), nullable=False, default="main")
    github_token_encrypted = Column(Text, nullable=True)
    last_synced = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Foreign Key to User
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    # Relationships
    owner_user = relationship("User")
    suspect_commits = relationship("SuspectCommit", back_populates="repository", cascade="all, delete-orphan")
    analysis_repositories = relationship("AnalysisRepository", back_populates="repository", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Repository(id={self.id}, owner={self.owner}, name={self.name})>"


class IncidentAnalysis(Base):
    """Incident analysis model."""
    
    __tablename__ = "incident_analyses"

    id = Column(Integer, primary_key=True, index=True)
    analysis_uuid = Column(String(36), unique=True, nullable=False, index=True)
    log_content = Column(Text, nullable=False)
    log_format = Column(String(50), nullable=True)
    status = Column(String(20), nullable=False, default="pending")  # pending, processing, completed, failed
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Foreign Key to User
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    # Relationships
    owner = relationship("User")
    error_patterns = relationship("ErrorPattern", back_populates="analysis", cascade="all, delete-orphan")
    suspect_commits = relationship("SuspectCommit", back_populates="analysis", cascade="all, delete-orphan")
    timeline_events = relationship("TimelineEvent", back_populates="analysis", cascade="all, delete-orphan")
    shareable_reports = relationship("ShareableReport", back_populates="analysis", cascade="all, delete-orphan")
    analysis_repositories = relationship("AnalysisRepository", back_populates="analysis", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<IncidentAnalysis(id={self.id}, uuid={self.analysis_uuid}, status={self.status})>"


class AnalysisRepository(Base):
    """Junction table linking analyses to repositories."""
    
    __tablename__ = "analysis_repositories"

    id = Column(Integer, primary_key=True, index=True)
    analysis_id = Column(Integer, ForeignKey("incident_analyses.id"), nullable=False)
    repository_id = Column(Integer, ForeignKey("repositories.id"), nullable=False)

    # Relationships
    analysis = relationship("IncidentAnalysis", back_populates="analysis_repositories")
    repository = relationship("Repository", back_populates="analysis_repositories")

    def __repr__(self) -> str:
        return f"<AnalysisRepository(analysis_id={self.analysis_id}, repository_id={self.repository_id})>"


class ErrorPattern(Base):
    """Error pattern extracted from incident logs."""
    
    __tablename__ = "error_patterns"

    id = Column(Integer, primary_key=True, index=True)
    error_type = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    file_paths = Column(Text, nullable=True)  # JSON array
    function_names = Column(Text, nullable=True)  # JSON array
    line_numbers = Column(Text, nullable=True)  # JSON array
    timestamps = Column(Text, nullable=True)  # JSON array
    raw_stack_trace = Column(Text, nullable=True)

    # Foreign Key to IncidentAnalysis
    analysis_id = Column(Integer, ForeignKey("incident_analyses.id"), nullable=False)

    # Relationship
    analysis = relationship("IncidentAnalysis", back_populates="error_patterns")

    def __repr__(self) -> str:
        return f"<ErrorPattern(id={self.id}, error_type={self.error_type})>"


class SuspectCommit(Base):
    """Suspect commit identified during incident analysis."""
    
    __tablename__ = "suspect_commits"

    id = Column(Integer, primary_key=True, index=True)
    commit_sha = Column(String(40), nullable=False)
    author_name = Column(String(255), nullable=True)
    author_email = Column(String(255), nullable=True)
    commit_message = Column(Text, nullable=True)
    commit_timestamp = Column(DateTime(timezone=True), nullable=True)
    confidence_score = Column(Integer, nullable=False, default=0)  # 0-100
    matching_files = Column(Text, nullable=True)  # JSON array
    matching_functions = Column(Text, nullable=True)  # JSON array
    pr_number = Column(Integer, nullable=True)
    pr_title = Column(String(500), nullable=True)

    # Foreign Keys
    analysis_id = Column(Integer, ForeignKey("incident_analyses.id"), nullable=False)
    repository_id = Column(Integer, ForeignKey("repositories.id"), nullable=False)

    # Relationships
    analysis = relationship("IncidentAnalysis", back_populates="suspect_commits")
    repository = relationship("Repository", back_populates="suspect_commits")

    def __repr__(self) -> str:
        return f"<SuspectCommit(id={self.id}, sha={self.commit_sha}, confidence={self.confidence_score})>"


class TimelineEvent(Base):
    """Timeline event for incident analysis."""
    
    __tablename__ = "timeline_events"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    event_type = Column(String(50), nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    event_metadata = Column(Text, nullable=True)  # JSON (renamed from metadata to avoid SQLAlchemy conflict)

    # Foreign Key to IncidentAnalysis
    analysis_id = Column(Integer, ForeignKey("incident_analyses.id"), nullable=False)

    # Relationship
    analysis = relationship("IncidentAnalysis", back_populates="timeline_events")

    def __repr__(self) -> str:
        return f"<TimelineEvent(id={self.id}, type={self.event_type}, title={self.title})>"


class ShareableReport(Base):
    """Shareable report for incident analysis."""
    
    __tablename__ = "shareable_reports"

    id = Column(Integer, primary_key=True, index=True)
    share_uuid = Column(String(36), unique=True, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=True)
    access_count = Column(Integer, nullable=False, default=0)

    # Foreign Key to IncidentAnalysis
    analysis_id = Column(Integer, ForeignKey("incident_analyses.id"), nullable=False)

    # Relationship
    analysis = relationship("IncidentAnalysis", back_populates="shareable_reports")

    def __repr__(self) -> str:
        return f"<ShareableReport(id={self.id}, uuid={self.share_uuid}, access_count={self.access_count})>"
