"""
LangChain Agent Orchestrator
Main agent that processes natural language and routes to appropriate tools
"""

import os
from typing import Any
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

load_dotenv()

# Initialize Gemini LLM
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

if not GOOGLE_API_KEY:
    print("WARNING: GOOGLE_API_KEY not set. Chat functionality will be limited.")

llm = None
if GOOGLE_API_KEY:
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        google_api_key=GOOGLE_API_KEY,
        temperature=0.1,
        convert_system_message_to_human=True,  # Required for Gemini to handle system prompts
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

### Google Calendar (Scheduling)
- Create calendar events with attendees
- View upcoming events

## Guidelines:
- When the user asks you to do something, use the appropriate tool with correct parameters.
- For destructive actions like deleting projects, always confirm with the user first.
- If a tool returns an error, explain what went wrong and suggest alternatives.
- Be concise but informative in your responses.
- When searching Jira, help users construct JQL queries if needed."""


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
    
    return tools


def create_agent_executor(tools: list[BaseTool]) -> AgentExecutor:
    """Create a LangChain agent with the given tools using native tool calling."""
    if not llm:
        raise ValueError("LLM not configured. Please set GOOGLE_API_KEY.")
    
    # Create a prompt that works with the tool calling agent
    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        ("human", "{input}"),
        MessagesPlaceholder(variable_name="agent_scratchpad"),
    ])
    
    # Use tool calling agent instead of ReAct for better structured output
    agent = create_tool_calling_agent(llm, tools, prompt)
    
    return AgentExecutor(
        agent=agent,
        tools=tools,
        verbose=True,
        handle_parsing_errors=True,
        max_iterations=5
    )


async def process_chat_message(
    message: str,
    integration_configs: dict[str, dict]
) -> ChatResponse:
    """
    Process a natural language message through the LangChain agent.
    """
    # Build tools based on available integrations
    tools = build_tools(integration_configs)
    
    if not tools:
        return ChatResponse(
            message="No integration tools available. Please connect at least one service.",
            actions_taken=[],
            raw_response=None
        )
    
    if not llm:
        return ChatResponse(
            message="LLM not configured. Please set GOOGLE_API_KEY.",
            actions_taken=[],
            raw_response=None
        )
    
    # Create and run agent SYNCHRONOUSLY to avoid coroutine issues
    agent = create_agent_executor(tools)
    
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
