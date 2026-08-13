"""
Jira Integration Service
LangChain tools for Jira issue management, project administration, and workflow management

Scopes used:
- read:jira-work
- write:jira-work
- read:jira-user
- manage:jira-project
- manage:jira-configuration
"""

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from app.services.credential_context import CredentialProxy

# Store credentials at module level for tool access
# Task-local so concurrent users cannot see each other's credentials.
# See app/services/credential_context.py.
_jira_config = CredentialProxy("jira")


# ============================================================================
# INPUT SCHEMAS
# ============================================================================

class CreateIssueInput(BaseModel):
    """Input schema for creating a Jira issue."""
    summary: str = Field(description="Brief title/summary of the issue")
    description: str = Field(default="", description="Detailed description of the issue")
    project_key: str = Field(
        default="",
        description=(
            "Jira project key (e.g., 'KAN'). Leave empty to use the default "
            "project configured on the integration. Never invent a key -- if "
            "there is no default and the user did not name one, call "
            "jira_list_projects first."
        ),
    )
    issue_type: str = Field(default="Task", description="Issue type: Task, Bug, Story, Epic, etc.")
    priority: str = Field(default="Medium", description="Priority: Highest, High, Medium, Low, Lowest")
    assignee: str = Field(default="", description="Account ID or email of assignee (optional)")
    labels: str = Field(default="", description="Comma-separated labels (optional)")


class UpdateIssueInput(BaseModel):
    """Input schema for updating a Jira issue."""
    issue_key: str = Field(description="Issue key (e.g., 'PROJ-123')")
    summary: str = Field(default="", description="New summary (leave empty to keep current)")
    description: str = Field(default="", description="New description (leave empty to keep current)")
    priority: str = Field(default="", description="New priority (leave empty to keep current)")
    assignee: str = Field(default="", description="New assignee account ID or email (leave empty to keep current)")
    labels: str = Field(default="", description="New comma-separated labels (leave empty to keep current)")


class AddCommentInput(BaseModel):
    """Input schema for adding a comment to an issue."""
    issue_key: str = Field(description="Issue key (e.g., 'PROJ-123')")
    comment: str = Field(description="Comment text to add")


class TransitionIssueInput(BaseModel):
    """Input schema for transitioning an issue."""
    issue_key: str = Field(description="Issue key (e.g., 'PROJ-123')")
    transition_name: str = Field(description="Transition name (e.g., 'In Progress', 'Done', 'To Do')")


class SearchIssuesInput(BaseModel):
    """Input schema for searching Jira issues."""
    jql: str = Field(description="JQL query string (e.g., 'project = PROJ AND status = Open')")
    max_results: int = Field(default=10, description="Maximum number of results (1-50)")


class CreateProjectInput(BaseModel):
    """Input schema for creating a Jira project."""
    name: str = Field(description="Project name")
    key: str = Field(description="Project key (uppercase, 2-10 characters, e.g., 'PROJ')")
    project_type: str = Field(default="software", description="Project type: software, business, service_desk")
    lead_account_id: str = Field(default="", description="Account ID of project lead (optional)")
    description: str = Field(default="", description="Project description")


class DeleteProjectInput(BaseModel):
    """Input schema for deleting a Jira project."""
    project_key: str = Field(description="Project key to delete (e.g., 'PROJ')")
    confirm: bool = Field(default=False, description="REQUIRED: Must be set to true to confirm deletion")


class AssignWorkflowInput(BaseModel):
    """Input schema for assigning a workflow to a project."""
    project_key: str = Field(description="Project key (e.g., 'PROJ')")
    workflow_scheme_id: str = Field(description="ID of the workflow scheme to assign")


class AssignPermissionSchemeInput(BaseModel):
    """Input schema for assigning permission scheme to project."""
    project_key: str = Field(description="Project key (e.g., 'PROJ')")
    permission_scheme_id: str = Field(description="ID of the permission scheme to assign")


# ============================================================================
# HELPER FUNCTION
# ============================================================================

def _get_jira_client():
    """Get configured Jira client or raise error."""
    if not _jira_config.get("api_token"):
        return None, "Error: Jira is not configured. Please connect your Jira account first."
    
    try:
        from atlassian import Jira
        jira = Jira(
            url=_jira_config.get("url", ""),
            username=_jira_config.get("email", ""),
            password=_jira_config["api_token"],
            cloud=True
        )
        return jira, None
    except ImportError:
        return None, "DEMO_MODE"


def _fetch_projects() -> tuple[list[dict], str | None]:
    """Return (projects, error). Each project is {"key", "name"}."""
    jira, error = _get_jira_client()
    if error == "DEMO_MODE":
        return [], "DEMO_MODE"
    if error:
        return [], error

    try:
        raw = jira.projects()
    except Exception as exc:
        return [], f"Error listing projects: {exc}"

    # `projects()` returns a bare list on Jira Cloud but a paginated dict on
    # some Server versions.
    if isinstance(raw, dict):
        raw = raw.get("values", [])

    return [
        {"key": p.get("key", ""), "name": p.get("name", "")}
        for p in raw or []
        if p.get("key")
    ], None


def _describe_projects(hint: str) -> str:
    """Render the available projects, for use in an error the model reads."""
    projects, error = _fetch_projects()
    if error == "DEMO_MODE":
        return hint
    if error:
        return f"Could not list projects to suggest one: {error}"
    if not projects:
        return "No projects exist in this Jira instance yet -- create one first."

    listing = "\n".join(f"• {p['key']} — {p['name']}" for p in projects[:25])
    return f"Available projects:\n{listing}\n\n{hint}"


# ============================================================================
# ISSUE MANAGEMENT TOOLS
# ============================================================================

@tool("jira_list_projects")
def jira_list_projects() -> str:
    """
    List the Jira projects this account can see, with their keys.

    Use this before creating an issue when no project key is known, rather
    than guessing a key that may not exist.
    """
    projects, error = _fetch_projects()

    if error == "DEMO_MODE":
        return "📁 Demo mode - atlassian-python-api not installed."
    if error:
        return f"❌ {error}"
    if not projects:
        return "📁 No projects found in this Jira instance."

    default = _jira_config.get("default_project_key", "")
    lines = []
    for project in projects:
        marker = "  (default)" if project["key"] == default else ""
        lines.append(f"• **{project['key']}** — {project['name']}{marker}")

    return f"📁 Found {len(projects)} projects:\n\n" + "\n".join(lines)

@tool("jira_create_issue", args_schema=CreateIssueInput)
def jira_create_issue(
    summary: str,
    project_key: str = "",
    description: str = "",
    issue_type: str = "Task",
    priority: str = "Medium",
    assignee: str = "",
    labels: str = ""
) -> str:
    """
    Create a new Jira issue/ticket.

    Use this when the user wants to create a new ticket, issue, bug report, or task in Jira.

    Omit project_key to use the project configured on the integration. Do not
    guess a key: if none is configured, this returns the list of real projects
    to choose from.
    """
    try:
        project_key = (project_key or _jira_config.get("default_project_key", "")).strip()
        if not project_key:
            return (
                "❌ No project key given and no default project is configured "
                "on the Jira integration.\n\n"
                + _describe_projects(
                    "Pass one of these as project_key, or set a default project "
                    "in Settings → Integrations → Jira."
                )
            )
        project_key = project_key.upper()

        jira, error = _get_jira_client()
        
        if error == "DEMO_MODE":
            import random
            issue_key = f"{project_key}-{random.randint(100, 999)}"
            return f"""✅ Created Jira issue: {issue_key}
📝 Summary: {summary}
📁 Project: {project_key}
🏷️ Type: {issue_type}
⚡ Priority: {priority}

(Demo mode - atlassian-python-api not installed)"""
        
        if error:
            return error
        
        fields = {
            "project": {"key": project_key},
            "summary": summary,
            "description": description,
            "issuetype": {"name": issue_type},
            "priority": {"name": priority}
        }
        
        if assignee:
            fields["assignee"] = {"accountId": assignee} if "-" in assignee else {"emailAddress": assignee}
        
        if labels:
            fields["labels"] = [l.strip() for l in labels.split(",")]
        
        result = jira.create_issue(fields=fields)
        issue_key = result.get("key", "UNKNOWN")
        url = _jira_config.get("url", "")
        
        return f"""✅ Created Jira issue: {issue_key}
📝 Summary: {summary}
📁 Project: {project_key}
🏷️ Type: {issue_type}
⚡ Priority: {priority}
🔗 URL: {url}/browse/{issue_key}"""
            
    except Exception as e:
        return f"❌ Error creating Jira issue: {str(e)}"


@tool("jira_update_issue", args_schema=UpdateIssueInput)
def jira_update_issue(
    issue_key: str,
    summary: str = "",
    description: str = "",
    priority: str = "",
    assignee: str = "",
    labels: str = ""
) -> str:
    """
    Update an existing Jira issue.
    
    Use this when the user wants to modify, edit, or update a ticket's details.
    """
    try:
        jira, error = _get_jira_client()
        
        if error == "DEMO_MODE":
            updates = []
            if summary: updates.append(f"Summary: {summary}")
            if description: updates.append("Description updated")
            if priority: updates.append(f"Priority: {priority}")
            if assignee: updates.append(f"Assignee: {assignee}")
            if labels: updates.append(f"Labels: {labels}")
            
            return f"""✅ Updated {issue_key}
{''.join([f'  • {u}' + chr(10) for u in updates])}
(Demo mode - atlassian-python-api not installed)"""
        
        if error:
            return error
        
        fields = {}
        if summary:
            fields["summary"] = summary
        if description:
            fields["description"] = description
        if priority:
            fields["priority"] = {"name": priority}
        if assignee:
            fields["assignee"] = {"accountId": assignee} if "-" in assignee else {"emailAddress": assignee}
        if labels:
            fields["labels"] = [l.strip() for l in labels.split(",")]
        
        if not fields:
            return "⚠️ No fields to update. Please specify at least one field."
        
        jira.update_issue_field(issue_key, fields)
        
        return f"""✅ Updated {issue_key}
Updated fields: {', '.join(fields.keys())}"""
            
    except Exception as e:
        return f"❌ Error updating issue: {str(e)}"


@tool("jira_add_comment", args_schema=AddCommentInput)
def jira_add_comment(issue_key: str, comment: str) -> str:
    """
    Add a comment to a Jira issue.
    
    Use this when the user wants to comment on a ticket or add notes to an issue.
    """
    try:
        jira, error = _get_jira_client()
        
        if error == "DEMO_MODE":
            return f"""✅ Comment added to {issue_key}
💬 "{comment[:100]}{'...' if len(comment) > 100 else ''}"

(Demo mode - atlassian-python-api not installed)"""
        
        if error:
            return error
        
        jira.issue_add_comment(issue_key, comment)
        
        return f"""✅ Comment added to {issue_key}
💬 "{comment[:100]}{'...' if len(comment) > 100 else ''}" """
            
    except Exception as e:
        return f"❌ Error adding comment: {str(e)}"


@tool("jira_transition_issue", args_schema=TransitionIssueInput)
def jira_transition_issue(issue_key: str, transition_name: str) -> str:
    """
    Transition a Jira issue to a different status.
    
    Use this when the user wants to move an issue to a different status like 'In Progress', 'Done', or 'To Do'.
    """
    try:
        jira, error = _get_jira_client()
        
        if error == "DEMO_MODE":
            return f"""✅ Transitioned {issue_key}
📍 Status changed to: {transition_name}

(Demo mode - atlassian-python-api not installed)"""
        
        if error:
            return error
        
        # Get available transitions
        transitions = jira.get_issue_transitions(issue_key)
        
        # Find matching transition
        transition_id = None
        available = []
        for t in transitions.get("transitions", []):
            available.append(t["name"])
            if t["name"].lower() == transition_name.lower():
                transition_id = t["id"]
                break
        
        if not transition_id:
            return f"❌ Transition '{transition_name}' not found.\nAvailable transitions: {', '.join(available)}"
        
        jira.issue_transition(issue_key, transition_id)
        
        return f"""✅ Transitioned {issue_key}
📍 Status changed to: {transition_name}"""
            
    except Exception as e:
        return f"❌ Error transitioning issue: {str(e)}"


@tool("jira_search_issues", args_schema=SearchIssuesInput)
def jira_search_issues(jql: str, max_results: int = 10) -> str:
    """
    Search for Jira issues using JQL (Jira Query Language).
    
    Use this when the user wants to find issues. JQL examples:
    - project = PROJ AND status = Open
    - assignee = currentUser() AND status != Done
    - text ~ "login bug"
    - created >= -7d ORDER BY priority DESC
    """
    try:
        jira, error = _get_jira_client()
        
        if error == "DEMO_MODE":
            return f"""📋 Search results for: {jql}

• [PROJ-123] Login page not loading - In Progress (High)
• [PROJ-124] Database connection timeout - Open (Critical)
• [PROJ-125] Update user documentation - Done (Low)

Found 3 issues (Demo mode)"""
        
        if error:
            return error
        
        max_results = min(max(1, max_results), 50)
        results = jira.jql(jql, limit=max_results)
        issues = results.get("issues", [])
        
        if not issues:
            return f"No issues found for: {jql}"
        
        output = f"📋 Found {len(issues)} issue(s):\n\n"
        for issue in issues:
            key = issue["key"]
            summary = issue["fields"]["summary"]
            status = issue["fields"]["status"]["name"]
            priority = issue["fields"].get("priority", {}).get("name", "None")
            output += f"• [{key}] {summary} - {status} ({priority})\n"
        
        return output
            
    except Exception as e:
        return f"❌ Error searching Jira: {str(e)}"


# ============================================================================
# PROJECT MANAGEMENT TOOLS
# ============================================================================

@tool("jira_create_project", args_schema=CreateProjectInput)
def jira_create_project(
    name: str,
    key: str,
    project_type: str = "software",
    lead_account_id: str = "",
    description: str = ""
) -> str:
    """
    Create a new Jira project.
    
    Use this when the user wants to create a new project in Jira.
    Project types: software, business, service_desk
    """
    try:
        jira, error = _get_jira_client()
        
        if error == "DEMO_MODE":
            return f"""✅ Created Jira project
📁 Name: {name}
🔑 Key: {key}
📋 Type: {project_type}

(Demo mode - atlassian-python-api not installed)"""
        
        if error:
            return error
        
        # Map project type to template key
        template_map = {
            "software": "com.pyxis.greenhopper.jira:gh-simplified-agility-scrum",
            "business": "com.atlassian.jira-core-project-templates:jira-core-simplified-project-management",
            "service_desk": "com.atlassian.servicedesk:simplified-it-service-desk"
        }
        
        project_data = {
            "key": key.upper(),
            "name": name,
            "projectTypeKey": project_type,
            "projectTemplateKey": template_map.get(project_type, template_map["software"]),
            "description": description
        }
        
        if lead_account_id:
            project_data["leadAccountId"] = lead_account_id
        
        result = jira.create_project(**project_data)
        
        return f"""✅ Created Jira project
📁 Name: {name}
🔑 Key: {key.upper()}
📋 Type: {project_type}
🔗 URL: {_jira_config.get('url', '')}/browse/{key.upper()}"""
            
    except Exception as e:
        return f"❌ Error creating project: {str(e)}"


@tool("jira_delete_project", args_schema=DeleteProjectInput)
def jira_delete_project(project_key: str, confirm: bool = False) -> str:
    """
    Delete a Jira project. REQUIRES confirm=true to proceed.
    
    ⚠️ WARNING: This permanently deletes the project and ALL its issues.
    Use this only when the user explicitly wants to delete a project.
    """
    try:
        if not confirm:
            return f"""⚠️ DELETE PROJECT CONFIRMATION REQUIRED

You are about to delete project: {project_key}
This action will permanently delete:
  • All issues in the project
  • All project configurations
  • All project history

To confirm deletion, call this tool again with confirm=true"""
        
        jira, error = _get_jira_client()
        
        if error == "DEMO_MODE":
            return f"""✅ Project {project_key} has been deleted.

(Demo mode - atlassian-python-api not installed)"""
        
        if error:
            return error
        
        jira.delete_project(project_key)
        
        return f"✅ Project {project_key} has been permanently deleted."
            
    except Exception as e:
        return f"❌ Error deleting project: {str(e)}"


# ============================================================================
# WORKFLOW MANAGEMENT TOOLS
# ============================================================================

@tool("jira_list_workflows")
def jira_list_workflows() -> str:
    """
    List available workflow schemes in Jira.
    
    Use this when the user wants to see available workflows or workflow schemes.
    """
    try:
        jira, error = _get_jira_client()
        
        if error == "DEMO_MODE":
            return """📋 Available Workflow Schemes:

• ID: 10001 - Default Software Workflow
  Description: Standard software development workflow
  
• ID: 10002 - Simplified Workflow
  Description: Basic To Do → In Progress → Done
  
• ID: 10003 - Bug Tracking Workflow
  Description: Specialized workflow for bug tracking

(Demo mode - atlassian-python-api not installed)"""
        
        if error:
            return error
        
        # Get workflow schemes
        import requests
        from requests.auth import HTTPBasicAuth
        
        url = f"{_jira_config.get('url')}/rest/api/3/workflowscheme"
        auth = HTTPBasicAuth(_jira_config.get("email", ""), _jira_config.get("api_token", ""))
        
        response = requests.get(url, auth=auth, headers={"Accept": "application/json"})
        
        if response.status_code != 200:
            return f"❌ Error fetching workflows: {response.status_code}"
        
        schemes = response.json().get("values", [])
        
        if not schemes:
            return "No workflow schemes found."
        
        output = "📋 Available Workflow Schemes:\n\n"
        for scheme in schemes:
            output += f"• ID: {scheme.get('id')} - {scheme.get('name')}\n"
            if scheme.get("description"):
                output += f"  Description: {scheme.get('description')}\n"
            output += "\n"
        
        return output
            
    except Exception as e:
        return f"❌ Error listing workflows: {str(e)}"


@tool("jira_assign_workflow", args_schema=AssignWorkflowInput)
def jira_assign_workflow(project_key: str, workflow_scheme_id: str) -> str:
    """
    Assign a workflow scheme to a project.
    
    Use this when the user wants to change or assign a workflow to a project.
    First use jira_list_workflows to get available workflow scheme IDs.
    """
    try:
        jira, error = _get_jira_client()
        
        if error == "DEMO_MODE":
            return f"""✅ Workflow scheme assigned
📁 Project: {project_key}
🔄 Workflow Scheme ID: {workflow_scheme_id}

(Demo mode - atlassian-python-api not installed)"""
        
        if error:
            return error
        
        import requests
        from requests.auth import HTTPBasicAuth
        
        url = f"{_jira_config.get('url')}/rest/api/3/workflowscheme/project"
        auth = HTTPBasicAuth(_jira_config.get("email", ""), _jira_config.get("api_token", ""))
        
        # First get project ID
        project = jira.project(project_key)
        project_id = project.get("id")
        
        payload = {
            "projectId": project_id,
            "workflowSchemeId": workflow_scheme_id
        }
        
        response = requests.put(url, json=payload, auth=auth, 
                               headers={"Content-Type": "application/json"})
        
        if response.status_code not in [200, 204]:
            return f"❌ Error assigning workflow: {response.text}"
        
        return f"""✅ Workflow scheme assigned
📁 Project: {project_key}
🔄 Workflow Scheme ID: {workflow_scheme_id}"""
            
    except Exception as e:
        return f"❌ Error assigning workflow: {str(e)}"


# ============================================================================
# PERMISSION MANAGEMENT TOOLS
# ============================================================================

@tool("jira_list_permission_schemes")
def jira_list_permission_schemes() -> str:
    """
    List available permission schemes in Jira.
    
    Use this when the user wants to see available permission schemes.
    """
    try:
        jira, error = _get_jira_client()
        
        if error == "DEMO_MODE":
            return """📋 Available Permission Schemes:

• ID: 10000 - Default Permission Scheme
  Description: Default permission configuration
  
• ID: 10001 - Restricted Access
  Description: Limited permissions for sensitive projects
  
• ID: 10002 - Open Project
  Description: More permissive settings for open projects

(Demo mode - atlassian-python-api not installed)"""
        
        if error:
            return error
        
        import requests
        from requests.auth import HTTPBasicAuth
        
        url = f"{_jira_config.get('url')}/rest/api/3/permissionscheme"
        auth = HTTPBasicAuth(_jira_config.get("email", ""), _jira_config.get("api_token", ""))
        
        response = requests.get(url, auth=auth, headers={"Accept": "application/json"})
        
        if response.status_code != 200:
            return f"❌ Error fetching permission schemes: {response.status_code}"
        
        schemes = response.json().get("permissionSchemes", [])
        
        if not schemes:
            return "No permission schemes found."
        
        output = "📋 Available Permission Schemes:\n\n"
        for scheme in schemes:
            output += f"• ID: {scheme.get('id')} - {scheme.get('name')}\n"
            if scheme.get("description"):
                output += f"  Description: {scheme.get('description')}\n"
            output += "\n"
        
        return output
            
    except Exception as e:
        return f"❌ Error listing permission schemes: {str(e)}"


@tool("jira_assign_permission_scheme", args_schema=AssignPermissionSchemeInput)
def jira_assign_permission_scheme(project_key: str, permission_scheme_id: str) -> str:
    """
    Assign a permission scheme to a project.
    
    Use this when the user wants to change the permissions for a project.
    First use jira_list_permission_schemes to get available scheme IDs.
    """
    try:
        jira, error = _get_jira_client()
        
        if error == "DEMO_MODE":
            return f"""✅ Permission scheme assigned
📁 Project: {project_key}
🔐 Permission Scheme ID: {permission_scheme_id}

(Demo mode - atlassian-python-api not installed)"""
        
        if error:
            return error
        
        import requests
        from requests.auth import HTTPBasicAuth
        
        # Get project ID first
        project = jira.project(project_key)
        project_id = project.get("id")
        
        url = f"{_jira_config.get('url')}/rest/api/3/project/{project_key}/permissionscheme"
        auth = HTTPBasicAuth(_jira_config.get("email", ""), _jira_config.get("api_token", ""))
        
        payload = {"id": permission_scheme_id}
        
        response = requests.put(url, json=payload, auth=auth,
                               headers={"Content-Type": "application/json"})
        
        if response.status_code not in [200, 204]:
            return f"❌ Error assigning permission scheme: {response.text}"
        
        return f"""✅ Permission scheme assigned
📁 Project: {project_key}
🔐 Permission Scheme ID: {permission_scheme_id}"""
            
    except Exception as e:
        return f"❌ Error assigning permission scheme: {str(e)}"


# ============================================================================
# TOOL EXPORT
# ============================================================================

def get_jira_tools(
    api_token: str,
    email: str = "",
    url: str = "",
    default_project_key: str = ""
) -> list[BaseTool]:
    """
    Get LangChain tools for Jira integration.

    Args:
        api_token: Jira API token
        email: User email for Jira Cloud
        url: Jira instance URL (e.g., https://company.atlassian.net)
        default_project_key: Project new issues land in when the user does not
            name one. Without it the model has to guess a key, and a wrong
            guess costs a failed round trip against the live API.

    Returns:
        List of Jira tools
    """
    _jira_config.set({
        "api_token": api_token,
        "email": email,
        "url": url,
        "default_project_key": (default_project_key or "").strip().upper(),
    })

    return [
        jira_list_projects,
        # Issue management
        jira_create_issue,
        jira_update_issue,
        jira_add_comment,
        jira_transition_issue,
        jira_search_issues,
        # Project management
        jira_create_project,
        jira_delete_project,
        # Workflow management
        jira_list_workflows,
        jira_assign_workflow,
        # Permission management
        jira_list_permission_schemes,
        jira_assign_permission_scheme,
    ]
