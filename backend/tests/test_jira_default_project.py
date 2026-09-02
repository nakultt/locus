"""
Default Jira project resolution.

Without a configured default the model has to guess a project key, and a wrong
guess costs a failed round trip against the live API before anyone finds out.
These tests pin the three paths: explicit key wins, default fills the gap, and
neither one present produces the real project list rather than a guess.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.services.integrations import jira


@pytest.fixture
def client():
    """A stubbed atlassian client, with the credential context populated."""
    fake = MagicMock()
    fake.create_issue.return_value = {"key": "KAN-1"}
    fake.projects.return_value = [
        {"key": "KAN", "name": "Kanban Board"},
        {"key": "OPS", "name": "Operations"},
    ]
    with patch.object(jira, "_get_jira_client", return_value=(fake, None)):
        yield fake


def configure(default_project_key: str = "") -> None:
    jira._jira_config.set({
        "api_token": "t",
        "email": "e@x.com",
        "url": "https://x.atlassian.net",
        "default_project_key": default_project_key,
    })


class TestCreateIssue:
    def test_explicit_key_is_used_over_the_default(self, client):
        configure("KAN")
        jira.jira_create_issue.invoke({"summary": "S", "project_key": "OPS"})

        fields = client.create_issue.call_args.kwargs["fields"]
        assert fields["project"]["key"] == "OPS"

    def test_default_fills_in_an_omitted_key(self, client):
        configure("KAN")
        output = jira.jira_create_issue.invoke({"summary": "Example Ticket"})

        fields = client.create_issue.call_args.kwargs["fields"]
        assert fields["project"]["key"] == "KAN"
        assert "KAN-1" in output

    def test_key_is_normalised_to_uppercase(self, client):
        configure("kan")
        jira.jira_create_issue.invoke({"summary": "S"})

        assert client.create_issue.call_args.kwargs["fields"]["project"]["key"] == "KAN"

    def test_no_key_and_no_default_lists_real_projects(self, client):
        """
        The failure mode this replaces: the model invented 'PROJ' and only
        found out it was wrong from the API. Hand it the real keys instead.
        """
        configure("")
        output = jira.jira_create_issue.invoke({"summary": "S"})

        assert client.create_issue.call_count == 0
        assert "KAN" in output and "OPS" in output
        assert "Kanban Board" in output


class TestListProjects:
    def test_lists_keys_and_marks_the_default(self, client):
        configure("OPS")
        output = jira.jira_list_projects.invoke({})

        assert "KAN" in output and "OPS" in output
        assert "(default)" in output
        # Only the configured one is marked.
        assert output.count("(default)") == 1

    def test_handles_a_paginated_server_response(self, client):
        """Jira Server returns {"values": [...]} where Cloud returns a list."""
        configure()
        client.projects.return_value = {"values": [{"key": "A", "name": "Alpha"}]}

        assert "Alpha" in jira.jira_list_projects.invoke({})

    def test_empty_instance(self, client):
        configure()
        client.projects.return_value = []

        assert "No projects" in jira.jira_list_projects.invoke({})


class TestToolRegistration:
    def test_list_projects_is_exposed_to_the_agent(self):
        names = {
            t.name for t in jira.get_jira_tools("token", "e@x.com", "https://x")
        }
        assert "jira_list_projects" in names

    def test_default_project_reaches_the_config(self):
        jira.get_jira_tools("token", "e@x.com", "https://x", default_project_key=" kan ")
        assert jira._jira_config.get("default_project_key") == "KAN"
