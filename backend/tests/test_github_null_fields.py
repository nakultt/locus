"""
Nullable fields in third-party API responses.

These APIs return an explicit `null` rather than omitting a key, so a
`dict.get(key, default)` default never fires -- the key exists, its value is
just None. Every case here crashed with "'NoneType' object is not
subscriptable" before the guard was added.
"""

from unittest.mock import patch

from app.services.integrations import github, linear


class TestListReposDescription:
    def test_repo_without_a_description_renders(self):
        """GitHub sends `"description": null` for a repo with none set."""
        payload = [
            {
                "full_name": "nakultt/locus",
                "private": True,
                "stargazers_count": 3,
                "description": None,
            },
            {
                "full_name": "nakultt/other",
                "private": False,
                "stargazers_count": 0,
                "description": "A described repo",
            },
        ]

        with patch.object(github, "_make_request", return_value=(payload, None)):
            output = github.github_list_repos.invoke({})

        assert "No description" in output
        assert "A described repo" in output
        # The null repo must not swallow the ones after it.
        assert "nakultt/locus" in output
        assert "nakultt/other" in output

    def test_long_description_is_still_truncated(self):
        payload = [{
            "full_name": "a/b", "private": False,
            "stargazers_count": 0, "description": "x" * 200,
        }]

        with patch.object(github, "_make_request", return_value=(payload, None)):
            output = github.github_list_repos.invoke({})

        assert "x" * 60 in output
        assert "x" * 61 not in output


class TestLinearIssueDetail:
    def test_null_relations_and_comment_authors(self):
        """
        Linear's GraphQL nulls out every unset relation: an issue in no
        project, on no team, with a comment posted by an integration.
        """
        issue = {
            "identifier": "LOC-1",
            "title": "Thing",
            "priority": 2,
            "assignee": None,
            "state": None,
            "team": None,
            "project": None,
            "labels": None,
            "url": "https://linear.app/x/LOC-1",
            "comments": {"nodes": [
                {"user": None, "body": "Posted by a bot"},
                {"user": {"name": "Nakul"}, "body": None},
            ]},
        }

        with patch.object(
            linear, "_execute_query", return_value=({"issue": issue}, None)
        ):
            output = linear.linear_get_issue.invoke({"issue_id": "LOC-1"})

        assert "Unassigned" in output
        assert "Unknown" in output          # the null state, and the bot author
        assert "Posted by a bot" in output
        assert "Nakul" in output

    def test_a_null_comments_connection_renders(self):
        """
        Regression: `labels` was guarded with `or {}` and `comments` was not,
        though both are connections GraphQL nulls the same way. The issue
        detail crashed instead of rendering.
        """
        issue = {
            "identifier": "LOC-2",
            "title": "No comments",
            "priority": 1,
            "assignee": None,
            "state": None,
            "team": None,
            "project": None,
            "labels": None,
            "comments": None,
            "url": "https://linear.app/x/LOC-2",
        }

        with patch.object(
            linear, "_execute_query", return_value=({"issue": issue}, None)
        ):
            output = linear.linear_get_issue.invoke({"issue_id": "LOC-2"})

        assert "LOC-2" in output
        assert "No comments" in output


class TestLinearNullConnections:
    """
    A partial GraphQL error resolves the data it could and nulls the rest, so
    a top-level connection can arrive as None on an otherwise-successful
    response. Each of these crashed on the `.get(key, {})` form.
    """

    def test_null_teams_connection(self):
        with patch.object(
            linear, "_execute_query", return_value=({"teams": None}, None)
        ):
            output = linear.linear_list_teams.invoke({})

        assert "No teams found" in output

    def test_null_issues_connection(self):
        with patch.object(
            linear, "_execute_query", return_value=({"issues": None}, None)
        ):
            output = linear.linear_list_issues.invoke({})

        assert "No issues found" in output

    def test_null_states_connection(self):
        with patch.object(
            linear,
            "_execute_query",
            return_value=({"team": {"name": "Core", "states": None}}, None),
        ):
            output = linear.linear_list_states.invoke({"team_id": "t"})

        assert "No workflow states" in output
