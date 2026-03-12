"""
Diff Engine Service
Retrieves and formats code differences between commits using GitHub API
"""

import requests
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from enum import Enum


# Store credentials at module level for service access
_github_config: dict = {}
GITHUB_API_BASE = "https://api.github.com"


class FileStatus(str, Enum):
    """File change status types."""
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"


@dataclass
class FileDiff:
    """Represents a single file's diff."""
    file_path: str
    old_path: Optional[str]  # For renames
    status: FileStatus
    additions: int
    deletions: int
    patch: str  # Unified diff format
    language: str  # For syntax highlighting
    change_type_indicator: str  # Visual indicator: +, -, ~, R


@dataclass
class CommitDiff:
    """Represents a complete commit diff."""
    commit_sha: str
    files_changed: List[FileDiff]
    additions: int
    deletions: int
    total_changes: int


@dataclass
class FileRename:
    """Represents a file rename operation."""
    old_path: str
    new_path: str
    commit_sha: str


class DiffEngine:
    """Service for retrieving and formatting code diffs from GitHub."""
    
    def __init__(self, token: str):
        """
        Initialize the Diff Engine with GitHub authentication.
        
        Args:
            token: GitHub Personal Access Token
        """
        global _github_config
        _github_config = {"token": token}
        self.token = token
    
    def _get_headers(self) -> Dict[str, str]:
        """Get GitHub API headers with authentication."""
        return {
            "Authorization": f"token {self.token}",
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28"
        }
    
    def _make_request(
        self, 
        method: str, 
        endpoint: str, 
        params: Optional[Dict[str, Any]] = None
    ) -> tuple[Optional[Dict], Optional[str]]:
        """
        Make a request to the GitHub API.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint path
            params: Optional query parameters
            
        Returns:
            Tuple of (response_data, error_message)
        """
        url = f"{GITHUB_API_BASE}{endpoint}"
        
        try:
            response = requests.request(
                method=method,
                url=url,
                headers=self._get_headers(),
                params=params
            )
            
            if response.status_code >= 400:
                error_msg = response.json().get("message", response.text) if response.text else "Unknown error"
                return None, f"GitHub API Error ({response.status_code}): {error_msg}"
            
            if response.status_code == 204:
                return {}, None
            
            return response.json(), None
        except requests.exceptions.RequestException as e:
            return None, f"Request failed: {str(e)}"
        except Exception as e:
            return None, f"Unexpected error: {str(e)}"
    
    def _detect_language(self, file_path: str) -> str:
        """
        Detect programming language from file extension for syntax highlighting.
        
        Args:
            file_path: Path to the file
            
        Returns:
            Language identifier for syntax highlighting
        """
        extension_map = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".jsx": "javascript",
            ".tsx": "typescript",
            ".java": "java",
            ".cpp": "cpp",
            ".c": "c",
            ".h": "c",
            ".hpp": "cpp",
            ".cs": "csharp",
            ".go": "go",
            ".rs": "rust",
            ".rb": "ruby",
            ".php": "php",
            ".swift": "swift",
            ".kt": "kotlin",
            ".scala": "scala",
            ".sql": "sql",
            ".sh": "bash",
            ".bash": "bash",
            ".yaml": "yaml",
            ".yml": "yaml",
            ".json": "json",
            ".xml": "xml",
            ".html": "html",
            ".htm": "html",
            ".css": "css",
            ".scss": "scss",
            ".sass": "sass",
            ".less": "less",
            ".md": "markdown",
            ".markdown": "markdown",
            ".txt": "plaintext",
            ".log": "plaintext",
            ".conf": "plaintext",
            ".config": "plaintext",
            ".ini": "ini",
            ".toml": "toml",
            ".vue": "vue",
            ".svelte": "svelte",
            ".r": "r",
            ".R": "r",
            ".m": "matlab",
            ".pl": "perl",
            ".lua": "lua",
            ".vim": "vim",
            ".ex": "elixir",
            ".exs": "elixir",
            ".erl": "erlang",
            ".hrl": "erlang",
            ".clj": "clojure",
            ".cljs": "clojure",
            ".dart": "dart",
            ".groovy": "groovy",
            ".gradle": "groovy",
        }
        
        # Get file extension
        for ext, lang in extension_map.items():
            if file_path.endswith(ext):
                return lang
        
        return "plaintext"
    
    def _get_change_type_indicator(self, status: FileStatus) -> str:
        """
        Get visual indicator for change type.
        
        Args:
            status: File status enum
            
        Returns:
            Single character indicator
        """
        indicator_map = {
            FileStatus.ADDED: "+",
            FileStatus.MODIFIED: "~",
            FileStatus.DELETED: "-",
            FileStatus.RENAMED: "R",
        }
        return indicator_map.get(status, "~")
    
    def _format_patch_with_line_numbers(self, patch: str) -> str:
        """
        Format patch data with line number annotations.
        
        Args:
            patch: Raw patch string
            
        Returns:
            Patch with enhanced line number annotations
        """
        if not patch:
            return ""
        
        lines = patch.split("\n")
        formatted_lines = []
        
        for line in lines:
            # Hunk headers already contain line numbers (e.g., @@ -1,5 +1,7 @@)
            # We'll preserve them and add visual markers
            if line.startswith("@@"):
                formatted_lines.append(line)
            elif line.startswith("+"):
                formatted_lines.append(line)  # Added line
            elif line.startswith("-"):
                formatted_lines.append(line)  # Deleted line
            else:
                formatted_lines.append(line)  # Context line
        
        return "\n".join(formatted_lines)
    
    def get_commit_diff(self, repo: str, commit_sha: str) -> tuple[Optional[CommitDiff], Optional[str]]:
        """
        Get the diff for a specific commit.
        
        Args:
            repo: Repository in format "owner/repo"
            commit_sha: Commit SHA to retrieve diff for
            
        Returns:
            Tuple of (CommitDiff, error_message)
        """
        # Validate input format
        if not repo or "/" not in repo:
            return None, "Invalid repository format. Expected 'owner/repo'"
        
        if not commit_sha:
            return None, "Commit SHA is required"
        
        # Fetch commit data from GitHub
        endpoint = f"/repos/{repo}/commits/{commit_sha}"
        data, error = self._make_request("GET", endpoint)
        
        if error:
            return None, error
        
        if not data:
            return None, f"Commit {commit_sha} not found in repository {repo}"
        
        # Parse files changed
        files_changed = []
        total_additions = 0
        total_deletions = 0
        
        for file_data in data.get("files", []):
            file_path = file_data.get("filename", "")
            old_path = file_data.get("previous_filename")
            status_str = file_data.get("status", "modified")
            additions = file_data.get("additions", 0)
            deletions = file_data.get("deletions", 0)
            patch = file_data.get("patch", "")
            
            # Determine file status
            if status_str == "renamed":
                status = FileStatus.RENAMED
            elif status_str == "added":
                status = FileStatus.ADDED
            elif status_str == "removed":
                status = FileStatus.DELETED
            else:
                status = FileStatus.MODIFIED
            
            # Detect language for syntax highlighting
            language = self._detect_language(file_path)
            
            # Get change type indicator
            change_indicator = self._get_change_type_indicator(status)
            
            # Format patch with line numbers
            formatted_patch = self._format_patch_with_line_numbers(patch)
            
            file_diff = FileDiff(
                file_path=file_path,
                old_path=old_path,
                status=status,
                additions=additions,
                deletions=deletions,
                patch=formatted_patch,
                language=language,
                change_type_indicator=change_indicator
            )
            
            files_changed.append(file_diff)
            total_additions += additions
            total_deletions += deletions
        
        commit_diff = CommitDiff(
            commit_sha=commit_sha,
            files_changed=files_changed,
            additions=total_additions,
            deletions=total_deletions,
            total_changes=total_additions + total_deletions
        )
        
        return commit_diff, None

    
    def compare_commits(
        self, 
        repo: str, 
        base: str, 
        head: str
    ) -> tuple[Optional[CommitDiff], Optional[str]]:
        """
        Compare two commits and get the diff between them.
        
        Args:
            repo: Repository in format "owner/repo"
            base: Base commit SHA or branch name
            head: Head commit SHA or branch name
            
        Returns:
            Tuple of (CommitDiff, error_message)
        """
        # Validate input format
        if not repo or "/" not in repo:
            return None, "Invalid repository format. Expected 'owner/repo'"
        
        if not base or not head:
            return None, "Both base and head commits are required"
        
        # Use GitHub compare API
        endpoint = f"/repos/{repo}/compare/{base}...{head}"
        data, error = self._make_request("GET", endpoint)
        
        if error:
            return None, error
        
        if not data:
            return None, f"Could not compare {base}...{head} in repository {repo}"
        
        # Parse files changed
        files_changed = []
        total_additions = 0
        total_deletions = 0
        
        for file_data in data.get("files", []):
            file_path = file_data.get("filename", "")
            old_path = file_data.get("previous_filename")
            status_str = file_data.get("status", "modified")
            additions = file_data.get("additions", 0)
            deletions = file_data.get("deletions", 0)
            patch = file_data.get("patch", "")
            
            # Determine file status
            if status_str == "renamed":
                status = FileStatus.RENAMED
            elif status_str == "added":
                status = FileStatus.ADDED
            elif status_str == "removed":
                status = FileStatus.DELETED
            else:
                status = FileStatus.MODIFIED
            
            # Detect language for syntax highlighting
            language = self._detect_language(file_path)
            
            # Get change type indicator
            change_indicator = self._get_change_type_indicator(status)
            
            # Format patch with line numbers
            formatted_patch = self._format_patch_with_line_numbers(patch)
            
            file_diff = FileDiff(
                file_path=file_path,
                old_path=old_path,
                status=status,
                additions=additions,
                deletions=deletions,
                patch=formatted_patch,
                language=language,
                change_type_indicator=change_indicator
            )
            
            files_changed.append(file_diff)
            total_additions += additions
            total_deletions += deletions
        
        # Use the head commit SHA from the comparison
        head_sha = data.get("commits", [{}])[-1].get("sha", head) if data.get("commits") else head
        
        commit_diff = CommitDiff(
            commit_sha=head_sha,
            files_changed=files_changed,
            additions=total_additions,
            deletions=total_deletions,
            total_changes=total_additions + total_deletions
        )
        
        return commit_diff, None
    
    def format_unified_diff(self, diff: CommitDiff) -> str:
        """
        Format a CommitDiff into unified diff format with line numbers.
        
        Args:
            diff: CommitDiff object to format
            
        Returns:
            Formatted unified diff string
        """
        output = []
        output.append(f"commit {diff.commit_sha}")
        output.append(f"{len(diff.files_changed)} files changed, {diff.additions} insertions(+), {diff.deletions} deletions(-)")
        output.append("")
        
        for file_diff in diff.files_changed:
            # File header
            if file_diff.status == FileStatus.RENAMED:
                output.append(f"diff --git a/{file_diff.old_path} b/{file_diff.file_path}")
                output.append(f"rename from {file_diff.old_path}")
                output.append(f"rename to {file_diff.file_path}")
            elif file_diff.status == FileStatus.ADDED:
                output.append(f"diff --git a/{file_diff.file_path} b/{file_diff.file_path}")
                output.append(f"new file")
                output.append(f"--- /dev/null")
                output.append(f"+++ b/{file_diff.file_path}")
            elif file_diff.status == FileStatus.DELETED:
                output.append(f"diff --git a/{file_diff.file_path} b/{file_diff.file_path}")
                output.append(f"deleted file")
                output.append(f"--- a/{file_diff.file_path}")
                output.append(f"+++ /dev/null")
            else:
                output.append(f"diff --git a/{file_diff.file_path} b/{file_diff.file_path}")
                output.append(f"--- a/{file_diff.file_path}")
                output.append(f"+++ b/{file_diff.file_path}")
            
            # Add patch with line numbers
            if file_diff.patch:
                output.append(file_diff.patch)
            
            output.append("")
        
        return "\n".join(output)
    
    def detect_file_renames(self, diff: CommitDiff) -> List[FileRename]:
        """
        Detect renamed or moved files in a diff.
        
        Args:
            diff: CommitDiff object to analyze
            
        Returns:
            List of FileRename objects
        """
        renames = []
        
        for file_diff in diff.files_changed:
            if file_diff.status == FileStatus.RENAMED and file_diff.old_path:
                rename = FileRename(
                    old_path=file_diff.old_path,
                    new_path=file_diff.file_path,
                    commit_sha=diff.commit_sha
                )
                renames.append(rename)
        
        return renames


def get_diff_engine(token: str) -> DiffEngine:
    """
    Factory function to create a DiffEngine instance.
    
    Args:
        token: GitHub Personal Access Token
        
    Returns:
        DiffEngine instance
    """
    return DiffEngine(token)
