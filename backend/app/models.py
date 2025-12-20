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
