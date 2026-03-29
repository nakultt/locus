# Locus Backend (Production MCP + LangGraph)

This backend now executes integrations through MCP servers with a LangGraph ToolNode workflow.

## Architecture

- API layer: FastAPI routers (`/api/chat`, `/api/chat/stream`, auth/settings/conversations)
- Orchestration: `app/services/agent.py`
  - Loads MCP tools via `MultiServerMCPClient`
  - Uses `StateGraph` + `ToolNode` for tool-calling loops
  - Preserves frontend-compatible response and SSE event contracts

## Install

```bash
pip install -r requirements.txt
```

## Environment

Copy and edit:

```bash
cp .env.example .env
```

Required minimum values:

- `DATABASE_URL`
- `SECRET_KEY`
- `ENCRYPTION_KEY`
- `LLM_PROVIDER` (`gemini` by default, or `ollama` for local testing)
- `GOOGLE_API_KEY` (required when `LLM_PROVIDER=gemini`)
- OAuth values for integrations you support (`GOOGLE_*`, `LINEAR_*`)
- MCP endpoints for providers you enable (`MCP_*_URL` or stdio command)

## LLM Provider Toggle

The backend supports an internal provider switch via environment variable:

- `LLM_PROVIDER=gemini` (default)
- `LLM_PROVIDER=ollama` (local testing)

For local Ollama + Qwen 3.5 4B (no-thinking mode), set:

```env
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_FAST_MODEL=qwen3.5:4b
OLLAMA_SMART_MODEL=qwen3.5:4b
OLLAMA_DISABLE_THINKING=true
```

Then make sure the model is available locally:

```bash
ollama pull qwen3.5:4b
```

## MCP Provider Mapping

- `github` -> `MCP_GITHUB_*`
- `slack` -> `MCP_SLACK_*`
- `linear` -> `MCP_LINEAR_*`
- `jira` -> `MCP_ATLASSIAN_*`
- `notion` -> `MCP_NOTION_*`
- `gmail`, `calendar`, `docs`, `sheets`, `slides`, `drive`, `forms`, `meet` -> `MCP_GOOGLE_WORKSPACE_*`
- `bugasura` -> `MCP_BUGASURA_*`

## Reliability Controls

The orchestration service supports runtime limits:

- `MCP_TOOL_LOAD_TIMEOUT_SECONDS`
- `MCP_GRAPH_TIMEOUT_SECONDS`
- `MCP_STREAM_TIMEOUT_SECONDS`
- `MCP_MAX_ACTIONS`
- `MCP_MAX_TOOL_RESULT_CHARS`
- `MCP_SSE_RESULT_PREVIEW_CHARS`

## Run

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

## Health Endpoints

- `/health`: basic service health plus configured MCP server count
- `/health/ready`: readiness payload with non-secret MCP transport/configured status

## Frontend Compatibility

No frontend contract changes are required. Existing endpoints and stream events remain the same:

- `/api/chat`
- `/api/chat/stream`
- Stream events: `planning`, `plan`, `task_started`, `task_completed`, `task_failed`, `complete`, `error`
