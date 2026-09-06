"""
LangChain Agent Orchestrator
Main agent that processes natural language and routes to appropriate tools
"""

from collections.abc import AsyncGenerator
from datetime import timedelta

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.tools import BaseTool

from app.core.datetimes import now_in, resolve_timezone
from app.schemas import ActionResult, ChatResponse
from app.services.chat.llm import get_llm, message_text
from app.services.chat.task_planner import TaskStatus, parse_tasks_from_message
from app.services.integrations.bugasura import get_bugasura_tools
from app.services.integrations.calendar import get_calendar_tools
from app.services.integrations.github import get_github_tools
from app.services.integrations.gmail import get_gmail_tools
from app.services.integrations.google_docs import get_docs_tools
from app.services.integrations.google_drive import get_drive_tools
from app.services.integrations.google_forms import get_forms_tools
from app.services.integrations.google_meet import get_meet_tools
from app.services.integrations.google_sheets import get_sheets_tools
from app.services.integrations.google_slides import get_slides_tools
from app.services.integrations.jira import get_jira_tools
from app.services.integrations.linear import get_linear_tools
from app.services.integrations.notion import get_notion_tools
from app.services.integrations.slack import get_slack_tools

load_dotenv()


# System prompt for the agent
SYSTEM_PROMPT = """You are Locus, an intelligent enterprise integration assistant.
Your role is to help users interact with their connected workplace tools through natural language.

## Your Capabilities:

### Jira (Issue & Project Management)
- Create, update, and search issues using JQL
- Add comments and transition issues between statuses
- Create and delete projects (deletion requires confirmation)
- List and assign workflow schemes to projects
- List and assign permission schemes to projects

### Slack (Team Communication)
- Send messages to channels
- Post formatted updates with titles
- List available channels

### Notion (Documentation)
- Search pages and content
- Get page content by title
- List recent pages
- Create new pages with content
- Append content to existing pages

### Gmail (Email)
- Send emails with subject and body
- Read latest emails from inbox

### Google Calendar (Scheduling)
- Create, update, and delete calendar events
- Add attendees to events

### Google Docs (Documents)
- Create new documents with content
- Append content to existing documents

### Google Sheets (Spreadsheets)
- Create new spreadsheets
- Add rows to existing spreadsheets

### Google Slides (Presentations)
- Create presentations with slides and bullet points

### Google Drive (File Storage)
- Upload files to Drive
- Share files with users
- List and search files

### Google Forms (Surveys)
- Create forms with text and choice questions

### Google Meet (Video Meetings)
- Create video meetings with Meet links
- Schedule meetings with attendees

### Bugasura (Bug Tracking)
- Create and list bugs/issues
- Add comments to issues
- Get issue details

### GitHub (Source Control & Issues)
- List, view and create repositories
- Create, update, and comment on issues
- List, create, and merge pull requests
- Get authenticated user info

### Linear (Issue Tracking)
- List teams and workflow states
- Create, update, and list issues
- Add comments to issues
- Update issue status and priority

## Guidelines:
- When the user asks you to do something, use the appropriate tool with correct parameters.
- For destructive actions like deleting projects, always confirm with the user first.
- If a tool returns an error, explain what went wrong and suggest alternatives.
- Be concise but informative in your responses.
- When searching Jira, help users construct JQL queries if needed.

## CRITICAL: Multi-Task Execution

When a user requests MULTIPLE actions in a single message, you MUST:

1. **Identify ALL tasks**: Parse the entire message and list every action the user wants.
2. **Execute ALL tasks**: Do NOT stop after completing just one task. Continue calling tools until EVERY requested action is complete.
3. **Execute in logical order**: If tasks depend on each other, execute them in the right sequence:
   - Calendar/Meeting creation FIRST (to get event links/IDs)
   - Jira ticket creation (to get ticket keys)
   - Slack messages (can reference tickets/meetings)
   - Gmail emails (include meeting links, ticket references)
   - Notion summaries LAST (can summarize all actions taken)
4. **Chain results**: Use output from previous tasks as input for subsequent tasks:
   - If user wants to "email about the meeting", include the actual meeting link from the calendar event
   - If user wants to "summarize in Notion", include details from all completed actions
5. **Report everything**: After completing all tasks, provide a comprehensive summary of ALL actions taken.

EXAMPLE: If user says "send a Slack message to #general, create a Jira ticket, and send an email to bob@example.com":
- Call slack_send_message
- Call jira_create_issue
- Call gmail_send_email (mention the Jira ticket key)
- Then respond with summary of all three actions

NEVER stop after just 1-2 actions if the user requested more. ALWAYS complete ALL requested tasks."""


def _current_date_note(timezone: str | None) -> str:
    """
    State today's date for the model.

    Without it a model resolves "tomorrow" against its training cutoff, which
    is how a meeting asked for tomorrow was booked into a date over a year
    past. The tools parse relative phrasing correctly against the real clock
    (`datetimes.parse_datetime`), so the failure only happens when the model
    resolves the date itself and passes an absolute one down.

    The date is stated in the user's zone, since that is the day they mean.
    """
    now = now_in(timezone)
    tomorrow = now + timedelta(days=1)
    return (
        "\n\n## Current date and time\n"
        f"Right now it is {now:%A, %d %B %Y at %H:%M} "
        f"({now.tzname()}, {resolve_timezone(timezone).key}). "
        f"\"Tomorrow\" therefore means {tomorrow:%A, %d %B %Y}.\n"
        "\n"
        "Do NOT do date arithmetic yourself. The scheduling tools parse "
        "natural language against this same clock, so pass the user's own "
        "words through verbatim -- send \"tomorrow at 11pm\", not a date you "
        "worked out. Converting it yourself is how a meeting asked for "
        "tomorrow gets booked for today. Only pass an absolute date when the "
        "user stated one."
    )


def build_tools(
    integration_configs: dict[str, dict],
    timezone: str | None = None,
) -> list[BaseTool]:
    """
    Build the tools available for one user's connected integrations.

    Args:
        integration_configs: Decrypted credentials by service
        timezone: The user's IANA timezone, needed for calendar scheduling
    """
    tools: list[BaseTool] = []
    
    # Jira tools
    if "jira" in integration_configs:
        config = integration_configs["jira"]
        jira_tools = get_jira_tools(
            api_token=config.get("api_key", ""),
            email=config.get("credentials", {}).get("email", ""),
            url=config.get("credentials", {}).get("url", ""),
            default_project_key=config.get("credentials", {}).get("default_project_key", "")
        )
        tools.extend(jira_tools)
    
    # Gmail tools
    if "gmail" in integration_configs:
        config = integration_configs["gmail"]
        gmail_tools = get_gmail_tools(
            credentials=config.get("credentials", {}),
            api_key=config.get("api_key", "")
        )
        tools.extend(gmail_tools)
    
    # Calendar tools
    if "calendar" in integration_configs:
        config = integration_configs["calendar"]
        calendar_tools = get_calendar_tools(
            credentials=config.get("credentials", {}),
            timezone=timezone,
        )
        tools.extend(calendar_tools)
    
    # Slack tools
    if "slack" in integration_configs:
        config = integration_configs["slack"]
        credentials = config.get("credentials", {}) or {}
        # Bot token may be stored either as the api_key or inside credentials.
        slack_tools = get_slack_tools(
            bot_token=credentials.get("bot_token") or config.get("api_key", ""),
            user_token=credentials.get("user_token", ""),
        )
        tools.extend(slack_tools)
    
    # Notion tools
    if "notion" in integration_configs:
        config = integration_configs["notion"]
        notion_tools = get_notion_tools(
            integration_token=config.get("api_key", "")
        )
        tools.extend(notion_tools)
    
    # Bugasura tools
    if "bugasura" in integration_configs:
        config = integration_configs["bugasura"]
        bugasura_tools = get_bugasura_tools(
            api_key=config.get("api_key", ""),
            team_id=config.get("credentials", {}).get("team_id", ""),
            project_key=config.get("credentials", {}).get("project_key", "")
        )
        tools.extend(bugasura_tools)
    
    # Google Docs tools
    if "docs" in integration_configs:
        config = integration_configs["docs"]
        docs_tools = get_docs_tools(
            credentials=config.get("credentials", {})
        )
        tools.extend(docs_tools)
    
    # Google Sheets tools
    if "sheets" in integration_configs:
        config = integration_configs["sheets"]
        sheets_tools = get_sheets_tools(
            credentials=config.get("credentials", {})
        )
        tools.extend(sheets_tools)
    
    # Google Slides tools
    if "slides" in integration_configs:
        config = integration_configs["slides"]
        slides_tools = get_slides_tools(
            credentials=config.get("credentials", {})
        )
        tools.extend(slides_tools)
    
    # Google Drive tools
    if "drive" in integration_configs:
        config = integration_configs["drive"]
        drive_tools = get_drive_tools(
            credentials=config.get("credentials", {})
        )
        tools.extend(drive_tools)
    
    # Google Forms tools
    if "forms" in integration_configs:
        config = integration_configs["forms"]
        forms_tools = get_forms_tools(
            credentials=config.get("credentials", {})
        )
        tools.extend(forms_tools)
    
    # Google Meet tools
    if "meet" in integration_configs:
        config = integration_configs["meet"]
        meet_tools = get_meet_tools(
            credentials=config.get("credentials", {}),
            timezone=timezone,
        )
        tools.extend(meet_tools)
    
    # GitHub tools
    if "github" in integration_configs:
        config = integration_configs["github"]
        github_tools = get_github_tools(
            token=config.get("api_key", "")
        )
        tools.extend(github_tools)
    
    # Linear tools
    if "linear" in integration_configs:
        config = integration_configs["linear"]
        linear_tools = get_linear_tools(
            api_key=config.get("api_key", "")
        )
        tools.extend(linear_tools)
    
    return tools


# Cap on agent loop turns. Multi-task requests legitimately need many tool
# calls; this stops a confused model looping forever on a local GPU.
MAX_AGENT_ITERATIONS = 25


class ToolErrorMiddleware(AgentMiddleware):
    """
    Convert a tool exception into an error ToolMessage instead of aborting.

    A request that touches five integrations should not lose the four that
    succeeded because the fifth had an expired token. The agent sees the error
    and can report it; the caller still gets partial results.
    """

    def wrap_tool_call(self, request, handler):
        try:
            return handler(request)
        except Exception as e:
            return ToolMessage(
                content=f"Error: {e}",
                tool_call_id=request.tool_call["id"],
                name=request.tool_call.get("name", ""),
                status="error",
            )

    async def awrap_tool_call(self, request, handler):
        try:
            return await handler(request)
        except Exception as e:
            return ToolMessage(
                content=f"Error: {e}",
                tool_call_id=request.tool_call["id"],
                name=request.tool_call.get("name", ""),
                status="error",
            )


def create_agent_executor(
    tools: list[BaseTool],
    smart_mode: bool = False,
    timezone: str | None = None,
):
    """
    Build an agent graph over the given tools.

    LangChain 1.x replaced AgentExecutor with `create_agent`, which returns a
    compiled LangGraph. The invoke contract changed with it: messages in and
    messages out, rather than {"input": ...} -> {"output", "intermediate_steps"}.

    The system prompt is built per call rather than being the module constant,
    because it carries today's date -- a constant evaluated at import time
    would go stale in a process that runs for days.

    Args:
        tools: Tools the agent may call
        smart_mode: Use the higher-capability model when True
        timezone: The user's IANA timezone, the zone today's date is stated in
    """
    return create_agent(
        model=get_llm(smart_mode=smart_mode),
        tools=tools,
        system_prompt=SYSTEM_PROMPT + _current_date_note(timezone),
        middleware=[ToolErrorMiddleware()],
    )


def extract_actions(messages: list[BaseMessage]) -> list[ActionResult]:
    """
    Turn an agent message list into the ActionResult list the UI renders.

    Tool calls arrive as an AIMessage carrying `tool_calls`, each paired with a
    later ToolMessage holding the result and matching `tool_call_id`. This
    replaces the (action, observation) tuples AgentExecutor used to expose.
    """
    # tool_call_id -> ToolMessage, so a result can be found for each call.
    results_by_id: dict[str, ToolMessage] = {
        m.tool_call_id: m for m in messages if isinstance(m, ToolMessage)
    }

    actions: list[ActionResult] = []
    for message in messages:
        for call in getattr(message, "tool_calls", None) or []:
            tool_name = call.get("name", "unknown")
            result = results_by_id.get(call.get("id", ""))

            observation = str(result.content) if result is not None else ""
            # ToolMessage.status is the framework's own signal, far more
            # reliable than sniffing the string for the word "error".
            failed = result is not None and getattr(result, "status", None) == "error"

            actions.append(ActionResult(
                service=determine_service(tool_name),
                action=tool_name,
                success=not failed,
                result=observation if not failed else None,
                error=observation if failed else None,
            ))

    return actions


# How many prior turns to replay into the agent. Local models run an 8K context
# and the system prompt plus tool schemas already consume a large share of it,
# so history is capped rather than unbounded.
MAX_HISTORY_MESSAGES = 20


def build_message_history(
    history: list[tuple[str, str]] | None,
    message: str,
) -> list[BaseMessage]:
    """
    Turn stored conversation rows into the message list the agent expects.

    Without this the agent sees only the current turn, so a reply like "#web"
    that answers a question the assistant just asked arrives with no idea what
    it refers to.

    Args:
        history: (role, content) pairs oldest-first, excluding the current turn
        message: The current user message

    Returns:
        Messages ready to pass as {"messages": ...}
    """
    messages: list[BaseMessage] = []

    for role, content in (history or [])[-MAX_HISTORY_MESSAGES:]:
        if not content:
            continue
        if role == "user":
            messages.append(HumanMessage(content=content))
        elif role == "assistant":
            messages.append(AIMessage(content=content))

    messages.append(HumanMessage(content=message))
    return messages


def final_text(messages: list[BaseMessage]) -> str:
    """Return the agent's last assistant message."""
    for message in reversed(messages):
        if isinstance(message, AIMessage) and message.content:
            # One implementation of "what did the model say", shared with every
            # analysis pass. This one was always correct; the seven parsers in
            # the pipeline each had their own copy that was not.
            return message_text(message)
    return ""


async def process_chat_message(
    message: str,
    integration_configs: dict[str, dict],
    smart_mode: bool = False,
    history: list[tuple[str, str]] | None = None,
    timezone: str | None = None,
) -> ChatResponse:
    """
    Process a natural language message through the LangChain agent.

    Args:
        message: User's natural language command
        integration_configs: Dict of service name to config
        smart_mode: Use higher intelligence model when True
        history: Prior (role, content) turns in this conversation, oldest first
    """
    tools = build_tools(integration_configs, timezone=timezone)

    if not tools:
        return ChatResponse(
            message="No integration tools available. Please connect at least one service.",
            actions_taken=[],
            raw_response=None
        )

    agent = create_agent_executor(tools, smart_mode=smart_mode, timezone=timezone)

    try:
        result = await agent.ainvoke(
            {"messages": build_message_history(history, message)},
            config={"recursion_limit": MAX_AGENT_ITERATIONS * 2},
        )

        messages = result.get("messages", [])
        output = final_text(messages)

        return ChatResponse(
            message=output,
            actions_taken=extract_actions(messages),
            raw_response=output
        )


    except Exception as e:
        return ChatResponse(
            message=f"I encountered an error while processing your request: {str(e)}",
            actions_taken=[
                ActionResult(
                    service="agent",
                    action="process_message",
                    success=False,
                    error=str(e)
                )
            ],
            raw_response=None
        )


def determine_service(tool_name: str) -> str:
    """Determine the service from tool name."""
    tool_lower = tool_name.lower()
    if "jira" in tool_lower:
        return "jira"
    elif "gmail" in tool_lower or "email" in tool_lower:
        return "gmail"
    elif "calendar" in tool_lower or "event" in tool_lower:
        return "calendar"
    elif "slack" in tool_lower:
        return "slack"
    elif "notion" in tool_lower:
        return "notion"
    elif "bugasura" in tool_lower:
        return "bugasura"
    elif "docs" in tool_lower or "document" in tool_lower:
        return "docs"
    elif "sheets" in tool_lower or "spreadsheet" in tool_lower:
        return "sheets"
    elif "slides" in tool_lower or "presentation" in tool_lower:
        return "slides"
    elif "drive" in tool_lower or "file" in tool_lower:
        return "drive"
    elif "forms" in tool_lower or "form" in tool_lower:
        return "forms"
    elif "meet" in tool_lower or "meeting" in tool_lower:
        return "meet"
    elif "github" in tool_lower:
        return "github"
    elif "linear" in tool_lower:
        return "linear"
    return "unknown"


# ============================================================================
# STREAMING CHAT PROCESSING
# ============================================================================


async def process_chat_message_streaming(
    message: str,
    integration_configs: dict[str, dict],
    history: list[tuple[str, str]] | None = None,
    timezone: str | None = None,
) -> AsyncGenerator[dict, None]:
    """
    Process a chat message with streaming task updates.
    
    Yields SSE events for real-time frontend updates:
    - planning: Initial message that we're analyzing
    - plan: Task plan with all identified tasks
    - task_started: When a task begins execution
    - task_completed: When a task finishes successfully
    - task_failed: When a task fails
    - complete: Final response with all results
    - error: If something goes wrong
    """
    tools = build_tools(integration_configs, timezone=timezone)
    available_services = list(integration_configs.keys())
    
    if not tools:
        yield {
            "event_type": "error",
            "data": {"message": "No integration tools available. Please connect at least one service."}
        }
        return

    # Step 1: Parse and plan tasks
    yield {
        "event_type": "planning",
        "data": {"status": "Analyzing your request..."}
    }
    
    task_plan = parse_tasks_from_message(message, available_services)
    
    if not task_plan.tasks:
        # No specific tasks identified, fall back to regular processing
        yield {
            "event_type": "planning",
            "data": {"status": "Processing with AI agent..."}
        }
        
        # Use regular agent for single/unclear requests
        try:
            result = await process_chat_message(
                message, integration_configs, history=history, timezone=timezone
            )
            yield {
                "event_type": "complete",
                "data": {
                    "message": result.message,
                    "actions_taken": [a.model_dump() for a in result.actions_taken],
                }
            }
        except Exception as e:
            yield {
                "event_type": "error",
                "data": {"message": str(e)}
            }
        return
    
    # Step 2: Emit the task plan
    yield {
        "event_type": "plan",
        "data": task_plan.to_dict()
    }
    
    # Step 3: Create agent for execution
    agent = create_agent_executor(tools, timezone=timezone)
    
    # Step 4: Execute using the agent with enhanced prompt
    # Build a prompt that explicitly lists all tasks
    task_list = "\n".join([
        f"- Task {i+1}: {t.description} (use {t.tool_name})"
        for i, t in enumerate(task_plan.tasks)
    ])
    
    enhanced_message = f"""{message}

IMPORTANT: You must complete ALL of the following tasks:
{task_list}

Execute each task in order and use the results from earlier tasks when needed (e.g., include meeting links in emails).
Do NOT stop until all tasks are complete."""
    
    actions_taken: list[ActionResult] = []
    output = ""

    # Pending tool calls awaiting their result: tool_call_id -> (task_id, service, tool_name)
    in_flight: dict[str, tuple[str, str, str]] = {}
    step_counter = 0

    def claim_task(tool_name: str) -> tuple[str, str]:
        """Match a tool call to a planned task, returning (task_id, description)."""
        nonlocal step_counter
        for task in task_plan.tasks:
            if task.tool_name == tool_name and task.status == TaskStatus.PENDING:
                task.status = TaskStatus.IN_PROGRESS
                return task.id, task.description
        step_counter += 1
        return f"task_{step_counter}", tool_name

    try:
        # Stream node updates so events are emitted as work happens, rather than
        # replayed from intermediate_steps once the whole run has finished.
        async for chunk in agent.astream(
            {"messages": build_message_history(history, enhanced_message)},
            config={"recursion_limit": MAX_AGENT_ITERATIONS * 2},
            stream_mode="updates",
        ):
            for node_output in chunk.values():
                for msg in node_output.get("messages", []) if isinstance(node_output, dict) else []:

                    # The model decided to call tools: announce them now.
                    for call in getattr(msg, "tool_calls", None) or []:
                        tool_name = call.get("name", "unknown")
                        service = determine_service(tool_name)
                        task_id, description = claim_task(tool_name)
                        in_flight[call.get("id", "")] = (task_id, service, tool_name)

                        yield {
                            "event_type": "task_started",
                            "data": {
                                "task_id": task_id,
                                "service": service,
                                "action": tool_name,
                                "description": description,
                            }
                        }

                    # A tool returned: report success or failure.
                    if isinstance(msg, ToolMessage):
                        task_id, service, tool_name = in_flight.pop(
                            msg.tool_call_id, (f"task_{step_counter}", "unknown", msg.name or "unknown")
                        )
                        observation = str(msg.content)
                        failed = getattr(msg, "status", None) == "error"

                        task_plan.update_task_status(
                            task_id,
                            TaskStatus.FAILED if failed else TaskStatus.COMPLETED,
                            **({"error": observation} if failed else {"result": observation}),
                        )

                        yield {
                            "event_type": "task_failed" if failed else "task_completed",
                            "data": {
                                "task_id": task_id,
                                "service": service,
                                "action": tool_name,
                                ("error" if failed else "result"): observation[:500],
                            }
                        }

                        actions_taken.append(ActionResult(
                            service=service,
                            action=tool_name,
                            success=not failed,
                            result=None if failed else observation,
                            error=observation if failed else None,
                        ))

                    # Plain assistant text is the running final answer.
                    elif isinstance(msg, AIMessage) and msg.content:
                        text = final_text([msg])
                        if text:
                            output = text

        yield {
            "event_type": "complete",
            "data": {
                "message": output,
                "actions_taken": [a.model_dump() for a in actions_taken],
                "total_tasks": task_plan.total,
                "completed_tasks": task_plan.completed,
                "failed_tasks": task_plan.failed,
            }
        }


    except Exception as e:
        yield {
            "event_type": "error",
            "data": {"message": f"Error processing request: {str(e)}"}
        }

