"""
Security Utilities
Password hashing (bcrypt) and token encryption (Fernet)
"""

import os
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from passlib.context import CryptContext
from cryptography.fernet import Fernet
from jose import jwt, JWTError
from dotenv import load_dotenv

load_dotenv()

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Encryption key for API tokens
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")

if not ENCRYPTION_KEY:
    # Generate a key for development (in production, always use env var)
    ENCRYPTION_KEY = Fernet.generate_key().decode()
    print("WARNING: Using generated ENCRYPTION_KEY. Set this in .env for production!")

# Ensure key is bytes
if isinstance(ENCRYPTION_KEY, str):
    ENCRYPTION_KEY = ENCRYPTION_KEY.encode()

fernet = Fernet(ENCRYPTION_KEY)

# JWT Configuration
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-for-jwt-here")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days


# ============== JWT Functions ==============

def create_access_token(
    user_id: int, 
    email: str, 
    name: Optional[str] = None,
    remember_me: bool = False
) -> str:
    """Create a JWT access token for a user."""
    if remember_me:
        expire = datetime.now(timezone.utc) + timedelta(days=30)
    else:
        expire = datetime.now(timezone.utc) + timedelta(hours=1)
    to_encode = {
        "sub": str(user_id),
        "email": email,
        "name": name,
        "exp": expire
    }
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def verify_token(token: str) -> Optional[dict]:
    """Verify and decode a JWT token. Returns payload or None if invalid."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


# ============== Password Functions ==============

def get_password_hash(password: str) -> str:
    """Hash a password using bcrypt."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return pwd_context.verify(plain_password, hashed_password)


# ============== Token Encryption Functions ==============

def encrypt_token(token: str) -> str:
    """Encrypt an API token using Fernet symmetric encryption."""
    if not token:
        return ""
    encrypted = fernet.encrypt(token.encode())
    return encrypted.decode()


def decrypt_token(encrypted_token: str) -> str:
    """Decrypt an API token."""
    if not encrypted_token:
        return ""
    decrypted = fernet.decrypt(encrypted_token.encode())
    return decrypted.decode()


# ============== Credentials Encryption (for OAuth/complex auth) ==============

def encrypt_credentials(credentials: dict[str, Any]) -> str:
    """Encrypt a credentials dictionary as JSON."""
    if not credentials:
        return ""
    json_str = json.dumps(credentials)
    encrypted = fernet.encrypt(json_str.encode())
    return encrypted.decode()


def decrypt_credentials(encrypted_credentials: str) -> dict[str, Any]:
    """Decrypt credentials back to dictionary."""
    if not encrypted_credentials:
        return {}
    decrypted = fernet.decrypt(encrypted_credentials.encode())
    return json.loads(decrypted.decode())
