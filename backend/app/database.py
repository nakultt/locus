"""
Database Configuration
SQLAlchemy engine and session setup for PostgreSQL/SQLite
"""

import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./conflux.db")

# Handle Render's postgres:// vs postgresql:// URL format
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Create engine with appropriate settings.
#
# Postgres is pinned to UTC rather than left on the server's zone. A session
# inherits the server default, so the same row serialized on a developer's
# machine and on a deployment carried different offsets -- "+05:30" locally,
# "+00:00" in production -- for the same instant. Both are correct and the
# difference is invisible until something compares or caches them.
#
# UTC is the storage zone; IST is the display zone, applied in the frontend
# (src/lib/datetime.ts) so every viewer reads the same wall clock regardless of
# where their browser thinks it is. Timestamps are stored as instants and given
# a zone only when shown to someone.
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False}
    )
else:
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        connect_args={"options": "-c timezone=utc"},
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """Dependency for database session injection."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
