"""
Unit Tests for Repository CRUD Operations
Tests repository connection management with encryption and caching
"""

import pytest
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from unittest.mock import patch, MagicMock

from app.database import Base
from app import crud, models, security
from app.services.repository_cache import (
    RepositoryMetadata, 
    clear_cache, 
    get_cached_metadata,
    cache_metadata
)


# Test database setup
SQLALCHEMY_DATABASE_URL = "sqlite:///./test_repository.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture
def db_session():
    """Create a test database session."""
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def test_user(db_session):
    """Create a test user."""
    user = models.User(
        email="test@example.com",
        name="Test User",
        hashed_password=security.get_password_hash("testpass123")
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def clear_repository_cache():
    """Clear repository cache before each test."""
    clear_cache()
    yield
    clear_cache()


class TestRepositoryCRUD:
    """Test repository CRUD operations."""
    
    def test_create_repository_success(self, db_session, test_user):
        """Test successful repository creation with encryption."""
        github_token = "ghp_test_token_123"
        
        repository = crud.create_repository(
            db=db_session,
            user_id=test_user.id,
            owner="testowner",
            name="testrepo",
            default_branch="main",
            github_token=github_token
        )
        
        assert repository.id is not None
        assert repository.user_id == test_user.id
        assert repository.owner == "testowner"
        assert repository.name == "testrepo"
        assert repository.default_branch == "main"
        assert repository.github_token_encrypted is not None
        assert repository.github_token_encrypted != github_token  # Should be encrypted
        
        # Verify token can be decrypted
        decrypted_token = crud.get_repository_github_token(db_session, test_user.id, repository.id)
        assert decrypted_token == github_token
    
    def test_create_repository_without_token(self, db_session, test_user):
        """Test repository creation without GitHub token."""
        repository = crud.create_repository(
            db=db_session,
            user_id=test_user.id,
            owner="testowner",
            name="testrepo"
        )
        
        assert repository.github_token_encrypted is None
        decrypted_token = crud.get_repository_github_token(db_session, test_user.id, repository.id)
        assert decrypted_token is None
    
    def test_create_duplicate_repository_fails(self, db_session, test_user):
        """Test that creating duplicate repository raises ValueError."""
        crud.create_repository(
            db=db_session,
            user_id=test_user.id,
            owner="testowner",
            name="testrepo"
        )
        
        with pytest.raises(ValueError, match="Repository testowner/testrepo already connected"):
            crud.create_repository(
                db=db_session,
                user_id=test_user.id,
                owner="testowner",
                name="testrepo"
            )
    
    def test_get_repository_by_id(self, db_session, test_user):
        """Test getting repository by ID."""
        created_repo = crud.create_repository(
            db=db_session,
            user_id=test_user.id,
            owner="testowner",
            name="testrepo"
        )
        
        retrieved_repo = crud.get_repository_by_id(db_session, test_user.id, created_repo.id)
        assert retrieved_repo is not None
        assert retrieved_repo.id == created_repo.id
        assert retrieved_repo.owner == "testowner"
        assert retrieved_repo.name == "testrepo"
        
        # Test with wrong user ID
        wrong_user_repo = crud.get_repository_by_id(db_session, 999, created_repo.id)
        assert wrong_user_repo is None
    
    def test_get_repository_by_name(self, db_session, test_user):
        """Test getting repository by owner/name."""
        crud.create_repository(
            db=db_session,
            user_id=test_user.id,
            owner="testowner",
            name="testrepo"
        )
        
        retrieved_repo = crud.get_repository_by_name(db_session, test_user.id, "testowner", "testrepo")
        assert retrieved_repo is not None
        assert retrieved_repo.owner == "testowner"
        assert retrieved_repo.name == "testrepo"
        
        # Test with non-existent repository
        missing_repo = crud.get_repository_by_name(db_session, test_user.id, "missing", "repo")
        assert missing_repo is None
    
    def test_get_user_repositories(self, db_session, test_user):
        """Test getting all repositories for a user."""
        # Create multiple repositories
        repo1 = crud.create_repository(db_session, test_user.id, "owner1", "repo1")
        repo2 = crud.create_repository(db_session, test_user.id, "owner2", "repo2")
        
        repositories = crud.get_user_repositories(db_session, test_user.id)
        assert len(repositories) == 2
        
        # Verify both repositories are present (order may vary)
        repo_ids = {repo.id for repo in repositories}
        assert repo1.id in repo_ids
        assert repo2.id in repo_ids
    
    def test_update_repository(self, db_session, test_user):
        """Test updating repository details."""
        repository = crud.create_repository(
            db=db_session,
            user_id=test_user.id,
            owner="testowner",
            name="testrepo",
            default_branch="main",
            github_token="old_token"
        )
        
        # Update repository
        updated_repo = crud.update_repository(
            db=db_session,
            user_id=test_user.id,
            repository_id=repository.id,
            default_branch="develop",
            github_token="new_token"
        )
        
        assert updated_repo is not None
        assert updated_repo.default_branch == "develop"
        
        # Verify new token is encrypted and retrievable
        decrypted_token = crud.get_repository_github_token(db_session, test_user.id, repository.id)
        assert decrypted_token == "new_token"
    
    def test_update_nonexistent_repository(self, db_session, test_user):
        """Test updating non-existent repository returns None."""
        updated_repo = crud.update_repository(
            db=db_session,
            user_id=test_user.id,
            repository_id=999,
            default_branch="develop"
        )
        assert updated_repo is None
    
    def test_delete_repository(self, db_session, test_user):
        """Test deleting repository."""
        repository = crud.create_repository(
            db=db_session,
            user_id=test_user.id,
            owner="testowner",
            name="testrepo"
        )
        
        # Delete repository
        success = crud.delete_repository(db_session, test_user.id, repository.id)
        assert success is True
        
        # Verify repository is deleted
        deleted_repo = crud.get_repository_by_id(db_session, test_user.id, repository.id)
        assert deleted_repo is None
    
    def test_delete_nonexistent_repository(self, db_session, test_user):
        """Test deleting non-existent repository returns False."""
        success = crud.delete_repository(db_session, test_user.id, 999)
        assert success is False
    
    def test_update_repository_sync_time(self, db_session, test_user):
        """Test updating repository sync time."""
        repository = crud.create_repository(
            db=db_session,
            user_id=test_user.id,
            owner="testowner",
            name="testrepo"
        )
        
        original_sync_time = repository.last_synced
        
        # Update sync time
        success = crud.update_repository_sync_time(db_session, repository.id)
        assert success is True
        
        # Verify sync time was updated
        db_session.refresh(repository)
        assert repository.last_synced is not None
        assert repository.last_synced != original_sync_time


class TestRepositoryCache:
    """Test repository metadata caching."""
    
    def test_cache_and_retrieve_metadata(self, clear_repository_cache):
        """Test caching and retrieving repository metadata."""
        metadata = RepositoryMetadata(
            owner="testowner",
            name="testrepo",
            default_branch="main",
            description="Test repository",
            language="Python",
            stars=42,
            forks=7,
            open_issues=3
        )
        
        # Cache metadata
        cache_metadata(metadata)
        
        # Retrieve from cache
        cached = get_cached_metadata("testowner", "testrepo")
        assert cached is not None
        assert cached.owner == "testowner"
        assert cached.name == "testrepo"
        assert cached.stars == 42
    
    def test_cache_case_insensitive(self, clear_repository_cache):
        """Test that cache keys are case-insensitive."""
        metadata = RepositoryMetadata(
            owner="TestOwner",
            name="TestRepo",
            default_branch="main"
        )
        
        cache_metadata(metadata)
        
        # Should retrieve with different case
        cached = get_cached_metadata("testowner", "testrepo")
        assert cached is not None
        assert cached.owner == "TestOwner"  # Original case preserved
        assert cached.name == "TestRepo"
    
    def test_cache_expiration(self, clear_repository_cache):
        """Test that cache entries expire after TTL."""
        from app.services.repository_cache import RepositoryCache
        
        # Create cache with 1-second TTL for testing
        cache = RepositoryCache(ttl_minutes=1/60)  # 1 second
        
        metadata = RepositoryMetadata(
            owner="testowner",
            name="testrepo",
            default_branch="main"
        )
        
        cache.set(metadata)
        
        # Should be available immediately
        cached = cache.get("testowner", "testrepo")
        assert cached is not None
        
        # Wait for expiration (in real test, we'd mock datetime)
        import time
        time.sleep(1.1)
        
        # Should be expired
        cached = cache.get("testowner", "testrepo")
        assert cached is None
    
    def test_cache_invalidation(self, clear_repository_cache):
        """Test cache invalidation."""
        from app.services.repository_cache import invalidate_metadata
        
        metadata = RepositoryMetadata(
            owner="testowner",
            name="testrepo",
            default_branch="main"
        )
        
        cache_metadata(metadata)
        
        # Verify cached
        cached = get_cached_metadata("testowner", "testrepo")
        assert cached is not None
        
        # Invalidate
        success = invalidate_metadata("testowner", "testrepo")
        assert success is True
        
        # Should be gone
        cached = get_cached_metadata("testowner", "testrepo")
        assert cached is None
        
        # Invalidating non-existent entry should return False
        success = invalidate_metadata("missing", "repo")
        assert success is False


class TestRepositoryEncryption:
    """Test repository credential encryption."""
    
    def test_token_encryption_decryption(self, db_session, test_user):
        """Test that GitHub tokens are properly encrypted and decrypted."""
        original_token = "ghp_very_secret_token_123456789"
        
        repository = crud.create_repository(
            db=db_session,
            user_id=test_user.id,
            owner="testowner",
            name="testrepo",
            github_token=original_token
        )
        
        # Token should be encrypted in database
        assert repository.github_token_encrypted != original_token
        assert repository.github_token_encrypted is not None
        
        # Should be able to decrypt
        decrypted = crud.get_repository_github_token(db_session, test_user.id, repository.id)
        assert decrypted == original_token
    
    def test_empty_token_handling(self, db_session, test_user):
        """Test handling of empty/None tokens."""
        repository = crud.create_repository(
            db=db_session,
            user_id=test_user.id,
            owner="testowner",
            name="testrepo",
            github_token=None
        )
        
        assert repository.github_token_encrypted is None
        
        decrypted = crud.get_repository_github_token(db_session, test_user.id, repository.id)
        assert decrypted is None
        
        # Test with empty string
        repository2 = crud.create_repository(
            db=db_session,
            user_id=test_user.id,
            owner="testowner2",
            name="testrepo2",
            github_token=""
        )
        
        assert repository2.github_token_encrypted is None
        
        decrypted2 = crud.get_repository_github_token(db_session, test_user.id, repository2.id)
        assert decrypted2 is None


if __name__ == "__main__":
    pytest.main([__file__])