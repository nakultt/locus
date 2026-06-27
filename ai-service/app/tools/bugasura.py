"""
Bugasura Integration Service
LangChain tools for bug tracking and issue management

API Reference: https://bugasura.io/api/
- Uses Authorization: Basic <api_key>
- Uses form data (application/x-www-form-urlencoded) for POST requests
"""

import httpx
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field
import json

# Store credentials at module level for tool access
_bugasura_config: dict = {}

# Bugasura API base URL (per docs)
BUGASURA_API_BASE = "https://api.bugasura.io"


class ListTeamsInput(BaseModel):
    """Input schema for listing Bugasura teams."""
    pass

class ListProjectsInput(BaseModel):
    """Input schema for listing Bugasura projects."""
    pass

class ListSprintsInput(BaseModel):
    """Input schema for listing Bugasura sprints."""
    pass

class CreateIssueInput(BaseModel):
    """Input schema for creating a Bugasura issue."""
    sprint_id: int = Field(description="Sprint ID where the issue will be created")
    title: str = Field(description="Title/summary of the bug or issue")
    description: str = Field(default="", description="Detailed description of the issue")
    severity: str = Field(default="MEDIUM", description="Severity: LOW, MEDIUM, HIGH, CRITICAL")


class ListIssuesInput(BaseModel):
    """Input schema for listing Bugasura issues."""
    sprint_id: int | None = Field(default=None, description="Optional sprint ID to filter issues")
    max_results: int = Field(default=10, description="Maximum number of issues to return")


class AddCommentInput(BaseModel):
    """Input schema for adding a comment to an issue."""
    issue_key: int = Field(description="Issue key (Numeric ID, e.g., 78100)")
    comment: str = Field(description="Comment text to add")


class GetIssueInput(BaseModel):
    """Input schema for getting issue details."""
    issue_key: int = Field(description="Issue key (Numeric ID, e.g., 78100)")


class UpdateIssueInput(BaseModel):
    """Input schema for updating an issue."""
    sprint_id: int = Field(description="Sprint ID of the issue")
    issue_key: int = Field(description="Issue key (Numeric ID)")
    status: str = Field(default="", description="New status for the issue (must match workflow)")
    severity: str = Field(default="", description="New severity for the issue")


class DeleteIssueInput(BaseModel):
    """Input schema for deleting an issue."""
    issue_key: int = Field(description="Issue key (Numeric ID) to delete")


def _get_auth_headers() -> dict | None:
    """Get authorization headers for API requests (no Content-Type for form data)."""
    api_key = _bugasura_config.get("api_key")
    if not api_key:
        return None
    
    return {
        "Authorization": f"Basic {api_key}",
        "Accept": "application/json"
    }


def _get_team_id() -> str:
    return _bugasura_config.get("team_id", "")

def _get_project_id() -> str:
    return _bugasura_config.get("project_id", "")

@tool("bugasura_list_teams", args_schema=ListTeamsInput)
def bugasura_list_teams() -> str:
    """
    List teams in Bugasura.
    Use this to find the team_id when interacting with Bugasura.
    """
    try:
        headers = _get_auth_headers()
        if not headers:
            return "Error: Bugasura is not configured."
        
        with httpx.Client() as client:
            response = client.get(
                f"{BUGASURA_API_BASE}/teams/list",
                headers=headers,
                params={"get_invite_accepted_teams_only": 1, "start_at": 0, "max_results": 100}
            )
            
            if response.status_code == 200:
                data = response.json()
                teams = data.get("team_list", [])
                if not teams:
                    return "No teams found."
                
                output = f"Found {len(teams)} team(s):\\n"
                for team in teams:
                    output += f"- Team ID: {team.get('team_id')} | Name: {team.get('team_name')} (Owner: {team.get('owner_name')})\\n"
                return output
            else:
                return f"Failed to list teams: {response.text[:200]}"
    except Exception as e:
        return f"Error listing teams: {str(e)}"

@tool("bugasura_list_projects", args_schema=ListProjectsInput)
def bugasura_list_projects() -> str:
    """
    List projects for the configured team in Bugasura.
    Use this to find the project_id.
    """
    try:
        headers = _get_auth_headers()
        team_id = _get_team_id()
        if not headers or not team_id:
            return "Error: Bugasura API Key or Team ID is not configured."
        
        with httpx.Client() as client:
            response = client.get(
                f"{BUGASURA_API_BASE}/projects/list",
                headers=headers,
                params={"team_id": team_id, "start_at": 0, "max_results": 100}
            )
            
            if response.status_code == 200:
                data = response.json()
                projects = data.get("project_list", [])
                if not projects:
                    return "No projects found."
                
                output = f"Found {len(projects)} project(s):\\n"
                for proj in projects:
                    output += f"- Project ID: {proj.get('project_id')} | Name: {proj.get('project_name')}\\n"
                return output
            else:
                return f"Failed to list projects: {response.text[:200]}"
    except Exception as e:
        return f"Error listing projects: {str(e)}"

@tool("bugasura_list_sprints", args_schema=ListSprintsInput)
def bugasura_list_sprints() -> str:
    """
    List sprints for the configured project in Bugasura.
    Use this to find a sprint_id before creating an issue.
    """
    try:
        headers = _get_auth_headers()
        team_id = _get_team_id()
        project_id = _get_project_id()
        if not headers or not team_id or not project_id:
            return "Error: Bugasura API Key, Team ID, or Project ID is not configured."
        
        with httpx.Client() as client:
            response = client.get(
                f"{BUGASURA_API_BASE}/sprints/list",
                headers=headers,
                params={"team_id": team_id, "project_id": project_id, "start_at": 0, "max_results": 100}
            )
            
            if response.status_code == 200:
                data = response.json()
                sprints = data.get("sprintList", [])
                if not sprints:
                    return "No sprints found."
                
                output = f"Found {len(sprints)} sprint(s):\\n"
                for sprint in sprints:
                    output += f"- Sprint ID: {sprint.get('sprint_id')} | Name: {sprint.get('sprint_name')}\\n"
                return output
            else:
                return f"Failed to list sprints: {response.text[:200]}"
    except Exception as e:
        return f"Error listing sprints: {str(e)}"

@tool("bugasura_create_issue", args_schema=CreateIssueInput)
def bugasura_create_issue(
    sprint_id: int,
    title: str,
    description: str = "",
    severity: str = "MEDIUM"
) -> str:
    """
    Create a new bug or issue in Bugasura.
    Requires sprint_id. Use bugasura_list_sprints if you don't know it.
    """
    try:
        headers = _get_auth_headers()
        team_id = _get_team_id()
        
        if not headers or not team_id:
            return "Error: Bugasura API Key or Team ID is not configured."
        
        form_data = {
            "team_id": team_id,
            "sprint_id": sprint_id,
            "summary": title,
            "description": description,
            "issue_type": "Issue",
            "severity": severity,
        }
        
        with httpx.Client() as client:
            response = client.post(
                f"{BUGASURA_API_BASE}/issues/add",
                headers=headers,
                data=form_data
            )
            
            if response.status_code in [200, 201]:
                result = response.json()
                if "issueDetails" in result:
                    issue_key = result["issueDetails"].get("issue_key", "N/A")
                    issue_id = result["issueDetails"].get("issue_id", "N/A")
                    return f"✅ Bug created successfully!\\n🐛 {title}\\n🔑 Issue Key: {issue_key} (ID: {issue_id})\\n⚡ Severity: {severity}"
                return "✅ Bug created successfully!"
            else:
                return f"❌ Failed to create issue: {response.text[:200]}"
                
    except Exception as e:
        return f"❌ Error creating Bugasura issue: {str(e)}"


@tool("bugasura_list_issues", args_schema=ListIssuesInput)
def bugasura_list_issues(max_results: int = 10, sprint_id: int | None = None) -> str:
    """
    List bugs and issues from Bugasura.
    """
    try:
        headers = _get_auth_headers()
        team_id = _get_team_id()
        project_id = _get_project_id()
        
        if not headers or not team_id or not project_id:
            return "Error: Bugasura API Key, Team ID, or Project ID is not configured."
        
        params = {
            "team_id": team_id,
            "project_id": project_id,
            "start_at": 0,
            "max_results": max_results
        }
        if sprint_id:
            params["sprint_id"] = sprint_id
        
        with httpx.Client() as client:
            response = client.get(
                f"{BUGASURA_API_BASE}/issues/list",
                headers=headers,
                params=params
            )
            
            if response.status_code == 200:
                data = response.json()
                issues = data.get("issue_list", [])
                
                if not issues:
                    return "📭 No issues found."
                
                output = f"🐛 Found {len(issues)} issue(s):\\n\\n"
                
                for issue in issues[:max_results]:
                    key = issue.get("issue_key", "N/A")
                    issue_id = issue.get("issue_id", "N/A")
                    summary = issue.get("summary", "Untitled")
                    status = issue.get("status", "unknown")
                    severity = issue.get("severity", "Medium")
                    
                    output += f"• [Key: {key}] [ID: {issue_id}] {summary}\\n"
                    output += f"  Status: {status} | Severity: {severity}\\n\\n"
                
                return output
            else:
                return f"❌ Failed to list issues: {response.text[:200]}"
                
    except Exception as e:
        return f"❌ Error listing Bugasura issues: {str(e)}"


@tool("bugasura_add_comment", args_schema=AddCommentInput)
def bugasura_add_comment(issue_key: int, comment: str) -> str:
    """
    Add a comment to a Bugasura issue.
    """
    try:
        headers = _get_auth_headers()
        team_id = _get_team_id()
        if not headers or not team_id:
            return "Error: Bugasura API Key or Team ID is not configured."
        
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
                return f"✅ Comment added to {issue_key}!\\n💬 \\\"{comment[:100]}{'...' if len(comment) > 100 else ''}\\\""
            else:
                return f"❌ Failed to add comment: {response.text[:200]}"
                
    except Exception as e:
        return f"❌ Error adding comment: {str(e)}"


@tool("bugasura_get_issue", args_schema=GetIssueInput)
def bugasura_get_issue(issue_key: int) -> str:
    """
    Get details of a specific Bugasura issue.
    """
    try:
        headers = _get_auth_headers()
        team_id = _get_team_id()
        project_id = _get_project_id()
        
        if not headers or not team_id or not project_id:
            return "Error: Bugasura API Key, Team ID, or Project ID is not configured."
        
        with httpx.Client() as client:
            response = client.get(
                f"{BUGASURA_API_BASE}/issues/get",
                headers=headers,
                params={"team_id": team_id, "project_id": project_id, "issue_key": issue_key}
            )
            
            if response.status_code == 200:
                data = response.json()
                issue = data.get("issueDetails", data)
                
                summary = issue.get("summary", "Untitled")
                description = issue.get("description", "No description")
                status = issue.get("status", "unknown")
                severity = issue.get("severity", "Medium")
                sprint_name = issue.get("sprint_name", "Unknown sprint")
                
                return f"🐛 **{issue_key}**: {summary}\\n\\n📋 **Status**: {status}\\n⚡ **Severity**: {severity}\\n🏃 **Sprint**: {sprint_name}\\n\\n📝 **Description**:\\n{str(description)[:500]}{'...' if len(str(description)) > 500 else ''}"
            elif response.status_code == 404:
                return f"❌ Issue not found: {issue_key}"
            else:
                return f"❌ Failed to get issue: {response.text[:200]}"
                
    except Exception as e:
        return f"❌ Error getting Bugasura issue: {str(e)}"

@tool("bugasura_update_issue", args_schema=UpdateIssueInput)
def bugasura_update_issue(sprint_id: int, issue_key: int, status: str = "", severity: str = "") -> str:
    """
    Update a Bugasura issue status or severity.
    """
    try:
        headers = _get_auth_headers()
        team_id = _get_team_id()
        
        if not headers or not team_id:
            return "Error: Bugasura API Key or Team ID is not configured."
        
        form_data = {
            "team_id": team_id,
            "sprint_id": sprint_id,
            "issue_key": issue_key,
        }
        if status:
            form_data["status"] = status
        if severity:
            form_data["severity"] = severity
            
        with httpx.Client() as client:
            response = client.post(
                f"{BUGASURA_API_BASE}/issues/update",
                headers=headers,
                data=form_data
            )
            
            if response.status_code in [200, 201]:
                return f"✅ Issue {issue_key} updated successfully!"
            else:
                return f"❌ Failed to update issue: {response.text[:200]}"
                
    except Exception as e:
        return f"❌ Error updating Bugasura issue: {str(e)}"

@tool("bugasura_delete_issue", args_schema=DeleteIssueInput)
def bugasura_delete_issue(issue_key: int) -> str:
    """
    Delete a Bugasura issue.
    """
    try:
        headers = _get_auth_headers()
        team_id = _get_team_id()
        
        if not headers or not team_id:
            return "Error: Bugasura API Key or Team ID is not configured."
        
        form_data = {
            "team_id": team_id,
            "issue_key": issue_key,
        }
            
        with httpx.Client() as client:
            response = client.post(
                f"{BUGASURA_API_BASE}/issues/delete",
                headers=headers,
                data=form_data
            )
            
            if response.status_code in [200, 201]:
                return f"✅ Issue {issue_key} deleted successfully!"
            else:
                return f"❌ Failed to delete issue: {response.text[:200]}"
                
    except Exception as e:
        return f"❌ Error deleting Bugasura issue: {str(e)}"


def get_bugasura_tools(api_key: str, team_id: str = "", project_id: str = "") -> list[BaseTool]:
    """
    Get LangChain tools for Bugasura integration.
    
    Args:
        api_key: Bugasura API key
        team_id: Bugasura team ID
        project_id: Bugasura project ID
        
    Returns:
        List of Bugasura tools
    """
    global _bugasura_config
    _bugasura_config = {
        "api_key": api_key,
        "team_id": team_id,
        "project_id": project_id
    }
    
    return [
        bugasura_list_teams,
        bugasura_list_projects,
        bugasura_list_sprints,
        bugasura_create_issue,
        bugasura_list_issues,
        bugasura_add_comment,
        bugasura_get_issue,
        bugasura_update_issue,
        bugasura_delete_issue,
    ]
