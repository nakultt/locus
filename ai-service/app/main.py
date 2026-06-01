import json
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage
import structlog

from app.schemas import ChatRequest, ChatResponse
from app.config import settings
from app.graph.agent import create_agent_graph
from app.tools import get_all_tools  # Assuming we have this function

logger = structlog.get_logger()

app = FastAPI(title="Locus AI Service")

@app.get("/health")
async def health_check():
    return {"status": "ok"}

@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    if not settings.google_api_key:
        raise HTTPException(status_code=500, detail="Google API key not configured")

    tools = get_all_tools(request.integration_configs)
    agent = await create_agent_graph(tools, settings.google_api_key)
    
    initial_state = {
        "messages": [HumanMessage(content=request.message)],
        "integration_configs": request.integration_configs,
        "actions_taken": [],
        "current_task": None
    }
    
    final_state = await agent.ainvoke(initial_state)
    
    # Extract the final response
    last_message = final_state["messages"][-1]
    response_text = last_message.content if hasattr(last_message, "content") else str(last_message)
    
    return ChatResponse(
        response=response_text,
        actions_taken=final_state.get("actions_taken", [])
    )

@app.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    if not settings.google_api_key:
        raise HTTPException(status_code=500, detail="Google API key not configured")

    tools = get_all_tools(request.integration_configs)
    agent = await create_agent_graph(tools, settings.google_api_key)
    
    initial_state = {
        "messages": [HumanMessage(content=request.message)],
        "integration_configs": request.integration_configs,
        "actions_taken": [],
        "current_task": None
    }

    async def event_generator():
        async for event in agent.astream_events(initial_state, version="v2"):
            kind = event["event"]
            if kind == "on_chat_model_stream":
                chunk = event["data"]["chunk"]
                if chunk.content:
                    yield f"data: {json.dumps({'type': 'token', 'content': chunk.content})}\n\n"
            elif kind == "on_tool_start":
                yield f"data: {json.dumps({'type': 'tool_start', 'tool': event['name'], 'input': event['data'].get('input')})}\n\n"
            elif kind == "on_tool_end":
                yield f"data: {json.dumps({'type': 'tool_end', 'tool': event['name'], 'output': str(event['data'].get('output'))})}\n\n"
        
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
