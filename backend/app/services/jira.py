"""
Jira Integration Service
LangChain tools for Jira issue management
"""

from typing import Optional
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

# Store credentials at module level for tool access
_jira_config: dict = {}


class JiraIssueInput(BaseModel):
    """Input schema for creating a Jira issue."""
    summary: str = Field(description="Brief title/summary of the issue")
    description: str = Field(default="", description="Detailed description of the issue")
    project_key: str = Field(default="CONFLUX", description="Jira project key")
    issue_type: str = Field(default="Task", description="Issue type: Task, Bug, Story, etc.")


class JiraSearchInput(BaseModel):
    """Input schema for searching Jira issues."""
    query: str = Field(description="JQL query or simple text search")
    max_results: int = Field(default=10, description="Maximum number of results")


@tool("jira_create_issue", args_schema=JiraIssueInput)
def jira_create_issue(
    summary: str,
    description: str = "",
    project_key: str = "CONFLUX",
    issue_type: str = "Task"
) -> str:
    """
    Create a new Jira issue/ticket.
    
    Use this when the user wants to create a new ticket, issue, bug report, or task in Jira.
    """
    try:
        # Check if Jira is configured
        if not _jira_config.get("api_token"):
            return "Error: Jira is not configured. Please connect your Jira account first."
        
        api_token = _jira_config["api_token"]
        email = _jira_config.get("email", "")
        url = _jira_config.get("url", "")
        
        # Try to use atlassian-python-api if available
        try:
            from atlassian import Jira
            
            jira = Jira(
                url=url,
                username=email,
                password=api_token,
                cloud=True
            )
            
            issue_data = {
                "project": {"key": project_key},
                "summary": summary,
                "description": description,
                "issuetype": {"name": issue_type}
            }
            
            result = jira.create_issue(fields=issue_data)
            issue_key = result.get("key", "UNKNOWN")
            
            return f"✅ Created Jira issue: {issue_key}\nSummary: {summary}\nType: {issue_type}\nURL: {url}/browse/{issue_key}"
            
        except ImportError:
            # Fallback to mock response for demo
            import random
            issue_key = f"{project_key}-{random.randint(100, 999)}"
            return f"✅ Created Jira issue: {issue_key}\nSummary: {summary}\nType: {issue_type}\n(Demo mode - atlassian-python-api not installed)"
            
    except Exception as e:
        return f"❌ Error creating Jira issue: {str(e)}"


@tool("jira_search_issues", args_schema=JiraSearchInput)
def jira_search_issues(query: str, max_results: int = 10) -> str:
    """
    Search for Jira issues using JQL or text search.
    
    Use this when the user wants to find existing tickets, search for issues, or list their tasks.
    """
    try:
        if not _jira_config.get("api_token"):
            return "Error: Jira is not configured. Please connect your Jira account first."
        
        api_token = _jira_config["api_token"]
        email = _jira_config.get("email", "")
        url = _jira_config.get("url", "")
        
        try:
            from atlassian import Jira
            
            jira = Jira(
                url=url,
                username=email,
                password=api_token,
                cloud=True
            )
            
            # If simple text, convert to JQL
            if not any(op in query for op in ["=", "~", "ORDER BY"]):
                jql = f'text ~ "{query}" ORDER BY created DESC'
            else:
                jql = query
            
            results = jira.jql(jql, limit=max_results)
            issues = results.get("issues", [])
            
            if not issues:
                return f"No issues found matching: {query}"
            
            output = f"Found {len(issues)} issue(s):\n\n"
            for issue in issues:
                key = issue["key"]
                summary = issue["fields"]["summary"]
                status = issue["fields"]["status"]["name"]
                output += f"• [{key}] {summary} ({status})\n"
            
            return output
            
        except ImportError:
            # Mock response for demo
            return f"""Found 3 issues matching "{query}":

• [CONFLUX-123] Login page not loading - In Progress
• [CONFLUX-124] Database connection timeout - Open
• [CONFLUX-125] Update user documentation - Done

(Demo mode - atlassian-python-api not installed)"""
            
    except Exception as e:
        return f"❌ Error searching Jira: {str(e)}"


@tool("jira_get_my_issues")
def jira_get_my_issues() -> str:
    """
    Get issues assigned to the current user.
    
    Use this when the user asks about their tasks, their tickets, or what they're working on.
    """
    try:
        if not _jira_config.get("api_token"):
            return "Error: Jira is not configured. Please connect your Jira account first."
        
        email = _jira_config.get("email", "")
        
        try:
            from atlassian import Jira
            
            jira = Jira(
                url=_jira_config.get("url", ""),
                username=email,
                password=_jira_config["api_token"],
                cloud=True
            )
            
            jql = f'assignee = "{email}" AND status != Done ORDER BY priority DESC'
            results = jira.jql(jql, limit=10)
            issues = results.get("issues", [])
            
            if not issues:
                return "You have no open issues assigned to you."
            
            output = f"Your open issues ({len(issues)}):\n\n"
            for issue in issues:
                key = issue["key"]
                summary = issue["fields"]["summary"]
                status = issue["fields"]["status"]["name"]
                priority = issue["fields"]["priority"]["name"]
                output += f"• [{key}] {summary}\n  Status: {status} | Priority: {priority}\n"
            
            return output
            
        except ImportError:
            return f"""Your open issues (3):

• [CONFLUX-101] Implement user authentication
  Status: In Progress | Priority: High

• [CONFLUX-102] Set up CI/CD pipeline
  Status: Open | Priority: Medium

• [CONFLUX-103] Write API documentation
  Status: Open | Priority: Low

(Demo mode - atlassian-python-api not installed)"""
            
    except Exception as e:
        return f"❌ Error fetching your issues: {str(e)}"


def get_jira_tools(
    api_token: str,
    email: str = "",
    url: str = ""
) -> list[BaseTool]:
    """
    Get LangChain tools for Jira integration.
    
    Args:
        api_token: Jira API token
        email: User email for Jira Cloud
        url: Jira instance URL (e.g., https://company.atlassian.net)
        
    Returns:
        List of Jira tools
    """
    global _jira_config
    _jira_config = {
        "api_token": api_token,
        "email": email,
        "url": url
    }
    
    return [
        jira_create_issue,
        jira_search_issues,
        jira_get_my_issues
    ]
