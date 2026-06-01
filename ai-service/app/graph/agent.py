from __future__ import annotations

import structlog
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode
from langchain_google_genai import ChatGoogleGenerativeAI

from app.graph.state import AgentState

logger = structlog.get_logger()

async def create_agent_graph(
    tools: list,
    api_key: str,
    smart_mode: bool = False,
):
    """Build a LangGraph StateGraph for multi-tool agent execution."""
    
    model_name = "gemini-2.5-pro" if smart_mode else "gemini-2.5-flash"
    llm = ChatGoogleGenerativeAI(
        model=model_name,
        google_api_key=api_key,
        temperature=0.1,
    ).bind_tools(tools)

    async def call_model(state: AgentState) -> dict:
        """LLM decides which tool to call next."""
        log = logger.bind(task=state.get("current_task"))
        response = await llm.ainvoke(state["messages"])
        
        tool_calls = getattr(response, "tool_calls", [])
        log.info("model_response", tool_calls=len(tool_calls))
        
        return {"messages": [response]}

    def should_continue(state: AgentState) -> str:
        """Route: continue calling tools or finish."""
        last = state["messages"][-1]
        if hasattr(last, "tool_calls") and last.tool_calls:
            return "tools"
        return END

    # Build the graph
    graph = StateGraph(AgentState)
    graph.add_node("agent", call_model)
    graph.add_node("tools", ToolNode(tools))
    
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")  # After tool execution, go back to agent
    
    return graph.compile()
