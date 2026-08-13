"""
Shared test configuration.

SECRET_KEY and ENCRYPTION_KEY are required at import time -- app.security
raises rather than falling back, because a generated encryption key silently
destroys stored credentials and a default JWT secret lets anyone forge a
token. Tests supply throwaway values before any app module is imported.
"""

import os

from cryptography.fernet import Fernet

os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ.setdefault("SECRET_KEY", "test-only-secret-not-used-outside-tests")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_locus.db")
