"""
Unit tests for Diff Engine Service
"""

import pytest
from unittest.mock import Mock, patch
from hypothesis import given, strategies as st, assume, settings
from hypothesis import HealthCheck
from app.services.diff_engine import (
    DiffEngine,
    FileDiff,
    CommitDiff,
    FileStatus,
    FileRename,
    get_diff_engine
)


class TestDiffEngine:
    """Test suite for DiffEngine class."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.token = "test_token_123"
        self.engine = DiffEngine(self.token)
    
    def test_init(self):
        """Test DiffEngine initialization."""
        assert self.engine.token == self.token
    
    def test_get_headers(self):
        """Test header generation."""
        headers = self.engine._get_headers()
        assert headers["Authorization"] == f"token {self.token}"
        assert headers["Accept"] == "application/vnd.github.v3+json"
    
    def test_detect_language_python(self):
        """Test language detection for Python files."""
        assert self.engine._detect_language("test.py") == "python"
    
    def test_detect_language_javascript(self):
        """Test language detection for JavaScript files."""
        assert self.engine._detect_language("app.js") == "javascript"
        assert self.engine._detect_language("component.jsx") == "javascript"
    
    def test_detect_language_typescript(self):
        """Test language detection for TypeScript files."""
        assert self.engine._detect_language("app.ts") == "typescript"
        assert self.engine._detect_language("component.tsx") == "typescript"
    
    def test_detect_language_unknown(self):
        """Test language detection for unknown file types."""
        assert self.engine._detect_language("unknown.xyz") == "plaintext"
    
    def test_get_change_type_indicator_added(self):
        """Test change type indicator for added files."""
        assert self.engine._get_change_type_indicator(FileStatus.ADDED) == "+"
    
    def test_get_change_type_indicator_modified(self):
        """Test change type indicator for modified files."""
        assert self.engine._get_change_type_indicator(FileStatus.MODIFIED) == "~"
    
    def test_get_change_type_indicator_deleted(self):
        """Test change type indicator for deleted files."""
        assert self.engine._get_change_type_indicator(FileStatus.DELETED) == "-"
    
    def test_get_change_type_indicator_renamed(self):
        """Test change type indicator for renamed files."""
        assert self.engine._get_change_type_indicator(FileStatus.RENAMED) == "R"
    
    def test_format_patch_with_line_numbers_empty(self):
        """Test patch formatting with empty patch."""
        result = self.engine._format_patch_with_line_numbers("")
        assert result == ""
    
    def test_format_patch_with_line_numbers_basic(self):
        """Test patch formatting with basic patch."""
        patch = "@@ -1,3 +1,4 @@\n line1\n-line2\n+line2 modified\n+line3"
        result = self.engine._format_patch_with_line_numbers(patch)
        assert "@@ -1,3 +1,4 @@" in result
        assert "-line2" in result
        assert "+line2 modified" in result
    
    def test_get_commit_diff_invalid_repo_format(self):
        """Test get_commit_diff with invalid repository format."""
        result, error = self.engine.get_commit_diff("invalid", "abc123")
        assert result is None
        assert "Invalid repository format" in error
    
    def test_get_commit_diff_missing_commit_sha(self):
        """Test get_commit_diff with missing commit SHA."""
        result, error = self.engine.get_commit_diff("owner/repo", "")
        assert result is None
        assert "Commit SHA is required" in error
    
    @patch('app.services.diff_engine.requests.request')
    def test_get_commit_diff_success(self, mock_request):
        """Test successful commit diff retrieval."""
        # Mock GitHub API response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "sha": "abc123",
            "files": [
                {
                    "filename": "test.py",
                    "status": "modified",
                    "additions": 5,
                    "deletions": 2,
                    "patch": "@@ -1,3 +1,4 @@\n line1\n-line2\n+line2 modified"
                }
            ]
        }
        mock_request.return_value = mock_response
        
        result, error = self.engine.get_commit_diff("owner/repo", "abc123")
        
        assert error is None
        assert result is not None
        assert result.commit_sha == "abc123"
        assert len(result.files_changed) == 1
        assert result.files_changed[0].file_path == "test.py"
        assert result.files_changed[0].language == "python"
        assert result.files_changed[0].change_type_indicator == "~"
        assert result.additions == 5
        assert result.deletions == 2
    
    @patch('app.services.diff_engine.requests.request')
    def test_get_commit_diff_api_error(self, mock_request):
        """Test commit diff retrieval with API error."""
        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.text = "Not Found"
        mock_response.json.return_value = {"message": "Not Found"}
        mock_request.return_value = mock_response
        
        result, error = self.engine.get_commit_diff("owner/repo", "abc123")
        
        assert result is None
        assert "GitHub API Error (404)" in error
    
    def test_compare_commits_invalid_repo(self):
        """Test compare_commits with invalid repository format."""
        result, error = self.engine.compare_commits("invalid", "base", "head")
        assert result is None
        assert "Invalid repository format" in error
    
    def test_compare_commits_missing_base(self):
        """Test compare_commits with missing base commit."""
        result, error = self.engine.compare_commits("owner/repo", "", "head")
        assert result is None
        assert "Both base and head commits are required" in error
    
    @patch('app.services.diff_engine.requests.request')
    def test_compare_commits_success(self, mock_request):
        """Test successful commit comparison."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "commits": [{"sha": "def456"}],
            "files": [
                {
                    "filename": "app.js",
                    "status": "added",
                    "additions": 10,
                    "deletions": 0,
                    "patch": "@@ -0,0 +1,10 @@\n+new code"
                }
            ]
        }
        mock_request.return_value = mock_response
        
        result, error = self.engine.compare_commits("owner/repo", "base", "head")
        
        assert error is None
        assert result is not None
        assert result.commit_sha == "def456"
        assert len(result.files_changed) == 1
        assert result.files_changed[0].status == FileStatus.ADDED
        assert result.files_changed[0].change_type_indicator == "+"
    
    def test_format_unified_diff(self):
        """Test unified diff formatting."""
        file_diff = FileDiff(
            file_path="test.py",
            old_path=None,
            status=FileStatus.MODIFIED,
            additions=5,
            deletions=2,
            patch="@@ -1,3 +1,4 @@\n line1\n-line2\n+line2 modified",
            language="python",
            change_type_indicator="~"
        )
        
        commit_diff = CommitDiff(
            commit_sha="abc123",
            files_changed=[file_diff],
            additions=5,
            deletions=2,
            total_changes=7
        )
        
        result = self.engine.format_unified_diff(commit_diff)
        
        assert "commit abc123" in result
        assert "1 files changed, 5 insertions(+), 2 deletions(-)" in result
        assert "diff --git a/test.py b/test.py" in result
        assert "@@ -1,3 +1,4 @@" in result
    
    def test_format_unified_diff_renamed_file(self):
        """Test unified diff formatting for renamed files."""
        file_diff = FileDiff(
            file_path="new_name.py",
            old_path="old_name.py",
            status=FileStatus.RENAMED,
            additions=0,
            deletions=0,
            patch="",
            language="python",
            change_type_indicator="R"
        )
        
        commit_diff = CommitDiff(
            commit_sha="abc123",
            files_changed=[file_diff],
            additions=0,
            deletions=0,
            total_changes=0
        )
        
        result = self.engine.format_unified_diff(commit_diff)
        
        assert "rename from old_name.py" in result
        assert "rename to new_name.py" in result
    
    def test_detect_file_renames(self):
        """Test file rename detection."""
        file_diff_renamed = FileDiff(
            file_path="new_name.py",
            old_path="old_name.py",
            status=FileStatus.RENAMED,
            additions=0,
            deletions=0,
            patch="",
            language="python",
            change_type_indicator="R"
        )
        
        file_diff_modified = FileDiff(
            file_path="other.py",
            old_path=None,
            status=FileStatus.MODIFIED,
            additions=5,
            deletions=2,
            patch="",
            language="python",
            change_type_indicator="~"
        )
        
        commit_diff = CommitDiff(
            commit_sha="abc123",
            files_changed=[file_diff_renamed, file_diff_modified],
            additions=5,
            deletions=2,
            total_changes=7
        )
        
        renames = self.engine.detect_file_renames(commit_diff)
        
        assert len(renames) == 1
        assert renames[0].old_path == "old_name.py"
        assert renames[0].new_path == "new_name.py"
        assert renames[0].commit_sha == "abc123"
    
    def test_detect_file_renames_no_renames(self):
        """Test file rename detection with no renames."""
        file_diff = FileDiff(
            file_path="test.py",
            old_path=None,
            status=FileStatus.MODIFIED,
            additions=5,
            deletions=2,
            patch="",
            language="python",
            change_type_indicator="~"
        )
        
        commit_diff = CommitDiff(
            commit_sha="abc123",
            files_changed=[file_diff],
            additions=5,
            deletions=2,
            total_changes=7
        )
        
        renames = self.engine.detect_file_renames(commit_diff)
        
        assert len(renames) == 0


def test_get_diff_engine_factory():
    """Test factory function."""
    token = "test_token"
    engine = get_diff_engine(token)
    
    assert isinstance(engine, DiffEngine)
    assert engine.token == token


class TestDiffEngineProperties:
    """Property-based tests for DiffEngine class."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.token = "test_token_123"
        self.engine = DiffEngine(self.token)
    
    @given(
        repo=st.text(min_size=0, max_size=100),
        commit_sha=st.text(min_size=0, max_size=100)
    )
    @settings(deadline=1000)  # Increase deadline to 1 second
    def test_property_1_diff_engine_input_acceptance(self, repo, commit_sha):
        """
        **Validates: Requirements 1.1**
        
        Property 1: Diff Engine Input Acceptance
        For any two commit identifiers (valid or invalid format), 
        the Diff_Engine should accept them as input without throwing 
        an exception during the input validation phase.
        """
        # The method should not throw an exception during input validation
        # It may return an error, but should not crash
        try:
            result, error = self.engine.get_commit_diff(repo, commit_sha)
            # Either we get a result or an error, but no exception should be thrown
            assert (result is None and error is not None) or (result is not None and error is None)
        except Exception as e:
            # Only network/unexpected errors are allowed, not input validation errors
            assert "Request failed" in str(e) or "Unexpected error" in str(e)
    
    @given(
        repo=st.sampled_from(["owner/repo", "test/project", "user/service", "org/app"]),
        commit_sha=st.text(min_size=7, max_size=40, alphabet="abcdef0123456789")
    )
    @patch('app.services.diff_engine.requests.request')
    @settings(suppress_health_check=[HealthCheck.filter_too_much])
    def test_property_2_diff_retrieval_completeness(self, mock_request, repo, commit_sha):
        """
        **Validates: Requirements 1.2**
        
        Property 2: Diff Retrieval Completeness
        For any pair of valid commit identifiers in a repository, 
        the Diff_Engine should return diff data that includes all 
        files changed between those commits.
        """
        # Mock a successful GitHub API response with multiple files
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "sha": commit_sha,
            "files": [
                {
                    "filename": "file1.py",
                    "status": "modified",
                    "additions": 5,
                    "deletions": 2,
                    "patch": "@@ -1,3 +1,4 @@\n line1\n-line2\n+line2 modified"
                },
                {
                    "filename": "file2.js",
                    "status": "added",
                    "additions": 10,
                    "deletions": 0,
                    "patch": "@@ -0,0 +1,10 @@\n+new code"
                },
                {
                    "filename": "file3.txt",
                    "status": "deleted",
                    "additions": 0,
                    "deletions": 8,
                    "patch": "@@ -1,8 +0,0 @@\n-deleted content"
                }
            ]
        }
        mock_request.return_value = mock_response
        
        result, error = self.engine.get_commit_diff(repo, commit_sha)
        
        # Should successfully retrieve diff data
        assert error is None
        assert result is not None
        
        # Should include all files from the API response
        assert len(result.files_changed) == 3
        
        # Should preserve file information for all files
        file_paths = [f.file_path for f in result.files_changed]
        assert "file1.py" in file_paths
        assert "file2.js" in file_paths
        assert "file3.txt" in file_paths
        
        # Should calculate totals correctly
        assert result.additions == 15  # 5 + 10 + 0
        assert result.deletions == 10  # 2 + 0 + 8
        assert result.total_changes == 25  # 15 + 10
    
    @given(
        repo=st.sampled_from(["owner/repo", "test/project", "user/service", "org/app"]),
        commit_sha=st.text(min_size=7, max_size=40, alphabet="abcdef0123456789")
    )
    @patch('app.services.diff_engine.requests.request')
    @settings(suppress_health_check=[HealthCheck.filter_too_much])
    def test_property_3_unified_diff_format_compliance(self, mock_request, repo, commit_sha):
        """
        **Validates: Requirements 1.3**
        
        Property 3: Unified Diff Format Compliance
        For any diff output from the Diff_Engine, the output should 
        conform to unified diff format with line numbers for each change hunk.
        """
        # Mock a successful GitHub API response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "sha": commit_sha,
            "files": [
                {
                    "filename": "test.py",
                    "status": "modified",
                    "additions": 3,
                    "deletions": 2,
                    "patch": "@@ -1,5 +1,6 @@\n line1\n-old line\n+new line\n+added line\n line3"
                }
            ]
        }
        mock_request.return_value = mock_response
        
        result, error = self.engine.get_commit_diff(repo, commit_sha)
        
        assert error is None
        assert result is not None
        
        # Format as unified diff
        unified_diff = self.engine.format_unified_diff(result)
        
        # Should contain unified diff format elements
        assert f"commit {commit_sha}" in unified_diff
        assert "files changed" in unified_diff
        assert "insertions(+)" in unified_diff
        assert "deletions(-)" in unified_diff
        assert "diff --git" in unified_diff
        assert "--- a/" in unified_diff or "--- /dev/null" in unified_diff
        assert "+++ b/" in unified_diff or "+++ /dev/null" in unified_diff
        
        # Should contain line number information (hunk headers)
        assert "@@" in unified_diff  # Hunk headers contain line numbers
        
        # Should preserve patch content with line numbers
        file_diff = result.files_changed[0]
        assert "@@ -1,5 +1,6 @@" in file_diff.patch
    
    @given(
        repo=st.one_of(
            st.just("invalid"),  # Invalid format
            st.just(""),  # Empty repo
            st.sampled_from(["owner/repo", "test/project"])  # Valid format
        ),
        commit_sha=st.one_of(
            st.just(""),  # Empty commit SHA
            st.text(min_size=7, max_size=40, alphabet="abcdef0123456789")  # Valid SHA
        )
    )
    def test_property_7_diff_error_handling(self, repo, commit_sha):
        """
        **Validates: Requirements 1.7**
        
        Property 7: Diff Error Handling
        For any invalid commit identifier or inaccessible commit, 
        the Diff_Engine should return an error response containing 
        a descriptive message rather than throwing an unhandled exception.
        """
        # Test with various invalid inputs
        with patch('app.services.diff_engine.requests.request') as mock_request:
            # Mock different types of API errors
            if repo and "/" in repo and commit_sha:
                # Valid format but API error
                mock_response = Mock()
                mock_response.status_code = 404
                mock_response.text = "Not Found"
                mock_response.json.return_value = {"message": "Not Found"}
                mock_request.return_value = mock_response
            
            try:
                result, error = self.engine.get_commit_diff(repo, commit_sha)
                
                # Should not throw unhandled exceptions
                assert True  # If we reach here, no exception was thrown
                
                # For invalid inputs, should return error with descriptive message
                if not repo or "/" not in repo:
                    assert result is None
                    assert error is not None
                    assert "Invalid repository format" in error
                elif not commit_sha:
                    assert result is None
                    assert error is not None
                    assert "Commit SHA is required" in error
                elif repo and "/" in repo and commit_sha:
                    # Valid format but API error
                    assert result is None
                    assert error is not None
                    assert "GitHub API Error" in error or "Not Found" in error
                
            except Exception as e:
                # Only network/unexpected errors are allowed, not validation errors
                error_msg = str(e)
                assert any(allowed in error_msg for allowed in [
                    "Request failed", 
                    "Unexpected error",
                    "Connection",
                    "Timeout"
                ]), f"Unexpected exception type: {error_msg}"
