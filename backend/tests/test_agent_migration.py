"""
Agent behaviour on LangChain 1.x.

LangChain 1.0 removed AgentExecutor; `create_agent` returns a compiled LangGraph
and the invoke contract changed from {"input"} -> {"output", "intermediate_steps"}
to messages in / messages out. These tests pin the translation between that
message list and the ActionResult objects the UI renders.
"""

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool

from app.services import agent as agent_module
from app.services.agent import (
    MAX_AGENT_ITERATIONS,
    create_agent_executor,
    extract_actions,
    final_text,
)


@tool
def slack_send_message(channel: str, message: str) -> str:
    """Send a Slack message."""
    return "Message sent to #dev"


@tool
def jira_create_issue(summary: str) -> str:
    """Create a Jira issue."""
    raise RuntimeError("Jira auth failed")


class FakeModel(GenericFakeChatModel):
    """Fake chat model that accepts bind_tools so create_agent can use it."""

    def bind_tools(self, tools, **kwargs):
        return self


def scripted(*messages) -> FakeModel:
    return FakeModel(messages=iter(messages))


class TestMessageExtraction:
    def test_extracts_tool_calls_with_results(self):
        messages = [
            HumanMessage(content="do it"),
            AIMessage(content="", tool_calls=[
                {"name": "slack_send_message", "args": {}, "id": "c1"},
            ]),
            ToolMessage(content="Message sent", tool_call_id="c1", name="slack_send_message"),
            AIMessage(content="Done."),
        ]
        actions = extract_actions(messages)
        assert len(actions) == 1
        assert actions[0].service == "slack"
        assert actions[0].success is True
        assert actions[0].result == "Message sent"

    def test_error_status_marks_action_failed(self):
        """
        Failure is read from ToolMessage.status, not by sniffing the string for
        the word "error" -- the previous heuristic only checked the first 50
        characters and misclassified anything past it.
        """
        messages = [
            AIMessage(content="", tool_calls=[
                {"name": "jira_create_issue", "args": {}, "id": "c1"},
            ]),
            ToolMessage(
                content="A" * 80 + " error happened",
                tool_call_id="c1",
                name="jira_create_issue",
                status="error",
            ),
        ]
        actions = extract_actions(messages)
        assert actions[0].success is False
        assert actions[0].error is not None
        assert actions[0].result is None

    def test_final_text_returns_last_assistant_message(self):
        messages = [
            AIMessage(content="thinking"),
            ToolMessage(content="x", tool_call_id="c1", name="t"),
            AIMessage(content="Final answer."),
        ]
        assert final_text(messages) == "Final answer."

    def test_final_text_handles_block_content(self):
        messages = [AIMessage(content=[{"type": "text", "text": "Hello"}])]
        assert final_text(messages) == "Hello"

    def test_no_messages_yields_empty_string(self):
        assert final_text([]) == ""


class TestToolErrorHandling:
    @pytest.mark.asyncio
    async def test_tool_exception_becomes_failed_action_not_a_crash(self, monkeypatch):
        """
        A request touching several integrations must not lose the ones that
        succeeded because a later tool raised.
        """
        monkeypatch.setattr(
            agent_module, "get_llm",
            lambda **kw: scripted(
                AIMessage(content="", tool_calls=[
                    {"name": "slack_send_message",
                     "args": {"channel": "dev", "message": "x"}, "id": "c1"},
                    {"name": "jira_create_issue", "args": {"summary": "b"}, "id": "c2"},
                ]),
                AIMessage(content="Slack posted; Jira failed."),
            ),
        )

        agent = create_agent_executor([slack_send_message, jira_create_issue])
        result = await agent.ainvoke(
            {"messages": [HumanMessage(content="do both")]},
            config={"recursion_limit": MAX_AGENT_ITERATIONS * 2},
        )

        actions = extract_actions(result["messages"])
        assert len(actions) == 2

        by_name = {a.action: a for a in actions}
        assert by_name["slack_send_message"].success is True
        assert by_name["jira_create_issue"].success is False
        assert "Jira auth failed" in by_name["jira_create_issue"].error


class TestStreaming:
    @pytest.mark.asyncio
    async def test_emits_full_task_lifecycle(self, monkeypatch):
        from app.services.task_planner import PlannedTask, TaskPlan

        monkeypatch.setattr(
            agent_module, "get_llm",
            lambda **kw: scripted(
                AIMessage(content="", tool_calls=[
                    {"name": "slack_send_message",
                     "args": {"channel": "dev", "message": "x"}, "id": "c1"},
                    {"name": "jira_create_issue", "args": {"summary": "b"}, "id": "c2"},
                ]),
                AIMessage(content="Slack posted; Jira failed."),
            ),
        )
        monkeypatch.setattr(
            agent_module, "build_tools",
            lambda cfg: [slack_send_message, jira_create_issue],
        )
        monkeypatch.setattr(
            agent_module, "parse_tasks_from_message",
            lambda m, s: TaskPlan(total=2, tasks=[
                PlannedTask(id="task_1", service="slack", action="send",
                            description="Post to Slack", tool_name="slack_send_message"),
                PlannedTask(id="task_2", service="jira", action="create",
                            description="Create ticket", tool_name="jira_create_issue"),
            ]),
        )

        events = [
            e async for e in agent_module.process_chat_message_streaming(
                "do both", {"slack": {}, "jira": {}}
            )
        ]
        kinds = [e["event_type"] for e in events]

        assert kinds[0] == "planning"
        assert "plan" in kinds
        assert kinds.count("task_started") == 2
        assert "task_completed" in kinds
        # The failing tool is reported as a failed task, not an aborted stream.
        assert "task_failed" in kinds
        assert "error" not in kinds
        assert kinds[-1] == "complete"

    @pytest.mark.asyncio
    async def test_no_tools_emits_error(self, monkeypatch):
        monkeypatch.setattr(agent_module, "build_tools", lambda cfg: [])
        events = [
            e async for e in agent_module.process_chat_message_streaming("hi", {})
        ]
        assert events[0]["event_type"] == "error"
