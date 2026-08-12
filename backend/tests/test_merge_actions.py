"""
Post-merge actions.

The transition guard is the safety-critical part: a misconfigured target status
must never drag a team's whole board backwards.
"""

from app.services.capabilities import build_readiness
from app.services.merge_actions import is_forward_transition


class TestForwardOnlyTransitions:
    def test_allows_normal_progression(self):
        assert is_forward_transition("In Progress", "Done") is True
        assert is_forward_transition("To Do", "In Progress") is True
        assert is_forward_transition("In Review", "Done") is True

    def test_blocks_regression(self):
        """The failure this guard exists to prevent."""
        assert is_forward_transition("Done", "In Progress") is False
        assert is_forward_transition("Closed", "To Do") is False
        assert is_forward_transition("In Review", "In Progress") is False

    def test_allows_staying_at_same_stage(self):
        # Re-running on an already-merged PR must be a no-op, not an error.
        assert is_forward_transition("Done", "Closed") is True

    def test_unknown_statuses_pass_through(self):
        """
        Custom workflows are common. Refusing everything unrecognized would
        make the feature useless; what matters is blocking the recognizable
        regression.
        """
        assert is_forward_transition("Awaiting Signoff", "Done") is True
        assert is_forward_transition("In Progress", "Bespoke State") is True
        assert is_forward_transition(None, "Done") is True

    def test_case_and_whitespace_insensitive(self):
        assert is_forward_transition("  done  ", "In Progress") is False
        assert is_forward_transition("IN PROGRESS", "DONE") is True


class TestCapabilityReadiness:
    def test_github_is_required_and_others_are_not(self):
        services = {s.key: s for s in build_readiness({})}
        assert services["github"].required is True
        assert services["jira"].required is False

    def test_slack_search_separate_from_posting(self):
        """
        Search needs a user token while posting needs a bot token, so one can
        be available while the other is not.
        """
        services = {s.key: s for s in build_readiness({
            "slack": {"api_key": "xoxb-x", "credentials": {"bot_token": "xoxb-x"}}
        })}
        caps = {c.key: c for c in services["slack"].capabilities}

        assert caps["post"].available is True
        assert caps["search"].available is False
        assert services["slack"].connected is True
        assert services["slack"].fully_ready is False

    def test_slack_fully_ready_with_user_token(self):
        services = {s.key: s for s in build_readiness({
            "slack": {"credentials": {"bot_token": "xoxb-x", "user_token": "xoxp-y"}}
        })}
        assert services["slack"].fully_ready is True

    def test_github_capabilities_listed_individually(self):
        services = {s.key: s for s in build_readiness({"github": {"api_key": "ghp_x"}})}
        keys = {c.key for c in services["github"].capabilities}
        assert {"pull_requests", "issues", "comments"} <= keys

    def test_jira_lists_transition_capability(self):
        services = {s.key: s for s in build_readiness({
            "jira": {"api_key": "t", "credentials": {"url": "https://x.atlassian.net"}}
        })}
        keys = {c.key for c in services["jira"].capabilities}
        assert "transition" in keys
