"""
CRUD Operations
Database create/read operations with encryption
"""

from typing import Optional, Any
from sqlalchemy.orm import Session

from app import models, schemas, security


# ============== User Operations ==============

def get_user_by_email(db: Session, email: str) -> Optional[models.User]:
    """Get a user by email address."""
    return db.query(models.User).filter(models.User.email == email).first()


def get_user_by_id(db: Session, user_id: int) -> Optional[models.User]:
    """Get a user by ID."""
    return db.query(models.User).filter(models.User.id == user_id).first()


def create_user(db: Session, user: schemas.UserCreate) -> models.User:
    """
    Create a new user with hashed password.
    
    Args:
        db: Database session
        user: User creation schema with email and password
        
    Returns:
        Created User model instance
    """
    hashed_password = security.get_password_hash(user.password)
    db_user = models.User(
        email=user.email,
        name=user.name,
        hashed_password=hashed_password
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


def authenticate_user(db: Session, email: str, password: str) -> Optional[models.User]:
    """Authenticate user with email and password."""
    user = get_user_by_email(db, email)
    if not user:
        return None
    if not security.verify_password(password, user.hashed_password):
        return None
    return user


def update_user(db: Session, user_id: int, user_update: schemas.UserUpdate) -> Optional[models.User]:
    """
    Update user details.
    
    Args:
        db: Database session
        user_id: ID of user to update
        user_update: Schema with update fields
        
    Returns:
        Updated User model or None if user not found
    """
    db_user = get_user_by_id(db, user_id)
    if not db_user:
        return None
    
    if user_update.name is not None:
        db_user.name = user_update.name
    
    if user_update.email is not None:
        db_user.email = user_update.email
        
    if user_update.password is not None:
        db_user.hashed_password = security.get_password_hash(user_update.password)
        
    db.commit()
    db.refresh(db_user)
    return db_user


def set_user_gemini_key(db: Session, user_id: int, gemini_key: str) -> bool:
    """
    Set or update user's Gemini API key (encrypted).
    
    Args:
        db: Database session
        user_id: User ID
        gemini_key: Gemini API key (will be encrypted)
        
    Returns:
        True if successful, False if user not found
    """
    user = get_user_by_id(db, user_id)
    if not user:
        return False
    
    user.encrypted_gemini_key = security.encrypt_token(gemini_key) if gemini_key else None
    db.commit()
    return True


def get_user_gemini_key(db: Session, user_id: int) -> Optional[str]:
    """
    Get decrypted Gemini API key for a user.
    
    Args:
        db: Database session
        user_id: User ID
        
    Returns:
        Decrypted Gemini API key or None if not set
    """
    user = get_user_by_id(db, user_id)
    if not user or not user.encrypted_gemini_key:
        return None
    return security.decrypt_token(user.encrypted_gemini_key)


def has_gemini_key(db: Session, user_id: int) -> bool:
    """Check if user has a Gemini API key configured."""
    user = get_user_by_id(db, user_id)
    return user is not None and user.encrypted_gemini_key is not None


def delete_user_gemini_key(db: Session, user_id: int) -> bool:
    """Delete user's Gemini API key."""
    user = get_user_by_id(db, user_id)
    if not user:
        return False
    user.encrypted_gemini_key = None
    db.commit()
    return True

# ============== Integration Operations ==============

def get_user_integrations(db: Session, user_id: int) -> list[models.Integration]:
    """Get all integrations for a user."""
    return db.query(models.Integration).filter(
        models.Integration.owner_id == user_id
    ).all()


def get_integration(
    db: Session, 
    user_id: int, 
    service_name: str
) -> Optional[models.Integration]:
    """Get a specific integration by user and service name."""
    return db.query(models.Integration).filter(
        models.Integration.owner_id == user_id,
        models.Integration.service_name == service_name.lower()
    ).first()


def add_integration(
    db: Session,
    user_id: int,
    service_name: str,
    api_key: Optional[str] = None,
    credentials: Optional[dict[str, Any]] = None
) -> models.Integration:
    """
    Add or update an integration with encrypted credentials.
    
    Args:
        db: Database session
        user_id: Owner user ID
        service_name: Name of the service (jira, gmail, etc.)
        api_key: Optional API key (will be encrypted)
        credentials: Optional OAuth/complex credentials (will be encrypted)
        
    Returns:
        Created or updated Integration model instance
    """
    # Check if integration already exists
    existing = get_integration(db, user_id, service_name)
    
    # Encrypt sensitive data
    encrypted_api_key = security.encrypt_token(api_key) if api_key else None
    encrypted_creds = security.encrypt_credentials(credentials) if credentials else None
    
    if existing:
        # Update existing integration
        existing.encrypted_api_key = encrypted_api_key
        existing.encrypted_credentials = encrypted_creds
        db.commit()
        db.refresh(existing)
        return existing
    
    # Create new integration
    db_integration = models.Integration(
        service_name=service_name.lower(),
        encrypted_api_key=encrypted_api_key,
        encrypted_credentials=encrypted_creds,
        owner_id=user_id
    )
    db.add(db_integration)
    db.commit()
    db.refresh(db_integration)
    return db_integration


def get_integration_key(
    db: Session, 
    user_id: int, 
    service_name: str
) -> Optional[str]:
    """
    Get decrypted API key for a service.
    
    Args:
        db: Database session
        user_id: Owner user ID
        service_name: Name of the service
        
    Returns:
        Decrypted API key or None if not found
    """
    integration = get_integration(db, user_id, service_name)
    if not integration or not integration.encrypted_api_key:
        return None
    return security.decrypt_token(integration.encrypted_api_key)


def get_integration_credentials(
    db: Session, 
    user_id: int, 
    service_name: str
) -> Optional[dict[str, Any]]:
    """
    Get decrypted credentials for a service.
    
    Args:
        db: Database session
        user_id: Owner user ID
        service_name: Name of the service
        
    Returns:
        Decrypted credentials dict or None if not found
    """
    integration = get_integration(db, user_id, service_name)
    if not integration or not integration.encrypted_credentials:
        return None
    return security.decrypt_credentials(integration.encrypted_credentials)


def delete_integration(db: Session, user_id: int, service_name: str) -> bool:
    """Delete an integration."""
    integration = get_integration(db, user_id, service_name)
    if not integration:
        return False
    db.delete(integration)
    db.commit()
    return True


# Alias for OAuth router compatibility
get_user_integration = get_integration


def update_integration_credentials(
    db: Session,
    integration_id: int,
    credentials: dict[str, Any]
) -> bool:
    """
    Update credentials for an existing integration.
    
    Args:
        db: Database session
        integration_id: ID of the integration to update
        credentials: New credentials (will be encrypted)
        
    Returns:
        True if updated, False if not found
    """
    integration = db.query(models.Integration).filter(
        models.Integration.id == integration_id
    ).first()
    
    if not integration:
        return False
    
    encrypted_creds = security.encrypt_credentials(credentials) if credentials else None
    integration.encrypted_credentials = encrypted_creds
    db.commit()
    return True


# ============== Conversation Operations ==============

def create_conversation(
    db: Session,
    user_id: int,
    title: str = "New Chat"
) -> models.Conversation:
    """Create a new conversation for a user."""
    db_conversation = models.Conversation(
        owner_id=user_id,
        title=title
    )
    db.add(db_conversation)
    db.commit()
    db.refresh(db_conversation)
    return db_conversation


def get_conversation(db: Session, conversation_id: int) -> Optional[models.Conversation]:
    """Get a conversation by ID."""
    return db.query(models.Conversation).filter(
        models.Conversation.id == conversation_id
    ).first()


def get_user_conversations(db: Session, user_id: int) -> list[models.Conversation]:
    """Get all conversations for a user, ordered by most recent first."""
    return db.query(models.Conversation).filter(
        models.Conversation.owner_id == user_id
    ).order_by(models.Conversation.updated_at.desc().nullsfirst(), models.Conversation.created_at.desc()).all()


def update_conversation_title(
    db: Session,
    conversation_id: int,
    title: str
) -> Optional[models.Conversation]:
    """Update a conversation's title."""
    conversation = get_conversation(db, conversation_id)
    if not conversation:
        return None
    conversation.title = title
    db.commit()
    db.refresh(conversation)
    return conversation


def delete_conversation(db: Session, conversation_id: int) -> bool:
    """Delete a conversation and all its messages."""
    conversation = get_conversation(db, conversation_id)
    if not conversation:
        return False
    db.delete(conversation)
    db.commit()
    return True


# ============== Message Operations ==============

def add_message(
    db: Session,
    conversation_id: int,
    role: str,
    content: str,
    actions_json: Optional[str] = None
) -> models.Message:
    """Add a message to a conversation."""
    db_message = models.Message(
        conversation_id=conversation_id,
        role=role,
        content=content,
        actions_json=actions_json
    )
    db.add(db_message)
    db.commit()
    db.refresh(db_message)
    return db_message


def get_conversation_messages(db: Session, conversation_id: int) -> list[models.Message]:
    """Get all messages for a conversation, ordered by creation time."""
    return db.query(models.Message).filter(
        models.Message.conversation_id == conversation_id
    ).order_by(models.Message.created_at).all()
