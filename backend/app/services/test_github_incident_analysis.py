"""
Unit tests for GitHub incident analysis functionality.
Tests the new methods added for incident-to-code traceability.
"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime
import json

from backend.app.services.github import (
    _handle_rate_limit_with_backoff,
    _make_request,
    _github_config
)

# Import the actual functions, not the tool wrappers
import backend.app.services.github as github_module


class TestGitHubIncidentAnalysis:
    """Test suite for GitHub incident analysis methods."""
    
    def setup_method(self):
        """Set up test configuration."""
        # Patch the global config directly in the module
        github_module._github_config = {"token": "test_token"}
    
    @patch('backend.app.services.github.requests.request')
    def test_fetch_commits_success(self, mock_request):
        """Test successful commit fetching."""
        # Mock response data
        mock_commits = [
            {
                "sha": "abc123def456",
                "commit": {
                    "message": "Fix authentication bug",
                    "author": {
                        "name": "John Doe",
                        "date": "2024-01-15T10:30:00Z"
                    }
                },
                "files": [{"filename": "auth.py"}]
            }
        ]
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_commits
        mock_request.return_value = mock_response
        
        result = github_module.github_fetch_commits.func(
            owner="testowner",
            repo="testrepo", 
            since="2024-01-01T00:00:00Z",
            until="2024-01-31T23:59:59Z"
        )
        
        assert "Found 1 commits" in result
        assert "abc123de" in result  # First 8 chars of SHA
        assert "Fix authentication bug" in result
        assert "John Doe" in result
    
    @patch('backend.app.services.github.requests.request')
    def test_fetch_pull_request_success(self, mock_request):
        """Test successful PR fetching."""
        mock_pr = {
            "number": 123,
            "title": "Fix critical security issue",
            "state": "closed",
            "user": {"login": "developer1"},
            "head": {"ref": "fix-security"},
            "base": {"ref": "main"},
            "body": "This PR fixes #456 and closes #789",
            "merged": True,
            "merged_at": "2024-01-15T15:30:00Z",
            "merged_by": {"login": "maintainer1"},
            "created_at": "2024-01-14T09:00:00Z",
            "updated_at": "2024-01-15T15:30:00Z",
            "html_url": "https://github.com/testowner/testrepo/pull/123",
            "requested_reviewers": [{"login": "reviewer1"}]
        }
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_pr
        mock_request.return_value = mock_response
        
        result = github_module.github_fetch_pull_request.func(
            owner="testowner",
            repo="testrepo",
            pr_number=123
        )
        
        assert "Pull Request **#123**" in result
        assert "Fix critical security issue" in result
        assert "developer1" in result
        assert "fix-security → main" in result
        assert "Merged at:" in result
        assert "#456, #789" in result  # Linked issues
    @patch('backend.app.services.github.requests.request')
    def test_get_commit_metadata_success(self, mock_request):
        """Test successful commit metadata retrieval."""
        mock_commit = {
            "sha": "abc123def456789",
            "commit": {
                "message": "Refactor user authentication\n\nThis commit improves security",
                "author": {
                    "name": "Jane Smith",
                    "email": "jane@example.com",
                    "date": "2024-01-15T14:20:00Z"
                },
                "committer": {
                    "name": "Jane Smith", 
                    "email": "jane@example.com",
                    "date": "2024-01-15T14:20:00Z"
                }
            },
            "stats": {
                "additions": 45,
                "deletions": 12,
                "total": 57
            },
            "files": [
                {"filename": "auth/models.py", "status": "modified"},
                {"filename": "auth/views.py", "status": "modified"},
                {"filename": "tests/test_auth.py", "status": "added"}
            ],
            "html_url": "https://github.com/testowner/testrepo/commit/abc123def456789"
        }
        
        # Mock PR search response (empty list)
        mock_prs = []
        
        def mock_request_side_effect(*args, **kwargs):
            mock_response = MagicMock()
            mock_response.status_code = 200
            
            # Return commit data for commit endpoint, empty PR list for PR endpoint
            if "/commits/" in kwargs.get('url', ''):
                mock_response.json.return_value = mock_commit
            else:
                mock_response.json.return_value = mock_prs
            
            return mock_response
        
        mock_request.side_effect = mock_request_side_effect
        
        result = github_module.github_get_commit_metadata.func(
            owner="testowner",
            repo="testrepo",
            sha="abc123def456789"
        )
        
        assert "Commit **abc123de**" in result
        assert "Refactor user authentication" in result
        assert "Jane Smith" in result
        assert "jane@example.com" in result
        assert "Additions: 45" in result
        assert "Deletions: 12" in result
        assert "Total Changes: 57" in result
        assert "auth/models.py" in result
        assert "Files Changed (3)" in result

    @patch('backend.app.services.github.time.sleep')
    @patch('backend.app.services.github.requests.request')
    def test_rate_limit_handling(self, mock_request, mock_sleep):
        """Test rate limit handling with exponential backoff."""
        # First call returns rate limit error
        rate_limit_response = MagicMock()
        rate_limit_response.status_code = 403
        rate_limit_response.json.return_value = {"message": "API rate limit exceeded"}
        
        # Second call succeeds
        success_response = MagicMock()
        success_response.status_code = 200
        success_response.json.return_value = [{"sha": "test123"}]
        
        mock_request.side_effect = [rate_limit_response, success_response]
        
        def mock_make_request(method, endpoint, **kwargs):
            response = mock_request(method=method, url=f"https://api.github.com{endpoint}", **kwargs)
            if response.status_code >= 400:
                error_msg = response.json().get("message", response.text)
                return None, f"GitHub API Error ({response.status_code}): {error_msg}"
            return response.json(), None
        
        result, error = _handle_rate_limit_with_backoff(mock_make_request, "GET", "/test")
        
        assert error is None
        assert result == [{"sha": "test123"}]
        mock_sleep.assert_called_once_with(1)  # First retry waits 2^0 = 1 second

    def test_rate_limit_max_retries_exceeded(self):
        """Test that rate limiting gives up after max retries."""
        def failing_function():
            return None, "GitHub API Error (403): API rate limit exceeded"
        
        result, error = _handle_rate_limit_with_backoff(failing_function, max_retries=2)
        
        assert result is None
        assert "Rate limit exceeded after 2 retries" in error

    @patch('backend.app.services.github.requests.request')
    def test_fetch_commits_no_results(self, mock_request):
        """Test fetch commits when no commits are found."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = []
        mock_request.return_value = mock_response
        
        result = github_module.github_fetch_commits.func(
            owner="testowner",
            repo="testrepo",
            since="2024-01-01T00:00:00Z", 
            until="2024-01-31T23:59:59Z"
        )
        
        assert "No commits found" in result

    @patch('backend.app.services.github.requests.request')
    def test_fetch_pull_request_not_found(self, mock_request):
        """Test fetch PR when PR doesn't exist."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.json.return_value = {"message": "Not Found"}
        mock_request.return_value = mock_response
        
        result = github_module.github_fetch_pull_request.func(
            owner="testowner",
            repo="testrepo",
            pr_number=999
        )
        
        assert "❌" in result
        assert "GitHub API Error (404)" in result

    def test_no_github_token_configured(self):
        """Test behavior when GitHub token is not configured."""
        # Temporarily clear the config
        original_config = github_module._github_config.copy()
        github_module._github_config = {}
        
        try:
            result = github_module.github_fetch_commits.func(
                owner="testowner",
                repo="testrepo",
                since="2024-01-01T00:00:00Z",
                until="2024-01-31T23:59:59Z"
            )
            
            assert "❌" in result
            assert "GitHub is not configured" in result
        finally:
            # Restore the config
            github_module._github_config = original_config