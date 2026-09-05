"""
Post-merge actions.

The transition guard is the safety-critical part: a misconfigured target status
must never drag a team's whole board backwards.
"""

import pytest

from app import schemas
from app.schemas import PRAnalysisResult
from app.services.pipeline import merge_actions
from app.services.pipeline.capabilities import build_readiness
from app.services.pipeline.merge_actions import is_forward_transition


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


class TestQABriefCarriesReviewerAsks:
    """
    The reviewer's requested changes must reach the testing team.

    A brief built only from the diff, the ticket and the security findings
    omitted the one requirement a human stated in plain words -- QA was told to
    verify the feature but not the change the reviewer explicitly asked for.
    """

    @staticmethod
    def _result():
        return PRAnalysisResult(
            context=schemas.PRContext(
                repo="acme/widget", pr_number=7, title="Restructure the page",
                author="dev", url="https://github.com/acme/widget/pull/7",
                files_changed=1,
            )
        )

    @pytest.mark.asyncio
    async def test_asks_are_given_to_the_model(self, monkeypatch):
        captured = {}

        class _LLM:
            async def ainvoke(self, prompt):
                captured["prompt"] = prompt
                return type("R", (), {"content": "- check it"})()

        monkeypatch.setattr(merge_actions, "get_llm", lambda **kw: _LLM())

        await merge_actions.draft_qa_brief(
            self._result(), ['add word "orange" too']
        )

        assert 'add word "orange" too' in captured["prompt"]

    @pytest.mark.asyncio
    async def test_asks_survive_an_unavailable_model(self, monkeypatch):
        """
        The fallback is where this matters most: no model to fold the asks
        into prose, so the brief must state them itself.
        """
        def _boom(**kw):
            raise RuntimeError("no model loaded")

        monkeypatch.setattr(merge_actions, "get_llm", _boom)

        brief = await merge_actions.draft_qa_brief(
            self._result(), ['add word "orange" too']
        )

        assert 'add word "orange" too' in brief

    @pytest.mark.asyncio
    async def test_no_asks_is_not_an_error(self, monkeypatch):
        def _boom(**kw):
            raise RuntimeError("no model loaded")

        monkeypatch.setattr(merge_actions, "get_llm", _boom)

        brief = await merge_actions.draft_qa_brief(self._result(), [])

        assert "(none)" in brief


class TestCloseDeferredToSignoff:
    """
    With close_on_qa_signoff set, the merge leaves the work item alone.

    The QA notification still goes out -- leaving the ticket open is the whole
    point, and someone has to be asked to close it.
    """

    @staticmethod
    def _result():
        return PRAnalysisResult(
            context=schemas.PRContext(
                repo="acme/widget", pr_number=7, title="Restructure",
                author="dev", url="https://github.com/acme/widget/pull/7",
                tickets=[schemas.RelatedTicket(key="LOC-1", summary="do it")],
                linked_issues=[schemas.LinkedIssue(
                    number=8, title="change name", relation="closes",
                    state="open",
                    url="https://github.com/acme/widget/issues/8",
                )],
            )
        )

    @pytest.fixture
    def spies(self, monkeypatch):
        calls = {"jira": [], "github": []}

        async def fake_jira(config, key, status):
            calls["jira"].append(key)
            return True, f"{key} moved"

        async def fake_gh(token, repo, number, pr_number):
            calls["github"].append(number)
            return True, f"Closed #{number}"

        monkeypatch.setattr(merge_actions, "transition_jira_ticket", fake_jira)
        monkeypatch.setattr(merge_actions, "close_github_issue", fake_gh)
        return calls

    @pytest.mark.asyncio
    async def test_merge_does_not_touch_the_work_item(self, spies):
        await merge_actions.run_merge_actions(
            self._result(),
            {"jira": {"api_key": "k"}, "github": {"api_key": "t"}},
            close_on_qa_signoff=True,
        )

        assert spies["jira"] == []
        assert spies["github"] == []

    @pytest.mark.asyncio
    async def test_merge_still_closes_when_not_deferred(self, spies):
        """The prior behaviour, unchanged for repos that have not opted in."""
        await merge_actions.run_merge_actions(
            self._result(),
            {"jira": {"api_key": "k"}, "github": {"api_key": "t"}},
            close_on_qa_signoff=False,
        )

        assert spies["jira"] == ["LOC-1"]
        assert spies["github"] == [8]


class TestReopenIsNotGatedOnClosing:
    """
    The reopen undoes GitHub's close, so it must not read `close_issues`.

    That setting says whether *Locus* closes an issue. GitHub closes it anyway
    on `Closes #N`, which the authoring driver always writes. Gated on both,
    the two most cautious settings on the form -- leave issues alone, and wait
    for a tester -- combined into the one outcome neither asks for: the ticket
    closed at merge and nothing reopened it.
    """

    @pytest.fixture
    def spies(self, monkeypatch):
        calls = {"closed": [], "reopened": []}

        async def fake_close(token, repo, number, pr_number):
            calls["closed"].append(number)
            return True, f"Closed #{number}"

        async def fake_reopen(token, repo, number, pr_number):
            calls["reopened"].append(number)
            return True, f"Reopened #{number}"

        monkeypatch.setattr(merge_actions, "close_github_issue", fake_close)
        monkeypatch.setattr(merge_actions, "reopen_for_qa", fake_reopen)
        return calls

    @pytest.mark.asyncio
    async def test_reopens_with_closing_off(self, spies):
        await merge_actions.run_merge_actions(
            TestCloseDeferredToSignoff._result(),
            {"github": {"api_key": "t"}},
            close_issues=False,
            close_on_qa_signoff=True,
        )

        assert spies["reopened"] == [8]
        assert spies["closed"] == []

    @pytest.mark.asyncio
    async def test_closing_off_without_deferral_touches_nothing(self, spies):
        """`close_issues=False` alone still means Locus leaves issues alone."""
        await merge_actions.run_merge_actions(
            TestCloseDeferredToSignoff._result(),
            {"github": {"api_key": "t"}},
            close_issues=False,
            close_on_qa_signoff=False,
        )

        assert spies["reopened"] == []
        assert spies["closed"] == []


class TestEmailDeliveryIsReportedHonestly:
    """
    A rejected QA email must not be recorded as delivered.

    `qa_notified` is set by whichever channel succeeded first, so a working
    Slack post made a Gmail 401 read as "sent" in the log and in the pipeline
    timeline. The email's own evidence is its message id, exactly as the Slack
    post's is its thread timestamp.
    """

    def test_a_rejected_send_returns_no_message_id(self):
        """
        The distinction the log needs. Gmail returns an id only when it
        accepted the message, so its absence is the failure signal.
        """
        outcome = schemas.MergeActionResult(
            qa_notified=True,          # set by the Slack post
            qa_thread_ts="1786803322.391159",
            qa_email_body="Ready to test ...",
            qa_email_to=["qa@example.com"],
            qa_email_message_id=None,  # Gmail rejected it
        )

        # What the comms row now records, rather than qa_notified.
        assert bool(outcome.qa_email_message_id) is False
        assert outcome.qa_notified is True

    def test_a_delivered_send_carries_its_id(self):
        outcome = schemas.MergeActionResult(
            qa_notified=True,
            qa_email_body="Ready to test ...",
            qa_email_message_id="<qa-acme-widget-7-abc@locus.local>",
        )

        assert bool(outcome.qa_email_message_id) is True

    @pytest.mark.asyncio
    async def test_a_401_is_reported_as_a_failure(self, monkeypatch):
        """Gmail rejecting the send must not return ok."""
        class _Response:
            status_code = 401
            text = "invalid credentials"

        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, *a, **kw):
                return _Response()

        monkeypatch.setattr(
            merge_actions.httpx, "AsyncClient", lambda **kw: _Client()
        )

        async def _token(*a, **kw):
            return "tok"

        monkeypatch.setattr(
            merge_actions.google_auth, "valid_access_token", _token
        )

        ok, detail, message_id, _body = await merge_actions.email_test_team(
            {"credentials": {"access_token": "tok"}},
            ["qa@example.com"],
            PRAnalysisResult(context=schemas.PRContext(
                repo="acme/widget", pr_number=7, title="t",
                author="d", url="u",
            )),
            "brief",
        )

        assert ok is False
        assert message_id is None
        assert "401" in detail
