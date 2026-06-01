"""
Bugasura Integration Service
LangChain tools for bug tracking and issue management

API Reference: https://bugasura.io/api/
- Uses Authorization: Basic <api_key>
- Uses form data (application/x-www-form-urlencoded) for POST requests
- Endpoint: https://api.bugasura.io/issues/add
"""

import httpx
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

# Store credentials at module level for tool access
_bugasura_config: dict = {}

# Bugasura API base URL (per docs)
BUGASURA_API_BASE = "https://api.bugasura.io"


class CreateIssueInput(BaseModel):
    """Input schema for creating a Bugasura issue."""
    title: str = Field(description="Title/summary of the bug or issue")
    description: str = Field(default="", description="Detailed description of the issue")
    severity: str = Field(default="Medium", description="Severity: Low, Medium, High, Critical")


class ListIssuesInput(BaseModel):
    """Input schema for listing Bugasura issues."""
    max_results: int = Field(default=10, description="Maximum number of issues to return")


class AddCommentInput(BaseModel):
    """Input schema for adding a comment to an issue."""
    issue_key: str = Field(description="Issue key (e.g., 'LOC-5')")
    comment: str = Field(description="Comment text to add")


class GetIssueInput(BaseModel):
    """Input schema for getting issue details."""
    issue_key: str = Field(description="Issue key (e.g., 'LOC-5')")


def _get_auth_headers() -> dict | None:
    """Get authorization headers for API requests (no Content-Type for form data)."""
    api_key = _bugasura_config.get("api_key")
    if not api_key:
        return None
    
    return {
        "Authorization": f"Basic {api_key}",
        "Accept": "application/json"
    }


@tool("bugasura_create_issue", args_schema=CreateIssueInput)
def bugasura_create_issue(
    title: str,
    description: str = "",
    severity: str = "Medium"
) -> str:
    """
    Create a new bug or issue in Bugasura.
    
    Use this when the user wants to report a bug, create an issue, or log a problem in Bugasura.
    """
    try:
        headers = _get_auth_headers()
        if not headers:
            return "Error: Bugasura is not configured. Please connect your Bugasura account first."
        
        team_id = _bugasura_config.get("team_id", "")
        project_key = _bugasura_config.get("project_key", "")
        
        if not team_id:
            return "Error: Bugasura team_id not configured. Please reconnect with your team ID."
        
        if not project_key:
            return "Error: Bugasura project_key not configured. Please reconnect with your project key."
        
        # Build form data (Bugasura uses form-urlencoded, not JSON)
        form_data = {
            "team_id": team_id,
            "project_key": project_key,
            "summary": title,
            "description": description,
            "issue_type": "BUG",
            "status": "New",
            "severity": severity,
        }
        
        print(f"[DEBUG BUGASURA] POST /issues/add with form_data: team_id={team_id}, project_key={project_key}, summary={title[:30]}", flush=True)
        
        with httpx.Client() as client:
            response = client.post(
                f"{BUGASURA_API_BASE}/issues/add",
                headers=headers,
                data=form_data  # Form data, not json=
            )
            
            print(f"[DEBUG BUGASURA] Response: {response.status_code} - {response.text[:300]}", flush=True)
            
            if response.status_code in [200, 201]:
                result = response.json()
                issue_key = result.get("issue_key", result.get("key", result.get("id", "N/A")))
                return f"""✅ Bug created successfully!
🐛 {title}
🔑 Issue Key: {issue_key}
⚡ Severity: {severity}"""
            else:
                try:
                    error_detail = response.json().get("message", response.text[:200])
                except:
                    error_detail = response.text[:200]
                return f"❌ Failed to create issue: {error_detail}"
                
    except Exception as e:
        return f"❌ Error creating Bugasura issue: {str(e)}"


@tool("bugasura_list_issues", args_schema=ListIssuesInput)
def bugasura_list_issues(max_results: int = 10) -> str:
    """
    List bugs and issues from Bugasura.
    
    Use this when the user wants to see bugs, list issues, or check what's in Bugasura.
    """
    try:
        headers = _get_auth_headers()
        if not headers:
            return "Error: Bugasura is not configured. Please connect your Bugasura account first."
        
        team_id = _bugasura_config.get("team_id", "")
        project_key = _bugasura_config.get("project_key", "")
        
        if not team_id:
            return "Error: Bugasura team_id not configured."
        
        params = {"team_id": team_id}
        if project_key:
            params["project_key"] = project_key
        
        with httpx.Client() as client:
            response = client.get(
                f"{BUGASURA_API_BASE}/issues/list",
                headers=headers,
                params=params
            )
            
            if response.status_code == 200:
                data = response.json()
                issues = data.get("issues", data.get("data", data if isinstance(data, list) else []))
                
                if not issues:
                    return "📭 No issues found."
                
                output = f"🐛 Found {len(issues)} issue(s):\n\n"
                
                for issue in issues[:max_results]:
                    key = issue.get("issue_key", issue.get("key", issue.get("id", "N/A")))
                    summary = issue.get("summary", issue.get("title", "Untitled"))
                    status = issue.get("status", "unknown")
                    severity = issue.get("severity", "Medium")
                    
                    output += f"• [{key}] {summary}\n"
                    output += f"  Status: {status} | Severity: {severity}\n\n"
                
                return output
            else:
                try:
                    error_detail = response.json().get("message", response.text[:200])
                except:
                    error_detail = response.text[:200]
                return f"❌ Failed to list issues: {error_detail}"
                
    except Exception as e:
        return f"❌ Error listing Bugasura issues: {str(e)}"


@tool("bugasura_add_comment", args_schema=AddCommentInput)
def bugasura_add_comment(issue_key: str, comment: str) -> str:
    """
    Add a comment to a Bugasura issue.
    
    Use this when the user wants to comment on a bug or add notes to an issue.
    """
    try:
        headers = _get_auth_headers()
        if not headers:
            return "Error: Bugasura is not configured."
        
        team_id = _bugasura_config.get("team_id", "")
        
        form_data = {
            "team_id": team_id,
            "issue_key": issue_key,
            "comment": comment
        }
        
        with httpx.Client() as client:
            response = client.post(
                f"{BUGASURA_API_BASE}/issues/comments/add",
                headers=headers,
                data=form_data
            )
            
            if response.status_code in [200, 201]:
                return f"""✅ Comment added to {issue_key}!
💬 "{comment[:100]}{'...' if len(comment) > 100 else ''}" """
            else:
                try:
                    error_detail = response.json().get("message", response.text[:200])
                except:
                    error_detail = response.text[:200]
                return f"❌ Failed to add comment: {error_detail}"
                
    except Exception as e:
        return f"❌ Error adding comment: {str(e)}"


@tool("bugasura_get_issue", args_schema=GetIssueInput)
def bugasura_get_issue(issue_key: str) -> str:
    """
    Get details of a specific Bugasura issue.
    
    Use this when the user wants to see bug details or get info about an issue.
    """
    try:
        headers = _get_auth_headers()
        if not headers:
            return "Error: Bugasura is not configured."
        
        team_id = _bugasura_config.get("team_id", "")
        
        with httpx.Client() as client:
            response = client.get(
                f"{BUGASURA_API_BASE}/issues/get",
                headers=headers,
                params={"team_id": team_id, "issue_key": issue_key}
            )
            
            if response.status_code == 200:
                issue = response.json()
                
                summary = issue.get("summary", issue.get("title", "Untitled"))
                description = issue.get("description", "No description")
                status = issue.get("status", "unknown")
                severity = issue.get("severity", "Medium")
                
                return f"""🐛 **{issue_key}**: {summary}

📋 **Status**: {status}
⚡ **Severity**: {severity}

📝 **Description**:
{str(description)[:500]}{'...' if len(str(description)) > 500 else ''}"""
            elif response.status_code == 404:
                return f"❌ Issue not found: {issue_key}"
            else:
                try:
                    error_detail = response.json().get("message", response.text[:200])
                except:
                    error_detail = response.text[:200]
                return f"❌ Failed to get issue: {error_detail}"
                
    except Exception as e:
        return f"❌ Error getting Bugasura issue: {str(e)}"


def get_bugasura_tools(api_key: str, team_id: str = "", project_key: str = "") -> list[BaseTool]:
    """
    Get LangChain tools for Bugasura integration.
    
    Args:
        api_key: Bugasura API key
        team_id: Bugasura team ID
        project_key: Bugasura project key (e.g., 'LOC')
        
    Returns:
        List of Bugasura tools
    """
    global _bugasura_config
    _bugasura_config = {
        "api_key": api_key,
        "team_id": team_id,
        "project_key": project_key
    }
    
    return [
        bugasura_create_issue,
        bugasura_list_issues,
        bugasura_add_comment,
        bugasura_get_issue,
    ]
