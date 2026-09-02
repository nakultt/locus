"""
GitHub Integration Service
LangChain tools for GitHub repository, issue, and pull request management

Uses classic Personal Access Token (ghp_...) for authentication.
"""


import requests
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from app.core.credential_context import CredentialProxy

# Store credentials at module level for tool access
# Task-local so concurrent users cannot see each other's credentials.
# See app/services/credential_context.py.
_github_config = CredentialProxy("github")
GITHUB_API_BASE = "https://api.github.com"


# ============================================================================
# INPUT SCHEMAS
# ============================================================================

class ListReposInput(BaseModel):
    """Input schema for listing repositories."""
    visibility: str = Field(default="all", description="Filter by visibility: all, public, private")
    sort: str = Field(default="updated", description="Sort by: created, updated, pushed, full_name")
    per_page: int = Field(default=10, description="Number of repos to return (max 100)")


class GetRepoInput(BaseModel):
    """Input schema for getting a repository."""
    owner: str = Field(description="Repository owner (username or organization)")
    repo: str = Field(description="Repository name")


class CreateRepoInput(BaseModel):
    """Input schema for creating a repository."""
    name: str = Field(description="Repository name")
    description: str = Field(default="", description="Repository description")
    private: bool = Field(default=False, description="Whether the repo should be private")
    auto_init: bool = Field(default=True, description="Initialize with a README")


class ListIssuesInput(BaseModel):
    """Input schema for listing issues."""
    owner: str = Field(description="Repository owner")
    repo: str = Field(description="Repository name")
    state: str = Field(default="open", description="Filter by state: open, closed, all")
    per_page: int = Field(default=10, description="Number of issues to return (max 100)")


class CreateIssueInput(BaseModel):
    """Input schema for creating an issue."""
    owner: str = Field(description="Repository owner")
    repo: str = Field(description="Repository name")
    title: str = Field(description="Issue title")
    body: str = Field(default="", description="Issue body/description")
    labels: str = Field(default="", description="Comma-separated labels")


class UpdateIssueInput(BaseModel):
    """Input schema for updating an issue."""
    owner: str = Field(description="Repository owner")
    repo: str = Field(description="Repository name")
    issue_number: int = Field(description="Issue number to update")
    title: str = Field(default="", description="New title (leave empty to keep)")
    body: str = Field(default="", description="New body (leave empty to keep)")
    state: str = Field(default="", description="New state: open or closed")


class AddIssueCommentInput(BaseModel):
    """Input schema for adding issue comment."""
    owner: str = Field(description="Repository owner")
    repo: str = Field(description="Repository name")
    issue_number: int = Field(description="Issue number")
    body: str = Field(description="Comment body")


class ListPRsInput(BaseModel):
    """Input schema for listing pull requests."""
    owner: str = Field(description="Repository owner")
    repo: str = Field(description="Repository name")
    state: str = Field(default="open", description="Filter by state: open, closed, all")
    per_page: int = Field(default=10, description="Number of PRs to return")


class CreatePRInput(BaseModel):
    """Input schema for creating a pull request."""
    owner: str = Field(description="Repository owner")
    repo: str = Field(description="Repository name")
    title: str = Field(description="Pull request title")
    head: str = Field(description="Branch containing changes (e.g., 'feature-branch')")
    base: str = Field(default="main", description="Branch to merge into")
    body: str = Field(default="", description="Pull request description")


class MergePRInput(BaseModel):
    """Input schema for merging a pull request."""
    owner: str = Field(description="Repository owner")
    repo: str = Field(description="Repository name")
    pull_number: int = Field(description="Pull request number")
    commit_title: str = Field(default="", description="Title for merge commit")
    merge_method: str = Field(default="merge", description="Merge method: merge, squash, rebase")


class AddPRCommentInput(BaseModel):
    """Input schema for adding PR comment."""
    owner: str = Field(description="Repository owner")
    repo: str = Field(description="Repository name")
    pull_number: int = Field(description="Pull request number")
    body: str = Field(description="Comment body")


# ============================================================================
# HELPER FUNCTION
# ============================================================================

def _get_headers():
    """Get GitHub API headers with authentication."""
    token = _github_config.get("token", "")
    if not token:
        return None, "Error: GitHub is not configured. Please connect your GitHub account first."
    
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }, None


def _make_request(method: str, endpoint: str, json_data: dict = None, params: dict = None):
    """Make a request to the GitHub API."""
    headers, error = _get_headers()
    if error:
        return None, error
    
    url = f"{GITHUB_API_BASE}{endpoint}"
    
    try:
        response = requests.request(
            method=method,
            url=url,
            headers=headers,
            json=json_data,
            params=params
        )
        
        if response.status_code >= 400:
            error_msg = response.json().get("message", response.text)
            return None, f"GitHub API Error ({response.status_code}): {error_msg}"
        
        if response.status_code == 204:
            return {}, None
        
        return response.json(), None
    except Exception as e:
        return None, f"Request failed: {str(e)}"


# ============================================================================
# REPOSITORY TOOLS
# ============================================================================

@tool("github_list_repos", args_schema=ListReposInput)
def github_list_repos(
    visibility: str = "all",
    sort: str = "updated",
    per_page: int = 10
) -> str:
    """
    List repositories for the authenticated user.
    
    Use this when the user wants to see their GitHub repositories.
    """
    params = {
        "visibility": visibility,
        "sort": sort,
        "per_page": min(per_page, 100)
    }
    
    data, error = _make_request("GET", "/user/repos", params=params)
    if error:
        return f"❌ {error}"
    
    if not data:
        return "📁 No repositories found."
    
    output = f"📁 Found {len(data)} repositories:\n\n"
    for repo in data:
        visibility_icon = "🔒" if repo.get("private") else "🌐"
        stars = repo.get("stargazers_count", 0)
        output += f"• {visibility_icon} **{repo['full_name']}**"
        if stars > 0:
            output += f" ⭐{stars}"
        # A repo with no description comes back as an explicit null, so the
        # `.get` default never fires -- guard the value, not the key.
        description = repo.get("description") or "No description"
        output += f"\n  {description[:60]}\n"
    
    return output


@tool("github_get_repo", args_schema=GetRepoInput)
def github_get_repo(owner: str, repo: str) -> str:
    """
    Get details about a specific repository.
    
    Use this when the user wants information about a particular repo.
    """
    data, error = _make_request("GET", f"/repos/{owner}/{repo}")
    if error:
        return f"❌ {error}"
    
    visibility = "Private" if data.get("private") else "Public"
    
    return f"""📁 Repository: **{data['full_name']}**

📝 Description: {data.get('description') or 'No description'}
🔒 Visibility: {visibility}
⭐ Stars: {data.get('stargazers_count', 0)}
🍴 Forks: {data.get('forks_count', 0)}
👁️ Watchers: {data.get('watchers_count', 0)}
🌿 Default Branch: {data.get('default_branch', 'main')}
🔗 URL: {data.get('html_url')}
📅 Created: {data.get('created_at', 'Unknown')[:10]}
📅 Updated: {data.get('updated_at', 'Unknown')[:10]}"""


@tool("github_create_repo", args_schema=CreateRepoInput)
def github_create_repo(
    name: str,
    description: str = "",
    private: bool = False,
    auto_init: bool = True
) -> str:
    """
    Create a new GitHub repository.
    
    Use this when the user wants to create a new repo.
    """
    payload = {
        "name": name,
        "description": description,
        "private": private,
        "auto_init": auto_init
    }
    
    data, error = _make_request("POST", "/user/repos", json_data=payload)
    if error:
        return f"❌ {error}"
    
    visibility = "Private" if private else "Public"
    
    return f"""✅ Created repository: **{data['full_name']}**

🔒 Visibility: {visibility}
🔗 URL: {data.get('html_url')}
📝 Clone: `git clone {data.get('clone_url')}`"""


# ============================================================================
# ISSUE TOOLS
# ============================================================================

@tool("github_list_issues", args_schema=ListIssuesInput)
def github_list_issues(
    owner: str,
    repo: str,
    state: str = "open",
    per_page: int = 10
) -> str:
    """
    List issues in a repository.
    
    Use this when the user wants to see issues in a repo.
    """
    params = {
        "state": state,
        "per_page": min(per_page, 100)
    }
    
    data, error = _make_request("GET", f"/repos/{owner}/{repo}/issues", params=params)
    if error:
        return f"❌ {error}"
    
    # Filter out pull requests (GitHub API returns PRs as issues too)
    issues = [i for i in data if "pull_request" not in i]
    
    if not issues:
        return f"📋 No {state} issues in {owner}/{repo}."
    
    output = f"📋 Issues in **{owner}/{repo}** ({state}):\n\n"
    for issue in issues:
        labels = ", ".join([l["name"] for l in issue.get("labels", [])])
        label_str = f" [{labels}]" if labels else ""
        output += f"• **#{issue['number']}** {issue['title']}{label_str}\n"
        output += f"  👤 {issue.get('user', {}).get('login', 'Unknown')} • 💬 {issue.get('comments', 0)} comments\n"
    
    return output


@tool("github_create_issue", args_schema=CreateIssueInput)
def github_create_issue(
    owner: str,
    repo: str,
    title: str,
    body: str = "",
    labels: str = ""
) -> str:
    """
    Create a new issue in a repository.
    
    Use this when the user wants to create a bug report, feature request, or task.
    """
    payload = {
        "title": title,
        "body": body
    }
    
    if labels:
        payload["labels"] = [l.strip() for l in labels.split(",")]
    
    data, error = _make_request("POST", f"/repos/{owner}/{repo}/issues", json_data=payload)
    if error:
        return f"❌ {error}"
    
    return f"""✅ Created issue in **{owner}/{repo}**

🔢 Issue: **#{data['number']}**
📝 Title: {data['title']}
🔗 URL: {data.get('html_url')}"""


@tool("github_update_issue", args_schema=UpdateIssueInput)
def github_update_issue(
    owner: str,
    repo: str,
    issue_number: int,
    title: str = "",
    body: str = "",
    state: str = ""
) -> str:
    """
    Update an existing issue.
    
    Use this when the user wants to modify issue title, body, or close/reopen it.
    """
    payload = {}
    if title:
        payload["title"] = title
    if body:
        payload["body"] = body
    if state in ["open", "closed"]:
        payload["state"] = state
    
    if not payload:
        return "⚠️ No updates specified. Provide title, body, or state."
    
    data, error = _make_request("PATCH", f"/repos/{owner}/{repo}/issues/{issue_number}", json_data=payload)
    if error:
        return f"❌ {error}"
    
    return f"""✅ Updated issue **#{issue_number}** in {owner}/{repo}

📝 Title: {data['title']}
📊 State: {data['state']}
🔗 URL: {data.get('html_url')}"""


@tool("github_add_issue_comment", args_schema=AddIssueCommentInput)
def github_add_issue_comment(
    owner: str,
    repo: str,
    issue_number: int,
    body: str
) -> str:
    """
    Add a comment to an issue.
    
    Use this when the user wants to comment on an issue.
    """
    payload = {"body": body}
    
    data, error = _make_request("POST", f"/repos/{owner}/{repo}/issues/{issue_number}/comments", json_data=payload)
    if error:
        return f"❌ {error}"
    
    return f"""✅ Added comment to issue **#{issue_number}**

💬 "{body[:100]}{'...' if len(body) > 100 else ''}"
🔗 URL: {data.get('html_url')}"""


# ============================================================================
# PULL REQUEST TOOLS
# ============================================================================

@tool("github_list_prs", args_schema=ListPRsInput)
def github_list_prs(
    owner: str,
    repo: str,
    state: str = "open",
    per_page: int = 10
) -> str:
    """
    List pull requests in a repository.
    
    Use this when the user wants to see PRs in a repo.
    """
    params = {
        "state": state,
        "per_page": min(per_page, 100)
    }
    
    data, error = _make_request("GET", f"/repos/{owner}/{repo}/pulls", params=params)
    if error:
        return f"❌ {error}"
    
    if not data:
        return f"🔀 No {state} pull requests in {owner}/{repo}."
    
    output = f"🔀 Pull Requests in **{owner}/{repo}** ({state}):\n\n"
    for pr in data:
        output += f"• **#{pr['number']}** {pr['title']}\n"
        output += f"  🌿 {pr['head']['ref']} → {pr['base']['ref']} • 👤 {pr.get('user', {}).get('login', 'Unknown')}\n"
    
    return output


@tool("github_create_pr", args_schema=CreatePRInput)
def github_create_pr(
    owner: str,
    repo: str,
    title: str,
    head: str,
    base: str = "main",
    body: str = ""
) -> str:
    """
    Create a new pull request.
    
    Use this when the user wants to create a PR to merge changes.
    """
    payload = {
        "title": title,
        "head": head,
        "base": base,
        "body": body
    }
    
    data, error = _make_request("POST", f"/repos/{owner}/{repo}/pulls", json_data=payload)
    if error:
        return f"❌ {error}"
    
    return f"""✅ Created pull request in **{owner}/{repo}**

🔢 PR: **#{data['number']}**
📝 Title: {data['title']}
🌿 {head} → {base}
🔗 URL: {data.get('html_url')}"""


@tool("github_merge_pr", args_schema=MergePRInput)
def github_merge_pr(
    owner: str,
    repo: str,
    pull_number: int,
    commit_title: str = "",
    merge_method: str = "merge"
) -> str:
    """
    Merge a pull request.
    
    Use this when the user wants to merge a PR. Merge methods: merge, squash, rebase.
    """
    payload = {"merge_method": merge_method}
    if commit_title:
        payload["commit_title"] = commit_title
    
    data, error = _make_request("PUT", f"/repos/{owner}/{repo}/pulls/{pull_number}/merge", json_data=payload)
    if error:
        return f"❌ {error}"
    
    return f"""✅ Merged PR **#{pull_number}** in {owner}/{repo}

📝 Message: {data.get('message', 'Pull request merged successfully')}
🔀 Method: {merge_method}"""


@tool("github_add_pr_comment", args_schema=AddPRCommentInput)
def github_add_pr_comment(
    owner: str,
    repo: str,
    pull_number: int,
    body: str
) -> str:
    """
    Add a comment to a pull request.
    
    Use this when the user wants to comment on a PR.
    """
    # PR comments use the issues endpoint
    payload = {"body": body}
    
    data, error = _make_request("POST", f"/repos/{owner}/{repo}/issues/{pull_number}/comments", json_data=payload)
    if error:
        return f"❌ {error}"
    
    return f"""✅ Added comment to PR **#{pull_number}**

💬 "{body[:100]}{'...' if len(body) > 100 else ''}"
🔗 URL: {data.get('html_url')}"""


# ============================================================================
# USER TOOLS
# ============================================================================

@tool("github_get_user")
def github_get_user() -> str:
    """
    Get the authenticated user's profile.
    
    Use this when the user wants to see their GitHub profile info.
    """
    data, error = _make_request("GET", "/user")
    if error:
        return f"❌ {error}"
    
    return f"""👤 GitHub User: **{data.get('login')}**

📛 Name: {data.get('name') or 'Not set'}
📧 Email: {data.get('email') or 'Not public'}
📍 Location: {data.get('location') or 'Not set'}
🏢 Company: {data.get('company') or 'Not set'}
📁 Public Repos: {data.get('public_repos', 0)}
👥 Followers: {data.get('followers', 0)} | Following: {data.get('following', 0)}
🔗 URL: {data.get('html_url')}"""


# ============================================================================
# TOOL EXPORT
# ============================================================================

def get_github_tools(token: str) -> list[BaseTool]:
    """
    Get LangChain tools for GitHub integration.
    
    Args:
        token: GitHub Personal Access Token (classic)
        
    Returns:
        List of GitHub tools
    """
    _github_config.set({"token": token})
    
    return [
        # Repository tools
        github_list_repos,
        github_get_repo,
        github_create_repo,
        # Issue tools
        github_list_issues,
        github_create_issue,
        github_update_issue,
        github_add_issue_comment,
        # Pull request tools
        github_list_prs,
        github_create_pr,
        github_merge_pr,
        github_add_pr_comment,
        # User tools
        github_get_user,
    ]
