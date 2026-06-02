import json
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage
import httpx
import structlog

from app.schemas import ChatRequest, ChatResponse
from app.config import settings
from app.graph.agent import create_agent_graph
from app.tools import get_all_tools  # Assuming we have this function

logger = structlog.get_logger()

async def fetch_integration_configs(user_id: str) -> dict:
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{settings.rust_service_url}/api/users/{user_id}/integrations/credentials")
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.error(f"Failed to fetch integration configs for user {user_id}: {e}")
        return {}

async def fetch_gemini_key(user_id: str) -> str:
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{settings.rust_service_url}/api/users/{user_id}/settings/gemini-key")
            resp.raise_for_status()
            return resp.json().get("key")
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return None
        logger.error(f"Failed to fetch gemini key for user {user_id}: {e}")
        return None
    except Exception as e:
        logger.error(f"Failed to fetch gemini key for user {user_id}: {e}")
        return None

async def create_conversation(user_id: str, title: str = "New Conversation") -> str:
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{settings.rust_service_url}/api/users/{user_id}/conversations",
                json={"title": title}
            )
            resp.raise_for_status()
            return resp.json().get("id")
    except Exception as e:
        logger.error(f"Failed to create conversation for user {user_id}: {e}")
        return None

async def save_message(user_id: str, conversation_id: str, role: str, content: str, tools_used: list = None):
    try:
        async with httpx.AsyncClient() as client:
            payload = {
                "role": role,
                "content": content,
                "tools_used": tools_used or []
            }
            resp = await client.post(
                f"{settings.rust_service_url}/api/users/{user_id}/conversations/{conversation_id}/messages",
                json=payload
            )
            resp.raise_for_status()
    except Exception as e:
        logger.error(f"Failed to save message for conversation {conversation_id}: {e}")

app = FastAPI(title="Locus AI Service")

@app.get("/health")
async def health_check():
    return {"status": "ok"}

@app.get("/api/supported-commands")
async def get_supported_commands():
    # Return available tool commands 
    return {"commands": []}

@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    user_api_key = await fetch_gemini_key(request.user_id)
    api_key = user_api_key or settings.google_api_key
    
    if not api_key:
        raise HTTPException(status_code=400, detail="Google API key not configured. Please add it in settings.")

    if not request.integration_configs:
        request.integration_configs = await fetch_integration_configs(request.user_id)

    if not request.conversation_id:
        request.conversation_id = await create_conversation(request.user_id, request.message[:50] + "...")
        
    if request.conversation_id:
        await save_message(request.user_id, request.conversation_id, "user", request.message)

    tools = get_all_tools(request.integration_configs)
    agent = await create_agent_graph(tools, api_key)
    
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
    actions = final_state.get("actions_taken", [])
    
    if request.conversation_id and response_text:
        await save_message(request.user_id, request.conversation_id, "assistant", response_text, [a.get("tool_name") for a in actions if "tool_name" in a])
    
    return ChatResponse(
        response=response_text,
        actions_taken=actions,
        conversation_id=request.conversation_id
    )

@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest):
    user_api_key = await fetch_gemini_key(request.user_id)
    api_key = user_api_key or settings.google_api_key
    
    if not api_key:
        raise HTTPException(status_code=400, detail="Google API key not configured. Please add it in settings.")

    if not request.integration_configs:
        request.integration_configs = await fetch_integration_configs(request.user_id)

    if not request.conversation_id:
        request.conversation_id = await create_conversation(request.user_id, request.message[:50] + "...")
        
    if request.conversation_id:
        await save_message(request.user_id, request.conversation_id, "user", request.message)

    tools = get_all_tools(request.integration_configs)
    agent = await create_agent_graph(tools, api_key)
    
    initial_state = {
        "messages": [HumanMessage(content=request.message)],
        "integration_configs": request.integration_configs,
        "actions_taken": [],
        "current_task": None
    }

    async def event_generator():
        yield f"data: {json.dumps({'event_type': 'planning', 'data': {'status': 'Initializing agent...', 'conversation_id': request.conversation_id}})}\n\n"
        
        final_actions = []
        final_message = ""
        task_counter = 1
        
        async for event in agent.astream_events(initial_state, version="v2"):
            kind = event["event"]
            if kind == "on_chat_model_stream":
                chunk = event["data"]["chunk"]
                if chunk.content:
                    final_message += chunk.content
            elif kind == "on_tool_start":
                tool_name = event['name']
                task_id = str(task_counter)
                task_counter += 1
                service = tool_name.split('_')[0] if '_' in tool_name else tool_name
                action_name = tool_name.replace(service + '_', '') if tool_name.startswith(service + '_') else tool_name
                
                yield f"data: {json.dumps({'event_type': 'task_started', 'data': {'task_id': task_id, 'service': service, 'action': action_name, 'description': f'Running {tool_name}...', 'conversation_id': request.conversation_id}})}\n\n"
                
                # store task_id for on_tool_end
                event['tags'] = event.get('tags', []) + [f"task_id:{task_id}", f"service:{service}", f"action:{action_name}"]
            elif kind == "on_tool_end":
                output_str = str(event['data'].get('output'))
                tool_name = event['name']
                
                # Retrieve from parent run's tags if possible, or just generate new ones
                task_id = next((t.split(':')[1] for t in event.get('tags', []) if t.startswith('task_id:')), str(task_counter - 1))
                service = tool_name.split('_')[0] if '_' in tool_name else tool_name
                action_name = tool_name.replace(service + '_', '') if tool_name.startswith(service + '_') else tool_name
                
                success = not output_str.lower().startswith("error")
                result_str = output_str[:500] if len(output_str) > 500 else output_str
                
                final_actions.append({
                    "service": service,
                    "action": action_name,
                    "success": success,
                    "result": result_str
                })
                
                if success:
                    yield f"data: {json.dumps({'event_type': 'task_completed', 'data': {'task_id': task_id, 'result': result_str, 'conversation_id': request.conversation_id}})}\n\n"
                else:
                    yield f"data: {json.dumps({'event_type': 'task_failed', 'data': {'task_id': task_id, 'error': result_str, 'conversation_id': request.conversation_id}})}\n\n"
        
        if request.conversation_id and final_message:
            await save_message(request.user_id, request.conversation_id, "assistant", final_message, [a.get("action") or "tool" for a in final_actions])
            
        yield f"data: {json.dumps({'event_type': 'complete', 'data': {'message': final_message, 'actions_taken': final_actions, 'conversation_id': request.conversation_id}})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
