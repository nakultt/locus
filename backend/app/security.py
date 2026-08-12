"""
Security Utilities
Password hashing (bcrypt) and token encryption (Fernet)
"""

import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
from cryptography.fernet import Fernet
from dotenv import load_dotenv
from jose import JWTError, jwt

load_dotenv()

# bcrypt is used directly rather than through passlib. passlib 1.7.4 is
# unmaintained (2020) and raises on bcrypt >= 5, which was pinning us to
# bcrypt 4.0.1. The stored hash format ($2b$) is unchanged, so hashes created
# under passlib still verify.
BCRYPT_ROUNDS = 12

# bcrypt truncates at 72 bytes and errors on longer input; hash a digest of
# anything longer so long passwords stay usable and distinguishable.
_MAX_BCRYPT_BYTES = 72

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
    name: str | None = None,
    remember_me: bool = False
) -> str:
    """Create a JWT access token for a user."""
    if remember_me:
        expire = datetime.now(UTC) + timedelta(days=30)
    else:
        expire = datetime.now(UTC) + timedelta(hours=1)
    to_encode = {
        "sub": str(user_id),
        "email": email,
        "name": name,
        "exp": expire
    }
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def verify_token(token: str) -> dict | None:
    """Verify and decode a JWT token. Returns payload or None if invalid."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


# ============== Password Functions ==============

def _prepare(password: str) -> bytes:
    """
    Encode a password for bcrypt.

    bcrypt rejects input over 72 bytes. Rather than truncate -- which would make
    two long passwords sharing a 72-byte prefix interchangeable -- pre-hash
    anything longer with SHA-256 so the full input contributes.
    """
    raw = password.encode("utf-8")
    if len(raw) > _MAX_BCRYPT_BYTES:
        return hashlib.sha256(raw).hexdigest().encode("ascii")
    return raw


def get_password_hash(password: str) -> str:
    """Hash a password using bcrypt."""
    return bcrypt.hashpw(_prepare(password), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    try:
        return bcrypt.checkpw(_prepare(plain_password), hashed_password.encode())
    except (ValueError, TypeError):
        # Malformed or unrecognized hash in the database.
        return False


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
