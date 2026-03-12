"""
Integration test demonstrating the new GitHub incident analysis functionality.
This test shows how the new methods would be used in practice.
"""

from backend.app.services.github import get_github_tools


def test_github_tools_integration():
    """Test that all GitHub tools are properly loaded and accessible."""
    # Get tools with a test token
    tools = get_github_tools("test_token")
    
    # Verify we have the expected number of tools
    assert len(tools) == 15
    
    # Verify the new incident analysis tools are included
    tool_names = [tool.name for tool in tools]
    
    # Check for new incident analysis tools
    assert "github_fetch_commits" in tool_names
    assert "github_fetch_pull_request" in tool_names
    assert "github_get_commit_metadata" in tool_names
    
    # Check for existing tools (to ensure we didn't break anything)
    assert "github_list_repos" in tool_names
    assert "github_create_issue" in tool_names
    assert "github_list_prs" in tool_names
    
    print("✅ All GitHub tools loaded successfully")
    print(f"📊 Total tools: {len(tools)}")
    print("🔧 New incident analysis tools:")
    for tool_name in ["github_fetch_commits", "github_fetch_pull_request", "github_get_commit_metadata"]:
        print(f"   - {tool_name}")


def test_tool_schemas():
    """Test that the new tools have proper input schemas."""
    tools = get_github_tools("test_token")
    
    # Find the new tools
    fetch_commits_tool = next(t for t in tools if t.name == "github_fetch_commits")
    fetch_pr_tool = next(t for t in tools if t.name == "github_fetch_pull_request")
    get_commit_tool = next(t for t in tools if t.name == "github_get_commit_metadata")
    
    # Check that they have the expected input fields
    assert hasattr(fetch_commits_tool, 'args_schema')
    assert hasattr(fetch_pr_tool, 'args_schema')
    assert hasattr(get_commit_tool, 'args_schema')
    
    # Check specific fields for fetch_commits
    fetch_commits_fields = fetch_commits_tool.args_schema.model_fields
    assert 'owner' in fetch_commits_fields
    assert 'repo' in fetch_commits_fields
    assert 'since' in fetch_commits_fields
    assert 'until' in fetch_commits_fields
    assert 'per_page' in fetch_commits_fields
    
    # Check specific fields for fetch_pull_request
    fetch_pr_fields = fetch_pr_tool.args_schema.model_fields
    assert 'owner' in fetch_pr_fields
    assert 'repo' in fetch_pr_fields
    assert 'pr_number' in fetch_pr_fields
    
    # Check specific fields for get_commit_metadata
    get_commit_fields = get_commit_tool.args_schema.model_fields
    assert 'owner' in get_commit_fields
    assert 'repo' in get_commit_fields
    assert 'sha' in get_commit_fields
    
    print("✅ All tool schemas are properly configured")


if __name__ == "__main__":
    test_github_tools_integration()
    test_tool_schemas()
    print("🎉 All integration tests passed!")