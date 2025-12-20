"""
Linear Integration Service
LangChain tools for Linear issue tracking and project management

Uses Personal API Key for authentication.
API Endpoint: https://api.linear.app/graphql
"""

import requests
from typing import Optional
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

# Store credentials at module level for tool access
_linear_config: dict = {}
LINEAR_API_URL = "https://api.linear.app/graphql"


# ============================================================================
# INPUT SCHEMAS
# ============================================================================

class ListTeamsInput(BaseModel):
    """Input schema for listing teams."""
    pass  # No input required


class ListIssuesInput(BaseModel):
    """Input schema for listing issues."""
    team_id: str = Field(default="", description="Team ID to filter issues (optional)")
    project_name: str = Field(default="", description="Project name to filter issues (optional)")
    state: str = Field(default="", description="Filter by state: backlog, todo, in_progress, done (optional)")
    limit: int = Field(default=10, description="Maximum number of issues to return")


class GetIssueInput(BaseModel):
    """Input schema for getting issue details."""
    issue_id: str = Field(description="Issue ID or issue identifier (e.g., 'ABC-123')")


class CreateIssueInput(BaseModel):
    """Input schema for creating an issue."""
    title: str = Field(description="Issue title")
    description: str = Field(default="", description="Issue description (markdown supported)")
    team_id: str = Field(description="Team ID to create the issue in")
    priority: int = Field(default=0, description="Priority: 0=No priority, 1=Urgent, 2=High, 3=Medium, 4=Low")
    state_id: str = Field(default="", description="State ID for the issue (optional)")


class UpdateIssueInput(BaseModel):
    """Input schema for updating an issue."""
    issue_id: str = Field(description="Issue ID to update")
    title: str = Field(default="", description="New title (leave empty to keep)")
    description: str = Field(default="", description="New description (leave empty to keep)")
    state_id: str = Field(default="", description="New state ID (leave empty to keep)")
    priority: int = Field(default=-1, description="New priority: -1=keep, 0-4 to set")


class AddCommentInput(BaseModel):
    """Input schema for adding a comment."""
    issue_id: str = Field(description="Issue ID to comment on")
    body: str = Field(description="Comment body (markdown supported)")


class ListStatesInput(BaseModel):
    """Input schema for listing workflow states."""
    team_id: str = Field(description="Team ID to get workflow states for")


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def _get_headers():
    """Get Linear API headers with authentication."""
    token = _linear_config.get("api_key", "")
    if not token:
        return None, "Error: Linear is not configured. Please connect your Linear account first."
    
    # Use Bearer token format for OAuth access tokens
    return {
        "Authorization": f"Bearer {token}" if not token.startswith("Bearer ") else token,
        "Content-Type": "application/json"
    }, None


def _execute_query(query: str, variables: dict = None):
    """Execute a GraphQL query against the Linear API."""
    headers, error = _get_headers()
    if error:
        return None, error
    
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
    
    try:
        response = requests.post(LINEAR_API_URL, headers=headers, json=payload)
        
        if response.status_code != 200:
            return None, f"Linear API Error ({response.status_code}): {response.text}"
        
        data = response.json()
        
        if "errors" in data:
            error_msg = data["errors"][0].get("message", "Unknown error")
            return None, f"GraphQL Error: {error_msg}"
        
        return data.get("data"), None
    except Exception as e:
        return None, f"Request failed: {str(e)}"


# ============================================================================
# TEAM TOOLS
# ============================================================================

@tool("linear_list_teams")
def linear_list_teams() -> str:
    """
    List all teams in the Linear workspace.
    
    Use this to get team IDs for creating issues or filtering.
    """
    query = """
    query {
        teams {
            nodes {
                id
                name
                key
                description
            }
        }
    }
    """
    
    data, error = _execute_query(query)
    if error:
        return f"❌ {error}"
    
    teams = data.get("teams", {}).get("nodes", [])
    
    if not teams:
        return "📋 No teams found in this workspace."
    
    output = f"📋 Found {len(teams)} team(s):\n\n"
    for team in teams:
        output += f"• **{team['name']}** (Key: {team['key']})\n"
        output += f"  ID: `{team['id']}`\n"
        if team.get('description'):
            output += f"  {team['description'][:60]}\n"
    
    return output


# ============================================================================
# ISSUE TOOLS
# ============================================================================

@tool("linear_list_issues", args_schema=ListIssuesInput)
def linear_list_issues(
    team_id: str = "",
    project_name: str = "",
    state: str = "",
    limit: int = 10
) -> str:
    """
    List issues in Linear, optionally filtered by team or project.
    
    Use this when the user wants to see issues or tasks.
    """
    # Build filter
    filters = []
    if team_id:
        filters.append(f'team: {{ id: {{ eq: "{team_id}" }} }}')
    if project_name:
        filters.append(f'project: {{ name: {{ containsIgnoreCase: "{project_name}" }} }}')
    if state:
        state_map = {"backlog": "backlog", "todo": "unstarted", "in_progress": "started", "done": "completed"}
        if state.lower() in state_map:
            filters.append(f'state: {{ type: {{ eq: "{state_map[state.lower()]}" }} }}')
    
    filter_str = ", ".join(filters) if filters else ""
    filter_clause = f"filter: {{ {filter_str} }}" if filter_str else ""
    
    query = f"""
    query {{
        issues(first: {min(limit, 50)}, {filter_clause}) {{
            nodes {{
                id
                identifier
                title
                priority
                state {{
                    name
                    type
                }}
                assignee {{
                    name
                }}
                team {{
                    name
                }}
            }}
        }}
    }}
    """
    
    data, error = _execute_query(query)
    if error:
        return f"❌ {error}"
    
    issues = data.get("issues", {}).get("nodes", [])
    
    if not issues:
        return "📋 No issues found matching the criteria."
    
    priority_icons = {0: "⚪", 1: "🔴", 2: "🟠", 3: "🟡", 4: "🟢"}
    
    output = f"📋 Found {len(issues)} issue(s):\n\n"
    for issue in issues:
        priority = priority_icons.get(issue.get("priority", 0), "⚪")
        state = issue.get("state", {}).get("name", "Unknown")
        assignee = issue.get("assignee", {})
        assignee_name = assignee.get("name", "Unassigned") if assignee else "Unassigned"
        team = issue.get("team", {}).get("name", "")
        
        output += f"• {priority} **[{issue['identifier']}]** {issue['title']}\n"
        output += f"  📊 {state} • 👤 {assignee_name}"
        if team:
            output += f" • 🏷️ {team}"
        output += "\n"
    
    return output


@tool("linear_get_issue", args_schema=GetIssueInput)
def linear_get_issue(issue_id: str) -> str:
    """
    Get detailed information about a specific issue.
    
    Use this when the user wants details about a particular issue.
    """
    query = """
    query($id: String!) {
        issue(id: $id) {
            id
            identifier
            title
            description
            priority
            url
            createdAt
            updatedAt
            state {
                name
                type
            }
            assignee {
                name
                email
            }
            team {
                name
            }
            project {
                name
            }
            labels {
                nodes {
                    name
                }
            }
            comments {
                nodes {
                    body
                    user {
                        name
                    }
                    createdAt
                }
            }
        }
    }
    """
    
    data, error = _execute_query(query, {"id": issue_id})
    if error:
        return f"❌ {error}"
    
    issue = data.get("issue")
    if not issue:
        return f"❌ Issue '{issue_id}' not found."
    
    priority_map = {0: "No priority", 1: "🔴 Urgent", 2: "🟠 High", 3: "🟡 Medium", 4: "🟢 Low"}
    priority = priority_map.get(issue.get("priority", 0), "Unknown")
    assignee = issue.get("assignee", {})
    assignee_str = assignee.get("name", "Unassigned") if assignee else "Unassigned"
    labels = [l["name"] for l in issue.get("labels", {}).get("nodes", [])]
    
    output = f"""📋 Issue: **[{issue['identifier']}] {issue['title']}**

📊 State: {issue.get('state', {}).get('name', 'Unknown')}
⚡ Priority: {priority}
👤 Assignee: {assignee_str}
🏷️ Team: {issue.get('team', {}).get('name', 'None')}
📁 Project: {issue.get('project', {}).get('name', 'None') if issue.get('project') else 'None'}
🔗 URL: {issue.get('url', 'N/A')}
"""
    
    if labels:
        output += f"🏷️ Labels: {', '.join(labels)}\n"
    
    if issue.get("description"):
        desc = issue["description"][:200]
        if len(issue["description"]) > 200:
            desc += "..."
        output += f"\n📝 Description:\n{desc}\n"
    
    comments = issue.get("comments", {}).get("nodes", [])
    if comments:
        output += f"\n💬 Comments ({len(comments)}):\n"
        for c in comments[:3]:
            user = c.get("user", {}).get("name", "Unknown")
            body = c.get("body", "")[:100]
            output += f"• **{user}**: {body}\n"
    
    return output


@tool("linear_create_issue", args_schema=CreateIssueInput)
def linear_create_issue(
    title: str,
    team_id: str,
    description: str = "",
    priority: int = 0,
    state_id: str = ""
) -> str:
    """
    Create a new issue in Linear.
    
    Use this when the user wants to create a task, bug, or issue.
    """
    query = """
    mutation($input: IssueCreateInput!) {
        issueCreate(input: $input) {
            success
            issue {
                id
                identifier
                title
                url
                state {
                    name
                }
            }
        }
    }
    """
    
    variables = {
        "input": {
            "title": title,
            "teamId": team_id,
            "priority": priority
        }
    }
    
    if description:
        variables["input"]["description"] = description
    if state_id:
        variables["input"]["stateId"] = state_id
    
    data, error = _execute_query(query, variables)
    if error:
        return f"❌ {error}"
    
    result = data.get("issueCreate", {})
    if not result.get("success"):
        return "❌ Failed to create issue."
    
    issue = result.get("issue", {})
    
    return f"""✅ Created issue in Linear

🔢 Issue: **[{issue.get('identifier')}]** {issue.get('title')}
📊 State: {issue.get('state', {}).get('name', 'Unknown')}
🔗 URL: {issue.get('url')}"""


@tool("linear_update_issue", args_schema=UpdateIssueInput)
def linear_update_issue(
    issue_id: str,
    title: str = "",
    description: str = "",
    state_id: str = "",
    priority: int = -1
) -> str:
    """
    Update an existing issue in Linear.
    
    Use this when the user wants to modify an issue's title, description, state, or priority.
    """
    query = """
    mutation($id: String!, $input: IssueUpdateInput!) {
        issueUpdate(id: $id, input: $input) {
            success
            issue {
                id
                identifier
                title
                state {
                    name
                }
            }
        }
    }
    """
    
    input_fields = {}
    if title:
        input_fields["title"] = title
    if description:
        input_fields["description"] = description
    if state_id:
        input_fields["stateId"] = state_id
    if priority >= 0:
        input_fields["priority"] = priority
    
    if not input_fields:
        return "⚠️ No updates specified. Provide title, description, state_id, or priority."
    
    variables = {
        "id": issue_id,
        "input": input_fields
    }
    
    data, error = _execute_query(query, variables)
    if error:
        return f"❌ {error}"
    
    result = data.get("issueUpdate", {})
    if not result.get("success"):
        return "❌ Failed to update issue."
    
    issue = result.get("issue", {})
    
    return f"""✅ Updated issue **[{issue.get('identifier')}]**

📝 Title: {issue.get('title')}
📊 State: {issue.get('state', {}).get('name', 'Unknown')}"""


@tool("linear_add_comment", args_schema=AddCommentInput)
def linear_add_comment(issue_id: str, body: str) -> str:
    """
    Add a comment to an issue.
    
    Use this when the user wants to comment on an issue.
    """
    query = """
    mutation($input: CommentCreateInput!) {
        commentCreate(input: $input) {
            success
            comment {
                id
                body
                issue {
                    identifier
                    title
                }
            }
        }
    }
    """
    
    variables = {
        "input": {
            "issueId": issue_id,
            "body": body
        }
    }
    
    data, error = _execute_query(query, variables)
    if error:
        return f"❌ {error}"
    
    result = data.get("commentCreate", {})
    if not result.get("success"):
        return "❌ Failed to add comment."
    
    comment = result.get("comment", {})
    issue = comment.get("issue", {})
    
    return f"""✅ Added comment to **[{issue.get('identifier')}]** {issue.get('title')}

💬 "{body[:100]}{'...' if len(body) > 100 else ''}" """


# ============================================================================
# WORKFLOW STATE TOOLS
# ============================================================================

@tool("linear_list_states", args_schema=ListStatesInput)
def linear_list_states(team_id: str) -> str:
    """
    List workflow states for a team.
    
    Use this to get state IDs for updating issue status.
    """
    query = """
    query($teamId: String!) {
        team(id: $teamId) {
            name
            states {
                nodes {
                    id
                    name
                    type
                    position
                }
            }
        }
    }
    """
    
    data, error = _execute_query(query, {"teamId": team_id})
    if error:
        return f"❌ {error}"
    
    team = data.get("team")
    if not team:
        return f"❌ Team not found."
    
    states = team.get("states", {}).get("nodes", [])
    
    if not states:
        return f"📊 No workflow states found for team {team.get('name')}."
    
    # Sort by position
    states.sort(key=lambda x: x.get("position", 0))
    
    state_icons = {
        "backlog": "📥",
        "unstarted": "⏳",
        "started": "🔄",
        "completed": "✅",
        "canceled": "❌"
    }
    
    output = f"📊 Workflow states for **{team.get('name')}**:\n\n"
    for state in states:
        icon = state_icons.get(state.get("type", ""), "•")
        output += f"{icon} **{state['name']}** ({state['type']})\n"
        output += f"   ID: `{state['id']}`\n"
    
    return output


# ============================================================================
# TOOL EXPORT
# ============================================================================

def get_linear_tools(api_key: str) -> list[BaseTool]:
    """
    Get LangChain tools for Linear integration.
    
    Args:
        api_key: Linear Personal API Key
        
    Returns:
        List of Linear tools
    """
    global _linear_config
    _linear_config = {"api_key": api_key}
    
    return [
        # Team tools
        linear_list_teams,
        # Issue tools
        linear_list_issues,
        linear_get_issue,
        linear_create_issue,
        linear_update_issue,
        linear_add_comment,
        # Workflow tools
        linear_list_states,
    ]
