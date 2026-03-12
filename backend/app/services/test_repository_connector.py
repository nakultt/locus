"""
Unit tests for Repository_Connector functionality.
Tests commit fetching with time windows, PR data retrieval, and rate limit handling.

**Validates: Requirements 2.3, 2.4, 2.6**
"""

import pytest
from unittest.mock import patch, MagicMock, call
from datetime import datetime, timedelta
import time

from backend.app.services.github import (
    fetch_repository_metadata,
    fetch_commits_for_analysis,
    fetch_pull_request_details,
    fetch_commit_details,
    _handle_rate_limit_with_backoff,
    _make_request,
    _github_config
)
from backend.app.services.repository_cache import RepositoryMetadata


class TestRepositoryConnector:
    """Test suite for Repository_Connector functionality."""
    
    def setup_method(self):
        """Set up test configuration before each test."""
        # Clear any existing config
        _github_config.clear()
        _github_config["token"] = "test_token_12345"
    
    def teardown_method(self):
        """Clean up after each test."""
        _github_config.clear()


class TestCommitFetchingWithTimeWindows:
    """Test commit fetching with time windows - Validates Requirement 2.3"""
    
    def setup_method(self):
        """Set up test configuration."""
        _github_config.clear()
        _github_config["token"] = "test_token_12345"
    
    @patch('backend.app.services.github._make_request')
    def test_fetch_commits_within_time_window_success(self, mock_make_request):
        """Test successful commit fetching within specified time window."""
        # Mock commit data within time window
        since_date = datetime(2024, 1, 1, 0, 0, 0)
        until_date = datetime(2024, 1, 31, 23, 59, 59)
        
        mock_commits = [
            {
                "sha": "abc123def456",
                "commit": {
                    "message": "Fix authentication bug",
                    "author": {
                        "name": "John Doe",
                        "email": "john@example.com",
                        "date": "2024-01-15T10:30:00Z"
                    }
                },
                "files": ["auth.py", "models.py"]
            },
            {
                "sha": "def456ghi789", 
                "commit": {
                    "message": "Update user validation",
                    "author": {
                        "name": "Jane Smith",
                        "email": "jane@example.com", 
                        "date": "2024-01-20T14:20:00Z"
                    }
                },
                "files": ["validators.py"]
            }
        ]
        
        mock_make_request.return_value = (mock_commits, None)
        
        result, error = fetch_commits_for_analysis(
            owner="testowner",
            name="testrepo",
            since=since_date,
            until=until_date
        )
        
        assert error is None
        assert result is not None
        assert len(result) == 2
        assert result[0]["sha"] == "abc123def456"
        assert result[1]["sha"] == "def456ghi789"
        
        # Verify API call was made with correct parameters
        mock_make_request.assert_called_once_with(
            "GET", 
            "/repos/testowner/testrepo/commits",
            params={
                "since": since_date.isoformat(),
                "until": until_date.isoformat(),
                "per_page": 100
            }
        )
    
    @patch('backend.app.services.github._make_request')
    def test_fetch_commits_empty_time_window(self, mock_make_request):
        """Test commit fetching when no commits exist in time window."""
        since_date = datetime(2024, 2, 1, 0, 0, 0)
        until_date = datetime(2024, 2, 28, 23, 59, 59)
        
        mock_make_request.return_value = ([], None)
        
        result, error = fetch_commits_for_analysis(
            owner="testowner",
            name="testrepo", 
            since=since_date,
            until=until_date
        )
        
        assert error is None
        assert result == []
    
    @patch('backend.app.services.github._make_request')
    def test_fetch_commits_with_custom_token(self, mock_make_request):
        """Test commit fetching with custom token parameter."""
        since_date = datetime(2024, 1, 1, 0, 0, 0)
        until_date = datetime(2024, 1, 31, 23, 59, 59)
        custom_token = "custom_token_xyz"
        
        mock_commits = [{"sha": "test123", "commit": {"message": "test"}}]
        mock_make_request.return_value = (mock_commits, None)
        
        # Store original token
        original_token = _github_config.get("token")
        
        result, error = fetch_commits_for_analysis(
            owner="testowner",
            name="testrepo",
            since=since_date,
            until=until_date,
            token=custom_token
        )
        
        assert error is None
        assert result == mock_commits
        
        # Verify original token was restored
        assert _github_config.get("token") == original_token
    
    @patch('backend.app.services.github._make_request')
    def test_fetch_commits_api_error(self, mock_make_request):
        """Test commit fetching when GitHub API returns error."""
        since_date = datetime(2024, 1, 1, 0, 0, 0)
        until_date = datetime(2024, 1, 31, 23, 59, 59)
        
        mock_make_request.return_value = (None, "GitHub API Error (404): Repository not found")
        
        result, error = fetch_commits_for_analysis(
            owner="nonexistent",
            name="repo",
            since=since_date,
            until=until_date
        )
        
        assert result is None
        assert error == "GitHub API Error (404): Repository not found"
    
    @patch('backend.app.services.github._make_request')
    def test_fetch_commits_time_window_validation(self, mock_make_request):
        """Test that time window parameters are properly formatted."""
        since_date = datetime(2024, 1, 15, 9, 30, 45)
        until_date = datetime(2024, 1, 20, 18, 45, 30)
        
        mock_make_request.return_value = ([], None)
        
        fetch_commits_for_analysis(
            owner="testowner",
            name="testrepo",
            since=since_date,
            until=until_date
        )
        
        # Verify ISO format timestamps were passed
        expected_params = {
            "since": "2024-01-15T09:30:45",
            "until": "2024-01-20T18:45:30", 
            "per_page": 100
        }
        
        mock_make_request.assert_called_once_with(
            "GET",
            "/repos/testowner/testrepo/commits",
            params=expected_params
        )


class TestPRDataRetrievalAndParsing:
    """Test PR data retrieval and parsing - Validates Requirement 2.4"""
    
    def setup_method(self):
        """Set up test configuration."""
        _github_config.clear()
        _github_config["token"] = "test_token_12345"
    
    @patch('backend.app.services.github._make_request')
    def test_fetch_pull_request_complete_data(self, mock_make_request):
        """Test fetching complete PR data with all fields."""
        mock_pr_data = {
            "number": 123,
            "title": "Fix critical security vulnerability",
            "state": "closed",
            "user": {"login": "security_dev"},
            "head": {"ref": "security-fix"},
            "base": {"ref": "main"},
            "body": "This PR addresses CVE-2024-001 by updating authentication logic.\n\nFixes #456\nCloses #789",
            "merged": True,
            "merged_at": "2024-01-15T15:30:00Z",
            "merged_by": {"login": "maintainer1"},
            "created_at": "2024-01-14T09:00:00Z",
            "updated_at": "2024-01-15T15:30:00Z",
            "html_url": "https://github.com/testowner/testrepo/pull/123",
            "requested_reviewers": [
                {"login": "reviewer1"},
                {"login": "reviewer2"}
            ],
            "assignees": [{"login": "assignee1"}],
            "labels": [
                {"name": "security"},
                {"name": "critical"}
            ]
        }
        
        mock_make_request.return_value = (mock_pr_data, None)
        
        result, error = fetch_pull_request_details(
            owner="testowner",
            name="testrepo",
            pr_number=123
        )
        
        assert error is None
        assert result is not None
        assert result["number"] == 123
        assert result["title"] == "Fix critical security vulnerability"
        assert result["state"] == "closed"
        assert result["merged"] is True
        assert result["user"]["login"] == "security_dev"
        assert len(result["requested_reviewers"]) == 2
        
        # Verify API call
        mock_make_request.assert_called_once_with(
            "GET",
            "/repos/testowner/testrepo/pulls/123"
        )
    
    @patch('backend.app.services.github._make_request')
    def test_fetch_pull_request_minimal_data(self, mock_make_request):
        """Test fetching PR with minimal required data."""
        mock_pr_data = {
            "number": 456,
            "title": "Simple bug fix",
            "state": "open",
            "user": {"login": "developer1"},
            "head": {"ref": "bugfix"},
            "base": {"ref": "develop"},
            "body": None,  # No description
            "merged": False,
            "merged_at": None,
            "merged_by": None,
            "created_at": "2024-01-16T10:00:00Z",
            "updated_at": "2024-01-16T10:00:00Z",
            "html_url": "https://github.com/testowner/testrepo/pull/456",
            "requested_reviewers": [],  # No reviewers
            "assignees": [],
            "labels": []
        }
        
        mock_make_request.return_value = (mock_pr_data, None)
        
        result, error = fetch_pull_request_details(
            owner="testowner",
            name="testrepo",
            pr_number=456
        )
        
        assert error is None
        assert result is not None
        assert result["number"] == 456
        assert result["merged"] is False
        assert result["body"] is None
        assert result["requested_reviewers"] == []
    
    @patch('backend.app.services.github._make_request')
    def test_fetch_pull_request_not_found(self, mock_make_request):
        """Test fetching non-existent PR."""
        mock_make_request.return_value = (None, "GitHub API Error (404): Not Found")
        
        result, error = fetch_pull_request_details(
            owner="testowner",
            name="testrepo",
            pr_number=999
        )
        
        assert result is None
        assert error == "GitHub API Error (404): Not Found"
    
    @patch('backend.app.services.github._make_request')
    def test_fetch_pull_request_with_custom_token(self, mock_make_request):
        """Test PR fetching with custom token parameter."""
        custom_token = "pr_token_abc"
        mock_pr_data = {"number": 789, "title": "Test PR"}
        mock_make_request.return_value = (mock_pr_data, None)
        
        # Store original token
        original_token = _github_config.get("token")
        
        result, error = fetch_pull_request_details(
            owner="testowner",
            name="testrepo",
            pr_number=789,
            token=custom_token
        )
        
        assert error is None
        assert result == mock_pr_data
        
        # Verify original token was restored
        assert _github_config.get("token") == original_token
    
    @patch('backend.app.services.github._make_request')
    def test_fetch_pull_request_linked_issues_parsing(self, mock_make_request):
        """Test parsing of linked issues from PR body."""
        mock_pr_data = {
            "number": 100,
            "title": "Complex feature implementation",
            "body": "This PR implements the new feature.\n\nFixes #123\nCloses #456\nResolves #789\nAlso references #999",
            "state": "open",
            "user": {"login": "feature_dev"},
            "head": {"ref": "feature-branch"},
            "base": {"ref": "main"},
            "merged": False,
            "created_at": "2024-01-17T12:00:00Z",
            "updated_at": "2024-01-17T12:00:00Z",
            "html_url": "https://github.com/testowner/testrepo/pull/100"
        }
        
        mock_make_request.return_value = (mock_pr_data, None)
        
        result, error = fetch_pull_request_details(
            owner="testowner",
            name="testrepo",
            pr_number=100
        )
        
        assert error is None
        assert result is not None
        # The function should return the raw PR data
        # Issue parsing is done in the tool wrapper, not the core function
        assert "fixes #123" in result["body"].lower()
        assert "closes #456" in result["body"].lower()


class TestRateLimitHandlingAndRetryLogic:
    """Test rate limit handling and retry logic - Validates Requirement 2.6"""
    
    def setup_method(self):
        """Set up test configuration."""
        _github_config.clear()
        _github_config["token"] = "test_token_12345"
    
    @patch('backend.app.services.github.time.sleep')
    def test_rate_limit_exponential_backoff_success(self, mock_sleep):
        """Test successful retry with exponential backoff after rate limit."""
        call_count = 0
        
        def mock_function():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return None, "GitHub API Error (403): API rate limit exceeded"
            elif call_count == 2:
                return None, "GitHub API Error (403): rate limit exceeded"
            else:
                return {"success": True}, None
        
        result, error = _handle_rate_limit_with_backoff(mock_function, max_retries=3)
        
        assert error is None
        assert result == {"success": True}
        assert call_count == 3
        
        # Verify exponential backoff sleep times: 2^0=1, 2^1=2
        expected_calls = [call(1), call(2)]
        mock_sleep.assert_has_calls(expected_calls)
    
    @patch('backend.app.services.github.time.sleep')
    def test_rate_limit_max_retries_exceeded(self, mock_sleep):
        """Test failure when max retries exceeded."""
        def always_rate_limited():
            return None, "GitHub API Error (403): API rate limit exceeded"
        
        result, error = _handle_rate_limit_with_backoff(always_rate_limited, max_retries=2)
        
        assert result is None
        assert "Rate limit exceeded after 2 retries" in error
        
        # Should sleep 2^0=1 and 2^1=2 seconds
        expected_calls = [call(1), call(2)]
        mock_sleep.assert_has_calls(expected_calls)
    
    def test_non_rate_limit_error_no_retry(self):
        """Test that non-rate-limit errors are not retried."""
        def non_rate_limit_error():
            return None, "GitHub API Error (404): Repository not found"
        
        result, error = _handle_rate_limit_with_backoff(non_rate_limit_error, max_retries=3)
        
        assert result is None
        assert error == "GitHub API Error (404): Repository not found"
    
    def test_immediate_success_no_retry(self):
        """Test that successful calls don't trigger retry logic."""
        def successful_function():
            return {"data": "success"}, None
        
        result, error = _handle_rate_limit_with_backoff(successful_function, max_retries=3)
        
        assert error is None
        assert result == {"data": "success"}
    
    @patch('backend.app.services.github.time.sleep')
    def test_rate_limit_different_error_formats(self, mock_sleep):
        """Test rate limit detection with different error message formats."""
        call_count = 0
        
        def mock_function():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return None, "rate limit exceeded"  # Lowercase
            elif call_count == 2:
                return None, "403 Forbidden"  # Just status code
            else:
                return {"success": True}, None
        
        result, error = _handle_rate_limit_with_backoff(mock_function, max_retries=3)
        
        assert error is None
        assert result == {"success": True}
        assert call_count == 3
    
    @patch('backend.app.services.github._handle_rate_limit_with_backoff')
    @patch('backend.app.services.github._make_request')
    def test_fetch_commits_with_rate_limiting(self, mock_make_request, mock_rate_limit):
        """Test that commit fetching uses rate limit handling."""
        since_date = datetime(2024, 1, 1, 0, 0, 0)
        until_date = datetime(2024, 1, 31, 23, 59, 59)
        
        mock_commits = [{"sha": "test123"}]
        mock_rate_limit.return_value = (mock_commits, None)
        
        result, error = fetch_commits_for_analysis(
            owner="testowner",
            name="testrepo",
            since=since_date,
            until=until_date
        )
        
        assert error is None
        assert result == mock_commits
        
        # Verify rate limit handler was called
        mock_rate_limit.assert_called_once()
    
    @patch('backend.app.services.github._handle_rate_limit_with_backoff')
    def test_fetch_pull_request_with_rate_limiting(self, mock_rate_limit):
        """Test that PR fetching uses rate limit handling."""
        mock_pr_data = {"number": 123, "title": "Test PR"}
        mock_rate_limit.return_value = (mock_pr_data, None)
        
        result, error = fetch_pull_request_details(
            owner="testowner",
            name="testrepo",
            pr_number=123
        )
        
        assert error is None
        assert result == mock_pr_data
        
        # Verify rate limit handler was called
        mock_rate_limit.assert_called_once()


class TestRepositoryMetadataFetching:
    """Test repository metadata fetching functionality."""
    
    def setup_method(self):
        """Set up test configuration."""
        _github_config.clear()
        _github_config["token"] = "test_token_12345"
    
    @patch('backend.app.services.github.cache_metadata')
    @patch('backend.app.services.github.get_cached_metadata')
    @patch('backend.app.services.github._make_request')
    def test_fetch_repository_metadata_success(self, mock_make_request, mock_get_cache, mock_cache):
        """Test successful repository metadata fetching."""
        # No cached data
        mock_get_cache.return_value = None
        
        # Mock GitHub API response
        mock_repo_data = {
            "owner": {"login": "testowner"},
            "name": "testrepo",
            "default_branch": "main",
            "description": "A test repository",
            "language": "Python",
            "stargazers_count": 42,
            "forks_count": 7,
            "open_issues_count": 3,
            "pushed_at": "2024-01-15T10:30:00Z",
            "created_at": "2023-06-01T12:00:00Z",
            "updated_at": "2024-01-15T10:30:00Z"
        }
        
        mock_make_request.return_value = (mock_repo_data, None)
        
        result, error = fetch_repository_metadata(
            owner="testowner",
            name="testrepo"
        )
        
        assert error is None
        assert result is not None
        assert result.owner == "testowner"
        assert result.name == "testrepo"
        assert result.default_branch == "main"
        assert result.description == "A test repository"
        assert result.language == "Python"
        assert result.stars == 42
        assert result.forks == 7
        assert result.open_issues == 3
        
        # Verify caching was called
        mock_cache.assert_called_once()
        
        # Verify API call
        mock_make_request.assert_called_once_with("GET", "/repos/testowner/testrepo")
    
    @patch('backend.app.services.github.get_cached_metadata')
    def test_fetch_repository_metadata_from_cache(self, mock_get_cache):
        """Test fetching repository metadata from cache."""
        cached_metadata = RepositoryMetadata(
            owner="testowner",
            name="testrepo",
            default_branch="main",
            description="Cached repo",
            stars=100
        )
        
        mock_get_cache.return_value = cached_metadata
        
        result, error = fetch_repository_metadata(
            owner="testowner",
            name="testrepo"
        )
        
        assert error is None
        assert result == cached_metadata
        assert result.description == "Cached repo"
        assert result.stars == 100
    
    @patch('backend.app.services.github.get_cached_metadata')
    @patch('backend.app.services.github._make_request')
    def test_fetch_repository_metadata_api_error(self, mock_make_request, mock_get_cache):
        """Test repository metadata fetching when API returns error."""
        mock_get_cache.return_value = None
        mock_make_request.return_value = (None, "GitHub API Error (404): Repository not found")
        
        result, error = fetch_repository_metadata(
            owner="nonexistent",
            name="repo"
        )
        
        assert result is None
        assert error == "GitHub API Error (404): Repository not found"


class TestCommitDetailsFetching:
    """Test commit details fetching functionality."""
    
    def setup_method(self):
        """Set up test configuration."""
        _github_config.clear()
        _github_config["token"] = "test_token_12345"
    
    @patch('backend.app.services.github._handle_rate_limit_with_backoff')
    def test_fetch_commit_details_success(self, mock_rate_limit):
        """Test successful commit details fetching."""
        mock_commit_data = {
            "sha": "abc123def456789",
            "commit": {
                "message": "Fix critical bug in authentication",
                "author": {
                    "name": "John Developer",
                    "email": "john@example.com",
                    "date": "2024-01-15T14:20:00Z"
                },
                "committer": {
                    "name": "John Developer",
                    "email": "john@example.com",
                    "date": "2024-01-15T14:20:00Z"
                }
            },
            "stats": {
                "additions": 25,
                "deletions": 8,
                "total": 33
            },
            "files": [
                {
                    "filename": "auth/models.py",
                    "status": "modified",
                    "additions": 15,
                    "deletions": 5
                },
                {
                    "filename": "tests/test_auth.py",
                    "status": "added",
                    "additions": 10,
                    "deletions": 0
                }
            ],
            "html_url": "https://github.com/testowner/testrepo/commit/abc123def456789"
        }
        
        mock_rate_limit.return_value = (mock_commit_data, None)
        
        result, error = fetch_commit_details(
            owner="testowner",
            name="testrepo",
            sha="abc123def456789"
        )
        
        assert error is None
        assert result is not None
        assert result["sha"] == "abc123def456789"
        assert result["commit"]["message"] == "Fix critical bug in authentication"
        assert result["stats"]["total"] == 33
        assert len(result["files"]) == 2
        
        # Verify rate limit handler was called
        mock_rate_limit.assert_called_once()
    
    @patch('backend.app.services.github._handle_rate_limit_with_backoff')
    def test_fetch_commit_details_not_found(self, mock_rate_limit):
        """Test fetching details for non-existent commit."""
        mock_rate_limit.return_value = (None, "GitHub API Error (404): Not Found")
        
        result, error = fetch_commit_details(
            owner="testowner",
            name="testrepo",
            sha="nonexistent123"
        )
        
        assert result is None
        assert error == "GitHub API Error (404): Not Found"


class TestIntegrationScenarios:
    """Test integration scenarios combining multiple Repository_Connector functions."""
    
    def setup_method(self):
        """Set up test configuration."""
        _github_config.clear()
        _github_config["token"] = "test_token_12345"
    
    @patch('backend.app.services.github._handle_rate_limit_with_backoff')
    @patch('backend.app.services.github._make_request')
    def test_incident_analysis_workflow(self, mock_make_request, mock_rate_limit):
        """Test complete incident analysis workflow using Repository_Connector."""
        # Step 1: Fetch repository metadata
        mock_repo_data = {
            "owner": {"login": "testowner"},
            "name": "testrepo",
            "default_branch": "main",
            "description": "Production service repository"
        }
        
        # Step 2: Fetch commits in time window
        mock_commits = [
            {
                "sha": "commit123",
                "commit": {
                    "message": "Fix database connection issue",
                    "author": {"name": "Dev1", "date": "2024-01-15T10:00:00Z"}
                }
            }
        ]
        
        # Step 3: Fetch PR details
        mock_pr_data = {
            "number": 456,
            "title": "Database connection fix",
            "merged": True,
            "merged_at": "2024-01-15T11:00:00Z"
        }
        
        # Configure mocks
        mock_make_request.return_value = (mock_repo_data, None)
        mock_rate_limit.side_effect = [
            (mock_commits, None),  # For commit fetching
            (mock_pr_data, None)   # For PR fetching
        ]
        
        # Execute workflow
        # 1. Get repository metadata
        repo_metadata, repo_error = fetch_repository_metadata("testowner", "testrepo")
        assert repo_error is None
        assert repo_metadata.name == "testrepo"
        
        # 2. Fetch commits
        since_date = datetime(2024, 1, 1, 0, 0, 0)
        until_date = datetime(2024, 1, 31, 23, 59, 59)
        commits, commits_error = fetch_commits_for_analysis(
            "testowner", "testrepo", since_date, until_date
        )
        assert commits_error is None
        assert len(commits) == 1
        assert commits[0]["sha"] == "commit123"
        
        # 3. Fetch PR details
        pr_details, pr_error = fetch_pull_request_details("testowner", "testrepo", 456)
        assert pr_error is None
        assert pr_details["number"] == 456
        assert pr_details["merged"] is True
    
    def test_error_handling_consistency(self):
        """Test that all Repository_Connector functions handle errors consistently."""
        # Test with no token configured
        _github_config.clear()
        
        since_date = datetime(2024, 1, 1, 0, 0, 0)
        until_date = datetime(2024, 1, 31, 23, 59, 59)
        
        # All functions should return (None, error_message) format
        commits_result, commits_error = fetch_commits_for_analysis(
            "test", "test", since_date, until_date
        )
        assert commits_result is None
        assert "GitHub is not configured" in commits_error or "Bad credentials" in commits_error
        
        pr_result, pr_error = fetch_pull_request_details("test", "test", 123)
        assert pr_result is None
        assert "GitHub is not configured" in pr_error or "Bad credentials" in pr_error
        
        commit_result, commit_error = fetch_commit_details("test", "test", "abc123")
        assert commit_result is None
        assert "GitHub is not configured" in commit_error or "Bad credentials" in commit_error


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
