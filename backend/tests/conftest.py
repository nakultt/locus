"""
Shared test configuration.

SECRET_KEY and ENCRYPTION_KEY are required at import time -- app.security
raises rather than falling back, because a generated encryption key silently
destroys stored credentials and a default JWT secret lets anyone forge a
token. Tests supply throwaway values before any app module is imported.
"""

import os
from pathlib import Path

from cryptography.fernet import Fernet

os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ.setdefault("SECRET_KEY", "test-only-secret-not-used-outside-tests")

# Forced, not `setdefault`. A real DATABASE_URL in the environment or in
# backend/.env would otherwise win, and the suite would run against a
# developer's actual database -- the background loops started by TestClient
# write to whatever this resolves to.
_TEST_DB = Path(__file__).resolve().parent.parent / "test_locus.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB.as_posix()}"

# Dropped between runs so the file cannot outlive a schema change. It is
# recreated by `Base.metadata.create_all()` at app startup; keeping a stale one
# produced "no such column" failures that looked like application bugs.
if _TEST_DB.exists():
    try:
        _TEST_DB.unlink()
    except OSError:
        # Windows keeps a handle open if a previous run died mid-write. The
        # file is still usable; a genuinely stale schema will surface loudly.
        pass
