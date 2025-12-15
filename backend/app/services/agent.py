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
    raise ValueError("GOOGLE_API_KEY environment variable is required")

llm = ChatGoogleGenerativeAI(
    model="gemini-1.5-flash",
    google_api_key=GOOGLE_API_KEY,
    temperature=0.1,
    convert_system_message_to_human=True
)

# System prompt for the agent
SYSTEM_PROMPT = """You are Conflux, an intelligent enterprise integration assistant.
Your role is to help users interact with their connected workplace tools through natural language.

Available integrations and their capabilities:
- **Jira**: Create issues, search tickets, get issue details
- **Gmail**: Send emails, read inbox, create drafts, search emails
- **Calendar**: Create events, view schedule, list upcoming events
- **Slack**: Send messages to channels, post updates
- **Notion**: Search pages, query documentation

Guidelines:
1. Parse the user's intent carefully
2. Use the appropriate tool(s) to fulfill the request
3. If a required integration is not available, inform the user politely
4. Provide clear, concise responses about actions taken
5. If you're unsure about parameters, ask for clarification

Always be helpful and proactive in suggesting related actions when appropriate."""


def build_tools(integration_configs: dict[str, dict]) -> list[BaseTool]:
    """
    Build list of available tools based on user's connected integrations.
    
    Args:
        integration_configs: Dict mapping service names to their credentials
        
    Returns:
        List of LangChain tools available for the user
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
            credentials=config.get("credentials", {})
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


def create_agent(tools: list[BaseTool]) -> AgentExecutor:
    """Create a LangChain agent with the given tools."""
    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        ("human", "{input}"),
        MessagesPlaceholder(variable_name="agent_scratchpad"),
    ])
    
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
    
    Args:
        message: User's natural language command
        integration_configs: Dict of available integrations and their credentials
        
    Returns:
        ChatResponse with action results
    """
    # Build tools based on available integrations
    tools = build_tools(integration_configs)
    
    if not tools:
        return ChatResponse(
            message="No integration tools available. Please connect at least one service.",
            actions_taken=[],
            raw_response=None
        )
    
    # Create and run agent
    agent = create_agent(tools)
    
    try:
        result = await agent.ainvoke({"input": message})
        
        # Parse the response
        output = result.get("output", "")
        intermediate_steps = result.get("intermediate_steps", [])
        
        # Extract actions taken
        actions_taken: list[ActionResult] = []
        for step in intermediate_steps:
            if len(step) >= 2:
                action, observation = step[0], step[1]
                tool_name = getattr(action, "tool", "unknown")
                
                # Determine service from tool name
                service = "unknown"
                if "jira" in tool_name.lower():
                    service = "jira"
                elif "gmail" in tool_name.lower() or "email" in tool_name.lower():
                    service = "gmail"
                elif "calendar" in tool_name.lower() or "event" in tool_name.lower():
                    service = "calendar"
                elif "slack" in tool_name.lower():
                    service = "slack"
                elif "notion" in tool_name.lower():
                    service = "notion"
                
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
