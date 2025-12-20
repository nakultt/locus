"""
LangChain Agent Orchestrator
Main agent that processes natural language and routes to appropriate tools
"""

import os
from typing import Any, Optional
from dotenv import load_dotenv

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import BaseTool

from app.schemas import ChatResponse, ActionResult
from app.services.jira import get_jira_tools
from app.services.gmail import get_gmail_tools
from app.services.calendar import get_calendar_tools
from app.services.slack import get_slack_tools
from app.services.notion import get_notion_tools
from app.services.bugasura import get_bugasura_tools
from app.services.google_docs import get_docs_tools
from app.services.google_sheets import get_sheets_tools
from app.services.google_slides import get_slides_tools
from app.services.google_drive import get_drive_tools
from app.services.google_forms import get_forms_tools
from app.services.google_meet import get_meet_tools
from app.services.github import get_github_tools
from app.services.linear import get_linear_tools

load_dotenv()

# Fallback to server-level API key if user hasn't configured their own
FALLBACK_GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")


def get_llm(api_key: str, smart_mode: bool = False) -> ChatGoogleGenerativeAI:
    """
    Create a Gemini LLM instance with the given API key.
    
    Args:
        api_key: User's Gemini API key
        smart_mode: Use higher intelligence model when True
        
    Returns:
        ChatGoogleGenerativeAI instance
    """
    model = "gemini-2.5-pro" if smart_mode else "gemini-2.5-flash"
    
    return ChatGoogleGenerativeAI(
        model=model,
        google_api_key=api_key,
        temperature=0.1,
        convert_system_message_to_human=True,
    )


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


def build_tools(integration_configs: dict[str, dict]) -> list[BaseTool]:
    """
    Build list of available tools based on user's connected integrations.
    """
    tools: list[BaseTool] = []
    
    # Jira tools
    if "jira" in integration_configs:
        config = integration_configs["jira"]
        jira_tools = get_jira_tools(
            api_token=config.get("api_key", ""),
            email=config.get("credentials", {}).get("email", ""),
            url=config.get("credentials", {}).get("url", "")
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
            credentials=config.get("credentials", {})
        )
        tools.extend(calendar_tools)
    
    # Slack tools
    if "slack" in integration_configs:
        config = integration_configs["slack"]
        slack_tools = get_slack_tools(
            bot_token=config.get("api_key", "")
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
            credentials=config.get("credentials", {})
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


def create_agent_executor(tools: list[BaseTool], api_key: str, smart_mode: bool = False) -> AgentExecutor:
    """Create a LangChain agent with the given tools using native tool calling.
    
    Args:
        tools: List of available tools
        api_key: User's Gemini API key
        smart_mode: Use higher intelligence model when True
    """
    # Create LLM with user's API key
    selected_llm = get_llm(api_key, smart_mode)
    
    # Create a prompt that works with the tool calling agent
    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        ("human", "{input}"),
        MessagesPlaceholder(variable_name="agent_scratchpad"),
    ])
    
    # Use tool calling agent instead of ReAct for better structured output
    agent = create_tool_calling_agent(selected_llm, tools, prompt)
    
    return AgentExecutor(
        agent=agent,
        tools=tools,
        verbose=True,
        handle_parsing_errors=True,
        max_iterations=25  # Increased for multi-tool requests (up to 25 tools)
    )


async def process_chat_message(
    message: str,
    integration_configs: dict[str, dict],
    gemini_api_key: Optional[str] = None,
    smart_mode: bool = False
) -> ChatResponse:
    """
    Process a natural language message through the LangChain agent.
    
    Args:
        message: User's natural language command
        integration_configs: Dict of service name to config
        gemini_api_key: User's Gemini API key (required)
        smart_mode: Use higher intelligence model when True
    """
    # Build tools based on available integrations
    tools = build_tools(integration_configs)
    
    if not tools:
        return ChatResponse(
            message="No integration tools available. Please connect at least one service.",
            actions_taken=[],
            raw_response=None
        )
    
    # Check for API key - use user's key or fall back to server key
    api_key = gemini_api_key or FALLBACK_GOOGLE_API_KEY
    
    if not api_key:
        return ChatResponse(
            message="No Gemini API key configured. Please add your Gemini API key in Settings.",
            actions_taken=[],
            raw_response=None
        )
    
    # Create and run agent SYNCHRONOUSLY to avoid coroutine issues
    agent = create_agent_executor(tools, api_key=api_key, smart_mode=smart_mode)
    
    try:
        # Use sync invoke instead of ainvoke to avoid StopIteration errors
        result = agent.invoke({"input": message})
        
        output = result.get("output", "")
        intermediate_steps = result.get("intermediate_steps", [])
        
        # Extract actions taken
        actions_taken: list[ActionResult] = []
        for step in intermediate_steps:
            if len(step) >= 2:
                action, observation = step[0], step[1]
                tool_name = getattr(action, "tool", "unknown")
                
                service = determine_service(tool_name)
                
                actions_taken.append(ActionResult(
                    service=service,
                    action=tool_name,
                    success=True,
                    result=str(observation) if observation else None
                ))
        
        return ChatResponse(
            message=output,
            actions_taken=actions_taken,
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


async def process_without_llm(
    message: str,
    tools: list[BaseTool],
    integration_configs: dict[str, dict]
) -> ChatResponse:
    """
    Simple keyword-based processing when no LLM is available.
    """
    message_lower = message.lower()
    actions_taken: list[ActionResult] = []
    response_parts: list[str] = []
    
    # Jira commands
    if "jira" in message_lower or "ticket" in message_lower or "issue" in message_lower:
        if "create" in message_lower:
            # Extract summary from message
            summary = message.replace("create", "").replace("jira", "").replace("ticket", "").replace("issue", "").strip()
            if not summary:
                summary = "New issue from Conflux"
            
            for tool in tools:
                if "create" in tool.name.lower() and "jira" in tool.name.lower():
                    try:
                        result = tool.invoke({"summary": summary, "description": "", "project_key": "CONFLUX", "issue_type": "Task"})
                        response_parts.append(str(result))
                        actions_taken.append(ActionResult(
                            service="jira",
                            action=tool.name,
                            success=True,
                            result=str(result)
                        ))
                    except Exception as e:
                        response_parts.append(f"Error: {e}")
                    break
        elif "search" in message_lower or "find" in message_lower:
            query = message.replace("search", "").replace("find", "").replace("jira", "").strip()
            for tool in tools:
                if "search" in tool.name.lower() and "jira" in tool.name.lower():
                    try:
                        result = tool.invoke({"query": query, "max_results": 5})
                        response_parts.append(str(result))
                        actions_taken.append(ActionResult(
                            service="jira",
                            action=tool.name,
                            success=True,
                            result=str(result)
                        ))
                    except Exception as e:
                        response_parts.append(f"Error: {e}")
                    break
    
    # Slack commands
    if "slack" in message_lower or "post" in message_lower:
        if "send" in message_lower or "post" in message_lower:
            for tool in tools:
                if "slack" in tool.name.lower() and "send" in tool.name.lower():
                    try:
                        result = tool.invoke({"channel": "general", "message": message})
                        response_parts.append(str(result))
                        actions_taken.append(ActionResult(
                            service="slack",
                            action=tool.name,
                            success=True,
                            result=str(result)
                        ))
                    except Exception as e:
                        response_parts.append(f"Error: {e}")
                    break
    
    # Calendar commands
    if "calendar" in message_lower or "schedule" in message_lower or "meeting" in message_lower:
        if "create" in message_lower or "schedule" in message_lower:
            for tool in tools:
                if "calendar" in tool.name.lower() and "create" in tool.name.lower():
                    try:
                        result = tool.invoke({
                            "summary": message,
                            "description": "",
                            "start_time": "tomorrow at 2pm",
                            "duration_minutes": 60,
                            "attendees": ""
                        })
                        response_parts.append(str(result))
                        actions_taken.append(ActionResult(
                            service="calendar",
                            action=tool.name,
                            success=True,
                            result=str(result)
                        ))
                    except Exception as e:
                        response_parts.append(f"Error: {e}")
                    break
    
    if not response_parts:
        response_parts.append(
            "I understood your request but couldn't find a matching action. "
            "Try commands like:\n"
            "- 'Create a Jira ticket for [issue]'\n"
            "- 'Search Jira for [query]'\n"
            "- 'Send [message] to Slack channel [name]'\n"
            "- 'Schedule a meeting [when]'\n"
            "\nNote: For full natural language support, please configure your GOOGLE_API_KEY."
        )
    
    return ChatResponse(
        message="\n\n".join(response_parts),
        actions_taken=actions_taken,
        raw_response=None
    )


# ============================================================================
# STREAMING CHAT PROCESSING
# ============================================================================

from typing import AsyncGenerator
from app.services.task_planner import parse_tasks_from_message, TaskPlan, TaskStatus


async def process_chat_message_streaming(
    message: str,
    integration_configs: dict[str, dict],
    gemini_api_key: Optional[str] = None
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
    # Build tools based on available integrations
    tools = build_tools(integration_configs)
    available_services = list(integration_configs.keys())
    
    if not tools:
        yield {
            "event_type": "error",
            "data": {"message": "No integration tools available. Please connect at least one service."}
        }
        return
    
    # Check for API key - use user's key or fall back to server key
    api_key = gemini_api_key or FALLBACK_GOOGLE_API_KEY
    
    if not api_key:
        yield {
            "event_type": "error",
            "data": {"message": "No Gemini API key configured. Please add your Gemini API key in Settings."}
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
            result = await process_chat_message(message, integration_configs, gemini_api_key=api_key)
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
    
    # Step 3: Create agent for execution with user's API key
    agent = create_agent_executor(tools, api_key=api_key)
    
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
    completed_tasks: dict[str, str] = {}  # task_id -> result
    
    try:
        # Execute with the agent
        result = agent.invoke({"input": enhanced_message})
        
        output = result.get("output", "")
        intermediate_steps = result.get("intermediate_steps", [])
        
        # Process each step and emit updates
        for i, step in enumerate(intermediate_steps):
            if len(step) >= 2:
                action, observation = step[0], step[1]
                tool_name = getattr(action, "tool", "unknown")
                
                service = determine_service(tool_name)
                
                # Find matching task in plan
                matching_task = None
                for task in task_plan.tasks:
                    if task.tool_name == tool_name and task.status == TaskStatus.PENDING:
                        matching_task = task
                        break
                
                task_id = matching_task.id if matching_task else f"task_{i+1}"
                
                # Emit task started
                yield {
                    "event_type": "task_started",
                    "data": {
                        "task_id": task_id,
                        "service": service,
                        "action": tool_name,
                        "description": matching_task.description if matching_task else tool_name,
                    }
                }
                
                # Check if successful (basic heuristic)
                is_success = observation and "error" not in str(observation).lower()[:50]
                
                if is_success:
                    # Update plan
                    if matching_task:
                        task_plan.update_task_status(task_id, TaskStatus.COMPLETED, str(observation))
                    completed_tasks[task_id] = str(observation)
                    
                    # Emit task completed
                    yield {
                        "event_type": "task_completed",
                        "data": {
                            "task_id": task_id,
                            "service": service,
                            "action": tool_name,
                            "result": str(observation)[:500],  # Truncate for SSE
                        }
                    }
                else:
                    # Update plan
                    if matching_task:
                        task_plan.update_task_status(task_id, TaskStatus.FAILED, error=str(observation))
                    
                    # Emit task failed
                    yield {
                        "event_type": "task_failed",
                        "data": {
                            "task_id": task_id,
                            "service": service,
                            "action": tool_name,
                            "error": str(observation)[:500],
                        }
                    }
                
                actions_taken.append(ActionResult(
                    service=service,
                    action=tool_name,
                    success=is_success,
                    result=str(observation) if is_success else None,
                    error=str(observation) if not is_success else None
                ))
        
        # Step 5: Emit completion
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

