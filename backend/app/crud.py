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
