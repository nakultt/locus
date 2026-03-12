"""
Unit tests for incident analysis router
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import uuid

from app.database import Base, get_db
from app.models import User, Repository, IncidentAnalysis
from main import app

# Test database setup
SQLALCHEMY_DATABASE_URL = "sqlite:///./test_incidents.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    """Override database dependency for testing."""
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(scope="function")
def test_db():
    """Create test database tables."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def test_user(test_db):
    """Create a test user."""
    db = TestingSessionLocal()
    user = User(
        email="test@example.com",
        name="Test User",
        hashed_password="hashed_password"
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    yield user
    db.close()


def test_create_repository(client, test_user):
    """Test creating a repository."""
    response = client.post(
        "/api/incidents/repositories",
        json={
            "owner": "testorg",
            "name": "testrepo",
            "default_branch": "main"
        },
        params={"user_id": test_user.id}
    )
    
    assert response.status_code == 201
    data = response.json()
    assert data["owner"] == "testorg"
    assert data["name"] == "testrepo"
    assert data["default_branch"] == "main"
    assert "id" in data
    assert "created_at" in data


def test_list_repositories(client, test_user):
    """Test listing repositories."""
    # Create a repository first
    db = TestingSessionLocal()
    repo = Repository(
        user_id=test_user.id,
        owner="testorg",
        name="testrepo",
        default_branch="main"
    )
    db.add(repo)
    db.commit()
    db.close()
    
    # List repositories
    response = client.get(
        "/api/incidents/repositories",
        params={"user_id": test_user.id}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["owner"] == "testorg"
    assert data[0]["name"] == "testrepo"


def test_get_repository(client, test_user):
    """Test getting a specific repository."""
    # Create a repository first
    db = TestingSessionLocal()
    repo = Repository(
        user_id=test_user.id,
        owner="testorg",
        name="testrepo",
        default_branch="main"
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)
    repo_id = repo.id
    db.close()
    
    # Get repository
    response = client.get(
        f"/api/incidents/repositories/{repo_id}",
        params={"user_id": test_user.id}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == repo_id
    assert data["owner"] == "testorg"


def test_delete_repository(client, test_user):
    """Test deleting a repository."""
    # Create a repository first
    db = TestingSessionLocal()
    repo = Repository(
        user_id=test_user.id,
        owner="testorg",
        name="testrepo",
        default_branch="main"
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)
    repo_id = repo.id
    db.close()
    
    # Delete repository
    response = client.delete(
        f"/api/incidents/repositories/{repo_id}",
        params={"user_id": test_user.id}
    )
    
    assert response.status_code == 204
    
    # Verify it's deleted
    response = client.get(
        f"/api/incidents/repositories/{repo_id}",
        params={"user_id": test_user.id}
    )
    assert response.status_code == 404


def test_create_incident_analysis(client, test_user):
    """Test creating an incident analysis."""
    # Create a repository first
    db = TestingSessionLocal()
    repo = Repository(
        user_id=test_user.id,
        owner="testorg",
        name="testrepo",
        default_branch="main"
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)
    repo_id = repo.id
    db.close()
    
    # Create analysis
    response = client.post(
        "/api/incidents/analyze",
        json={
            "log_content": "Error: NullPointerException at line 42",
            "log_format": "plain",
            "repository_ids": [repo_id]
        },
        params={"user_id": test_user.id}
    )
    
    assert response.status_code == 201
    data = response.json()
    assert data["log_content"] == "Error: NullPointerException at line 42"
    assert data["log_format"] == "plain"
    assert data["status"] == "pending"
    assert "analysis_uuid" in data
    assert len(data["repositories"]) == 1


def test_get_incident_analysis(client, test_user):
    """Test getting an incident analysis."""
    # Create analysis first
    db = TestingSessionLocal()
    analysis = IncidentAnalysis(
        user_id=test_user.id,
        analysis_uuid=str(uuid.uuid4()),
        log_content="Error: Test error",
        log_format="plain",
        status="pending"
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    analysis_id = analysis.id
    db.close()
    
    # Get analysis
    response = client.get(
        f"/api/incidents/{analysis_id}",
        params={"user_id": test_user.id}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == analysis_id
    assert data["log_content"] == "Error: Test error"


def test_get_incident_history(client, test_user):
    """Test getting incident analysis history."""
    # Create multiple analyses
    db = TestingSessionLocal()
    for i in range(3):
        analysis = IncidentAnalysis(
            user_id=test_user.id,
            analysis_uuid=str(uuid.uuid4()),
            log_content=f"Error {i}",
            log_format="plain",
            status="completed"
        )
        db.add(analysis)
    db.commit()
    db.close()
    
    # Get history
    response = client.get(
        "/api/incidents/history",
        params={"user_id": test_user.id, "limit": 10, "offset": 0}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3
    assert len(data["analyses"]) == 3
