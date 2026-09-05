"""
The agent runtime is a setting, not a deployment constant.

The driver, the model, the invocation template, the context mode, the diff
bounds, the commit identity, the source and workspace roots and the calendar
dials were environment variables -- one operator's answer for every tenant.
These pin the three-layer resolution that replaced them (account, then
environment, then the code's constant) and the two rules that make letting a
user supply a filesystem path safe.
"""

import pytest

from app.services.authoring import agent_runtime, workspace


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    """No account bound and no deployment variables set unless a test says so."""
    for name in (
        "LOCUS_AUTHORING_DRIVER",
        "LOCUS_OPENCODE_MODEL",
        "LOCUS_OPENCODE_CMD",
        "LOCUS_AUTHORING_CONTEXT",
        "LOCUS_AUTHORING_TIMEOUT_SECONDS",
        "LOCUS_MAX_CHANGED_FILES",
        "LOCUS_MAX_CHANGED_LINES",
        "LOCUS_MAX_OPEN_AUTONOMOUS_PRS",
        "LOCUS_AGENT_NAME",
        "LOCUS_AGENT_EMAIL",
        "LOCUS_CODE_ROOT",
        "LOCUS_WORKSPACE_ROOT",
        "LOCUS_ALLOW_IN_PLACE",
        "LOCUS_WORKSPACE_TTL_DAYS",
        "LOCUS_CALENDAR_SWEEP_MINUTES",
        "LOCUS_CALENDAR_LOOKAHEAD_DAYS",
        "LOCUS_AUTHORING_PR_REVIEWERS",
    ):
        monkeypatch.delenv(name, raising=False)

    agent_runtime.clear()
    yield
    agent_runtime.clear()


def _bind(**kwargs):
    agent_runtime.bind(agent_runtime.AgentRuntime(**kwargs))


class TestResolutionOrder:
    def test_nothing_configured_uses_the_constants(self):
        assert agent_runtime.driver_name() == "none"
        assert agent_runtime.context_mode() == "full"
        assert agent_runtime.max_open_prs() == agent_runtime.DEFAULT_MAX_OPEN_PRS
        assert agent_runtime.agent_email() == agent_runtime.DEFAULT_AGENT_EMAIL

    def test_the_environment_is_the_deployment_default(self, monkeypatch):
        monkeypatch.setenv("LOCUS_AUTHORING_DRIVER", "opencode")
        monkeypatch.setenv("LOCUS_MAX_CHANGED_FILES", "9")

        assert agent_runtime.driver_name() == "opencode"
        assert agent_runtime.max_changed_files() == 9

    def test_an_account_beats_the_environment(self, monkeypatch):
        monkeypatch.setenv("LOCUS_MAX_CHANGED_FILES", "9")
        monkeypatch.setenv("LOCUS_AUTHORING_CONTEXT", "full")
        _bind(max_changed_files=3, context_mode="ticket_only")

        assert agent_runtime.max_changed_files() == 3
        assert agent_runtime.context_mode() == "ticket_only"

    def test_a_blank_field_inherits_rather_than_overriding(self, monkeypatch):
        """Setting only the model must not blank the command template."""
        monkeypatch.setenv("LOCUS_OPENCODE_CMD", "deployment-agent {prompt}")
        _bind(model="pinned-model-1")

        assert agent_runtime.model() == "pinned-model-1"
        assert agent_runtime.command("fallback") == "deployment-agent {prompt}"

    def test_the_callers_constant_is_the_last_layer(self):
        """
        The module constant *is* the deployment default, so it is passed in
        rather than copied here -- one setting with two defaults would drift.
        """
        assert agent_runtime.max_changed_files(77) == 77
        assert agent_runtime.timeout_seconds(45) == 45


class TestSafety:
    def test_an_unknown_driver_never_runs_a_shell(self):
        """
        A typo must resolve to the do-nothing driver, not to opencode.

        Guessing here would start a subprocess in a checkout on the strength
        of a misspelling.
        """
        _bind(driver="opencde")
        assert agent_runtime.driver_name() == "none"

    def test_an_unknown_context_mode_keeps_the_safe_answer(self):
        _bind(context_mode="everything")
        assert agent_runtime.context_mode() == "full"

    def test_a_malformed_number_is_absent_not_zero(self):
        """
        A timeout of zero kills every attempt instantly; a file cap of zero
        refuses every diff. A value that will not parse must fall through.
        """
        assert agent_runtime._int("not-a-number") is None
        assert agent_runtime.timeout_seconds(600) == 600

    def test_allow_in_place_is_three_states(self, monkeypatch):
        """
        Unset inherits; False is a real choice that must beat a deployment
        default of on, or an account could never turn it off.
        """
        monkeypatch.setenv("LOCUS_ALLOW_IN_PLACE", "1")

        _bind()
        assert agent_runtime.allow_in_place() is True

        _bind(allow_in_place=False)
        assert agent_runtime.allow_in_place() is False

    def test_a_user_supplied_code_root_is_still_refused_if_it_is_locus(self):
        """
        The whole reason this is safe to let a user set.

        `check_not_locus` compares the resolved path against Locus's own tree
        in both directions and never consulted where the value came from, so
        an account pointing its root at the tree holding ENCRYPTION_KEY gets
        the same named configuration error the environment variable produced.
        """
        _bind(code_root=str(workspace.locus_root()))

        with pytest.raises(workspace.WorkspaceError):
            workspace.check_not_locus(workspace.locus_root())

    def test_the_workspace_root_follows_the_account(self, tmp_path):
        _bind(workspace_root=str(tmp_path / "agent-trees"))
        assert workspace.workspace_root() == tmp_path / "agent-trees"


class TestIsolation:
    def test_the_runtime_is_task_local(self):
        """
        A module-level dict would let two accounts' authoring runs overwrite
        each other's source root, pointing one agent at the other's code --
        the bug `credential_context` exists to prevent, one layer along.
        """
        import asyncio

        async def run(root: str) -> str:
            _bind(code_root=root)
            await asyncio.sleep(0)
            return agent_runtime.code_root()

        async def both():
            return await asyncio.gather(run("/one"), run("/two"))

        assert asyncio.run(both()) == ["/one", "/two"]


class TestDescribe:
    def test_every_resolved_value_is_reported(self):
        described = agent_runtime.describe()
        assert described["driver"] == "none"
        assert described["max_open_prs"] == agent_runtime.DEFAULT_MAX_OPEN_PRS
        assert described["calendar_lookahead_days"] == 14
        # Paths and bounds, not secrets: the values themselves are returned,
        # unlike the model backend's API key.
        assert set(described) >= {"code_root", "workspace_root", "agent_email"}


class TestPRReviewers:
    """
    Who GitHub is asked to review the pull requests the agent opens.

    Empty is the meaningful default: a review request is a notification the
    recipient cannot undo, so this must never resolve to somebody nobody
    named -- which is why the list above it, `settings.reviewers`, is not
    reused here.
    """

    def test_nobody_is_requested_unless_an_account_says_so(self):
        assert agent_runtime.pr_reviewers() == []

    def test_logins_are_read_however_they_were_typed(self):
        _bind(pr_reviewers="@senior-dev\ntech-lead, @qa-lead\n\n")
        assert agent_runtime.pr_reviewers() == ["senior-dev", "tech-lead", "qa-lead"]

    def test_a_repeated_login_is_requested_once(self):
        """
        GitHub takes the whole list in one call and rejects the whole of it if
        an entry is bad, so a login written twice must not become two entries.
        """
        _bind(pr_reviewers="senior-dev\nSenior-Dev")
        assert agent_runtime.pr_reviewers() == ["senior-dev"]

    def test_an_account_beats_the_deployment(self, monkeypatch):
        monkeypatch.setenv("LOCUS_AUTHORING_PR_REVIEWERS", "deployment-wide")

        assert agent_runtime.pr_reviewers() == ["deployment-wide"]

        _bind(pr_reviewers="ours")
        assert agent_runtime.pr_reviewers() == ["ours"]

    def test_it_is_reported_with_the_rest_of_the_runtime(self):
        _bind(pr_reviewers="senior-dev")
        assert agent_runtime.describe()["pr_reviewers"] == ["senior-dev"]
