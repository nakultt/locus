"""MCP-backed LangGraph orchestration for chat and streaming execution."""

import asyncio
import base64
import json
import logging
import os
import shlex
import time
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Optional

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from pydantic import SecretStr

from app.schemas import ActionResult, ChatResponse
from app.services.task_planner import TaskPlan, TaskStatus, parse_tasks_from_message

load_dotenv()

logger = logging.getLogger(__name__)


def _env_float(name: str, default: float) -> float:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default
    try:
        return float(raw_value)
    except ValueError:
        logger.warning("Invalid float value for %s=%s; using default=%s", name, raw_value, default)
        return default


def _env_int(name: str, default: int) -> int:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default
    try:
        return int(raw_value)
    except ValueError:
        logger.warning("Invalid integer value for %s=%s; using default=%s", name, raw_value, default)
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default

    normalized = raw_value.lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False

    logger.warning("Invalid boolean value for %s=%s; using default=%s", name, raw_value, default)
    return default

DEFAULT_LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
if DEFAULT_LLM_PROVIDER not in {"gemini", "ollama"}:
    logger.warning("Invalid LLM_PROVIDER=%s; defaulting to gemini", DEFAULT_LLM_PROVIDER)
    DEFAULT_LLM_PROVIDER = "gemini"

FALLBACK_GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
GEMINI_FAST_MODEL = os.getenv("GEMINI_FAST_MODEL", "gemini-2.5-flash")
GEMINI_SMART_MODEL = os.getenv("GEMINI_SMART_MODEL", "gemini-2.5-pro")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_FAST_MODEL = os.getenv("OLLAMA_FAST_MODEL", os.getenv("OLLAMA_MODEL", "qwen3.5:4b"))
OLLAMA_SMART_MODEL = os.getenv("OLLAMA_SMART_MODEL", OLLAMA_FAST_MODEL)
OLLAMA_DISABLE_THINKING = _env_bool("OLLAMA_DISABLE_THINKING", True)
MCP_TOOL_LOAD_TIMEOUT_SECONDS = _env_float("MCP_TOOL_LOAD_TIMEOUT_SECONDS", 20.0)
MCP_GRAPH_TIMEOUT_SECONDS = _env_float("MCP_GRAPH_TIMEOUT_SECONDS", 120.0)
MCP_STREAM_TIMEOUT_SECONDS = _env_float("MCP_STREAM_TIMEOUT_SECONDS", 180.0)
MCP_MAX_ACTIONS = _env_int("MCP_MAX_ACTIONS", 80)
MCP_MAX_TOOL_RESULT_CHARS = _env_int("MCP_MAX_TOOL_RESULT_CHARS", 6000)
MCP_SSE_RESULT_PREVIEW_CHARS = _env_int("MCP_SSE_RESULT_PREVIEW_CHARS", 500)

GOOGLE_SERVICES = {
    "gmail",
    "calendar",
    "docs",
    "sheets",
    "slides",
    "drive",
    "forms",
    "meet",
}


@dataclass(frozen=True)
class ServiceMCPSpec:
    """Metadata used to map a connected integration to an MCP server."""

    server_name: str
    env_prefix: str
    default_url: str


SERVICE_SPECS: dict[str, ServiceMCPSpec] = {
    "github": ServiceMCPSpec(
        server_name="github",
        env_prefix="MCP_GITHUB",
        default_url="https://api.githubcopilot.com/mcp",
    ),
    "slack": ServiceMCPSpec(
        server_name="slack",
        env_prefix="MCP_SLACK",
        default_url="https://mcp.slack.com/mcp",
    ),
    "linear": ServiceMCPSpec(
        server_name="linear",
        env_prefix="MCP_LINEAR",
        default_url="https://mcp.linear.app/mcp",
    ),
    "jira": ServiceMCPSpec(
        server_name="atlassian",
        env_prefix="MCP_ATLASSIAN",
        default_url="https://mcp.atlassian.com/v1/mcp",
    ),
    "notion": ServiceMCPSpec(
        server_name="notion",
        env_prefix="MCP_NOTION",
        default_url="https://mcp.notion.com/mcp",
    ),
    "bugasura": ServiceMCPSpec(
        server_name="bugasura",
        env_prefix="MCP_BUGASURA",
        default_url="",
    ),
    "gmail": ServiceMCPSpec(
        server_name="google_workspace",
        env_prefix="MCP_GOOGLE_WORKSPACE",
        default_url="",
    ),
    "calendar": ServiceMCPSpec(
        server_name="google_workspace",
        env_prefix="MCP_GOOGLE_WORKSPACE",
        default_url="",
    ),
    "docs": ServiceMCPSpec(
        server_name="google_workspace",
        env_prefix="MCP_GOOGLE_WORKSPACE",
        default_url="",
    ),
    "sheets": ServiceMCPSpec(
        server_name="google_workspace",
        env_prefix="MCP_GOOGLE_WORKSPACE",
        default_url="",
    ),
    "slides": ServiceMCPSpec(
        server_name="google_workspace",
        env_prefix="MCP_GOOGLE_WORKSPACE",
        default_url="",
    ),
    "drive": ServiceMCPSpec(
        server_name="google_workspace",
        env_prefix="MCP_GOOGLE_WORKSPACE",
        default_url="",
    ),
    "forms": ServiceMCPSpec(
        server_name="google_workspace",
        env_prefix="MCP_GOOGLE_WORKSPACE",
        default_url="",
    ),
    "meet": ServiceMCPSpec(
        server_name="google_workspace",
        env_prefix="MCP_GOOGLE_WORKSPACE",
        default_url="",
    ),
}

SYSTEM_PROMPT = """You are Locus, an enterprise assistant that executes tasks via MCP tools.
Use only provided tools, call all required tools for multi-step requests, and summarize outcomes clearly.
If a tool fails, explain the failure and what the user should do next.
Never invent that an action succeeded without a tool result."""

SERVICE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "github": ("github", "repo", "pull_request", "pull", "octokit", "gh_"),
    "slack": ("slack", "channel"),
    "linear": ("linear",),
    "jira": ("jira", "atlassian", "rovo", "confluence", "compass"),
    "notion": ("notion",),
    "gmail": ("gmail", "email", "mail"),
    "calendar": ("calendar", "event", "schedule"),
    "docs": ("docs", "document"),
    "sheets": ("sheets", "spreadsheet", "sheet"),
    "slides": ("slides", "presentation"),
    "drive": ("drive", "file", "folder"),
    "forms": ("forms", "form", "survey"),
    "meet": ("meet", "conference", "video"),
    "bugasura": ("bugasura",),
}


def _normalize_transport(raw_transport: str) -> str:
    transport = raw_transport.strip().lower()
    if transport == "streamable_http":
        return "http"
    if transport in {"http", "sse", "stdio"}:
        return transport
    return "http"


def _parse_args(raw: str) -> list[str]:
    if not raw.strip():
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
    except json.JSONDecodeError:
        pass
    return shlex.split(raw)


def _extract_token(config: dict[str, Any]) -> str:
    api_key = str(config.get("api_key", "") or "").strip()
    if api_key:
        return api_key

    credentials = config.get("credentials")
    if isinstance(credentials, dict):
        access_token = str(credentials.get("access_token", "") or "").strip()
        if access_token:
            return access_token

    return ""


def _parse_custom_headers(env_prefix: str) -> dict[str, str]:
    raw_headers = os.getenv(f"{env_prefix}_HEADERS_JSON", "").strip()
    if not raw_headers:
        return {}

    try:
        parsed = json.loads(raw_headers)
    except json.JSONDecodeError:
        return {}

    if not isinstance(parsed, dict):
        return {}

    return {str(key): str(value) for key, value in parsed.items()}


def _build_auth_headers(service: str, config: dict[str, Any]) -> dict[str, str]:
    headers: dict[str, str] = {}
    token = _extract_token(config)

    if not token:
        return headers

    if service == "jira":
        credentials = config.get("credentials")
        email = ""
        if isinstance(credentials, dict):
            email = str(credentials.get("email", "") or "").strip()
        if email and config.get("api_key"):
            basic_secret = f"{email}:{str(config['api_key'])}".encode("utf-8")
            headers["Authorization"] = f"Basic {base64.b64encode(basic_secret).decode('utf-8')}"
            return headers

    headers["Authorization"] = f"Bearer {token}"
    return headers


def _build_server_config(
    service: str,
    spec: ServiceMCPSpec,
    config: dict[str, Any],
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    transport = _normalize_transport(os.getenv(f"{spec.env_prefix}_TRANSPORT", "http"))

    if transport == "stdio":
        command = os.getenv(f"{spec.env_prefix}_COMMAND", "").strip()
        if not command:
            return None, (
                f"{service}: set {spec.env_prefix}_COMMAND (or switch {spec.env_prefix}_TRANSPORT to http/sse)."
            )

        args = _parse_args(os.getenv(f"{spec.env_prefix}_ARGS", ""))
        server_config: dict[str, Any] = {
            "transport": "stdio",
            "command": command,
        }
        if args:
            server_config["args"] = args
        return server_config, None

    url = os.getenv(f"{spec.env_prefix}_URL", spec.default_url).strip()
    if not url:
        return None, f"{service}: configure {spec.env_prefix}_URL for this MCP server."

    server_config = {
        "transport": transport,
        "url": url,
    }

    headers = _build_auth_headers(service, config)
    headers.update(_parse_custom_headers(spec.env_prefix))
    if headers and transport in {"http", "sse"}:
        server_config["headers"] = headers

    return server_config, None


def _has_credentials(config: dict[str, Any]) -> bool:
    return bool(_extract_token(config))


def _group_services_by_server(
    integration_configs: dict[str, dict[str, Any]],
) -> dict[str, list[tuple[str, ServiceMCPSpec, dict[str, Any]]]]:
    grouped: dict[str, list[tuple[str, ServiceMCPSpec, dict[str, Any]]]] = {}
    for service, config in integration_configs.items():
        spec = SERVICE_SPECS.get(service)
        if not spec:
            continue
        grouped.setdefault(spec.server_name, []).append((service, spec, config))
    return grouped


def _build_mcp_server_configs(
    integration_configs: dict[str, dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    server_configs: dict[str, dict[str, Any]] = {}
    setup_notes: list[str] = []

    unsupported = sorted(service for service in integration_configs if service not in SERVICE_SPECS)
    if unsupported:
        setup_notes.append(
            "No MCP mapping is configured for: " + ", ".join(unsupported)
        )

    grouped = _group_services_by_server(integration_configs)

    for server_name, entries in grouped.items():
        sorted_entries = sorted(entries, key=lambda item: _has_credentials(item[2]), reverse=True)
        selected_service, spec, selected_config = sorted_entries[0]

        config, error = _build_server_config(selected_service, spec, selected_config)
        if error:
            affected_services = ", ".join(sorted(service for service, _, _ in entries))
            setup_notes.append(f"{affected_services}: {error}")
            continue

        if config:
            server_configs[server_name] = config

    return server_configs, setup_notes


def _format_setup_notes(setup_notes: list[str]) -> str:
    if not setup_notes:
        return ""
    notes = "\n".join(f"- {note}" for note in setup_notes)
    return f"Some integrations were skipped during MCP setup:\n{notes}"


async def _load_mcp_tools(
    integration_configs: dict[str, dict[str, Any]],
) -> tuple[list[BaseTool], list[str]]:
    server_configs, setup_notes = _build_mcp_server_configs(integration_configs)
    if not server_configs:
        return [], setup_notes

    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "langchain-mcp-adapters is not installed. Install backend dependencies before starting the API."
        ) from exc

    client = MultiServerMCPClient(server_configs)
    tools = await client.get_tools()
    return tools, setup_notes


def _selected_llm_provider() -> str:
    provider = os.getenv("LLM_PROVIDER", DEFAULT_LLM_PROVIDER).strip().lower()
    if provider in {"gemini", "ollama"}:
        return provider
    logger.warning("Unsupported LLM_PROVIDER=%s; using gemini", provider)
    return "gemini"


def _build_ollama_llm(model_name: str) -> ChatOllama:
    llm_kwargs: dict[str, Any] = {
        "model": model_name,
        "base_url": OLLAMA_BASE_URL,
        "temperature": 0.1,
    }

    if OLLAMA_DISABLE_THINKING:
        try:
            return ChatOllama(reasoning=False, **llm_kwargs)
        except TypeError:
            logger.warning(
                "Installed langchain-ollama does not support 'reasoning'; continuing without that flag"
            )

    return ChatOllama(**llm_kwargs)


def _get_llm(api_key: Optional[str], smart_mode: bool = False, provider: str = "gemini") -> Any:
    if provider == "ollama":
        model_name = OLLAMA_SMART_MODEL if smart_mode else OLLAMA_FAST_MODEL
        return _build_ollama_llm(model_name)

    if not api_key:
        raise ValueError(
            "No Gemini API key configured. Set GOOGLE_API_KEY or switch LLM_PROVIDER=ollama for local testing."
        )

    model_name = GEMINI_SMART_MODEL if smart_mode else GEMINI_FAST_MODEL
    return ChatGoogleGenerativeAI(
        model=model_name,
        api_key=SecretStr(api_key),
        temperature=0.1,
    )


def _build_graph(llm: Any, tools: list[BaseTool]):
    llm_with_tools = llm.bind_tools(tools)

    def call_model(state: MessagesState):
        response = llm_with_tools.invoke(state["messages"])
        return {"messages": [response]}

    builder = StateGraph(MessagesState)
    builder.add_node("call_model", call_model)
    builder.add_node("tools", ToolNode(tools))
    builder.add_edge(START, "call_model")
    builder.add_conditional_edges("call_model", tools_condition)
    builder.add_edge("tools", "call_model")
    return builder.compile()


def _content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        return json.dumps(content, ensure_ascii=True)
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, str):
                chunks.append(item)
                continue

            if isinstance(item, dict):
                text = item.get("text")
                if text is not None:
                    chunks.append(str(text))
                else:
                    chunks.append(json.dumps(item, ensure_ascii=True))
                continue

            chunks.append(str(item))

        return "\n".join(chunk for chunk in chunks if chunk)

    return str(content)


def _truncate_text(value: str, limit: int) -> str:
    if limit <= 0:
        return ""
    if len(value) <= limit:
        return value
    overflow = len(value) - limit
    return f"{value[:limit]}... [truncated {overflow} chars]"


def _is_tool_success(tool_message: ToolMessage, content_text: str) -> bool:
    status = getattr(tool_message, "status", None)
    if status == "error":
        return False

    lowered = content_text.strip().lower()
    if lowered.startswith("error"):
        return False
    if "traceback" in lowered:
        return False
    return True


def determine_service(tool_name: str, enabled_services: Optional[list[str]] = None) -> str:
    """Best-effort service detection from MCP tool names."""
    normalized = tool_name.lower()
    enabled = set(enabled_services or [])

    for service, keywords in SERVICE_KEYWORDS.items():
        if any(keyword in normalized for keyword in keywords):
            if not enabled:
                return service
            if service in enabled:
                return service
            if service in GOOGLE_SERVICES:
                for google_service in GOOGLE_SERVICES:
                    if google_service in enabled:
                        return google_service

    if len(enabled) == 1:
        return next(iter(enabled))

    return "unknown"


def _extract_tool_call_names(messages: list[Any]) -> dict[str, str]:
    names: dict[str, str] = {}
    for message in messages:
        if isinstance(message, AIMessage):
            for tool_call in message.tool_calls or []:
                call_id = str(tool_call.get("id", "") or "")
                tool_name = str(tool_call.get("name", "tool") or "tool")
                if call_id:
                    names[call_id] = tool_name
    return names


def _extract_actions_from_messages(
    messages: list[Any],
    enabled_services: list[str],
) -> list[ActionResult]:
    call_name_map = _extract_tool_call_names(messages)
    actions_taken: list[ActionResult] = []

    for message in messages:
        if not isinstance(message, ToolMessage):
            continue

        call_id = str(getattr(message, "tool_call_id", "") or "")
        tool_name = call_name_map.get(call_id, str(getattr(message, "name", "tool") or "tool"))
        content_text = _truncate_text(_content_to_text(message.content), MCP_MAX_TOOL_RESULT_CHARS)
        success = _is_tool_success(message, content_text)

        actions_taken.append(
            ActionResult(
                service=determine_service(tool_name, enabled_services),
                action=tool_name,
                success=success,
                result=content_text if success else None,
                error=None if success else content_text,
            )
        )

    return actions_taken


def _find_final_message(messages: list[Any]) -> str:
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            if message.tool_calls:
                continue
            text = _content_to_text(message.content).strip()
            if text:
                return text

    for message in reversed(messages):
        if isinstance(message, AIMessage):
            text = _content_to_text(message.content).strip()
            if text:
                return text

    return "Task execution completed."


def _build_user_prompt(message: str, enabled_services: list[str]) -> str:
    service_list = ", ".join(sorted(enabled_services)) if enabled_services else "none"
    return (
        f"Connected integrations: {service_list}.\n"
        "Use the MCP tools to complete the request.\n\n"
        f"User request: {message}"
    )


def _next_task_for_tool(task_plan: TaskPlan, service: str, used_task_ids: set[str]) -> Optional[str]:
    for task in task_plan.tasks:
        if task.id in used_task_ids:
            continue
        if task.status != TaskStatus.PENDING:
            continue
        if task.service == service:
            return task.id

    for task in task_plan.tasks:
        if task.id in used_task_ids:
            continue
        if task.status == TaskStatus.PENDING:
            return task.id

    return None


def _task_exists(task_plan: TaskPlan, task_id: str) -> bool:
    return any(task.id == task_id for task in task_plan.tasks)


async def process_chat_message(
    message: str,
    integration_configs: dict[str, dict],
    gemini_api_key: Optional[str] = None,
    smart_mode: bool = False,
) -> ChatResponse:
    """Process a chat request using MCP tools orchestrated by LangGraph."""
    provider = _selected_llm_provider()
    api_key = gemini_api_key or FALLBACK_GOOGLE_API_KEY
    if provider == "gemini" and not api_key:
        return ChatResponse(
            message=(
                "No Gemini API key configured. Please add your Gemini API key in Settings "
                "or set LLM_PROVIDER=ollama for local testing."
            ),
            actions_taken=[],
            raw_response=None,
        )

    started_at = time.perf_counter()

    available_services = sorted(
        service for service in integration_configs if service in SERVICE_SPECS
    )

    try:
        tools, setup_notes = await asyncio.wait_for(
            _load_mcp_tools(integration_configs),
            timeout=MCP_TOOL_LOAD_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        logger.warning("Timed out loading MCP tools after %ss", MCP_TOOL_LOAD_TIMEOUT_SECONDS)
        return ChatResponse(
            message=(
                "Timed out while connecting to MCP servers. "
                "Please retry or verify MCP endpoint availability."
            ),
            actions_taken=[
                ActionResult(
                    service="mcp",
                    action="load_tools",
                    success=False,
                    error="MCP tool loading timeout",
                )
            ],
            raw_response=None,
        )
    except Exception as exc:
        logger.exception("Failed to load MCP tools")
        return ChatResponse(
            message=f"I encountered an error while loading MCP tools: {exc}",
            actions_taken=[
                ActionResult(
                    service="mcp",
                    action="load_tools",
                    success=False,
                    error=str(exc),
                )
            ],
            raw_response=None,
        )

    if not tools:
        details = _format_setup_notes(setup_notes)
        suffix = f"\n\n{details}" if details else ""
        return ChatResponse(
            message=(
                "No MCP tools are available for your connected integrations. "
                "Please configure the required MCP server URLs/commands and reconnect if needed."
                f"{suffix}"
            ),
            actions_taken=[],
            raw_response=None,
        )

    try:
        llm = _get_llm(api_key, smart_mode=smart_mode, provider=provider)
    except Exception as exc:
        logger.exception("Failed to initialize LLM provider=%s", provider)
        return ChatResponse(
            message=f"I couldn't initialize the configured LLM provider ({provider}): {exc}",
            actions_taken=[
                ActionResult(
                    service="agent",
                    action="init_llm",
                    success=False,
                    error=str(exc),
                )
            ],
            raw_response=None,
        )

    graph = _build_graph(llm, tools)

    initial_state = {
        "messages": [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=_build_user_prompt(message, available_services)),
        ]
    }

    try:
        result_state = await asyncio.wait_for(
            graph.ainvoke(initial_state),
            timeout=MCP_GRAPH_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        logger.warning("Timed out executing LangGraph run after %ss", MCP_GRAPH_TIMEOUT_SECONDS)
        return ChatResponse(
            message=(
                "Timed out while executing MCP actions. "
                "Please simplify the request or retry."
            ),
            actions_taken=[
                ActionResult(
                    service="agent",
                    action="process_message",
                    success=False,
                    error="LangGraph execution timeout",
                )
            ],
            raw_response=None,
        )
    except Exception as exc:
        logger.exception("Failed during LangGraph execution")
        return ChatResponse(
            message=f"I encountered an error while processing your request: {exc}",
            actions_taken=[
                ActionResult(
                    service="agent",
                    action="process_message",
                    success=False,
                    error=str(exc),
                )
            ],
            raw_response=None,
        )

    messages = result_state.get("messages", []) if isinstance(result_state, dict) else []
    if not isinstance(messages, list):
        messages = []

    final_text = _find_final_message(messages)
    actions_taken = _extract_actions_from_messages(messages, available_services)

    setup_summary = _format_setup_notes(setup_notes)
    if setup_summary:
        final_text = f"{final_text}\n\n{setup_summary}"

    elapsed = time.perf_counter() - started_at
    logger.info(
        "Chat request completed in %.2fs with %d tool actions",
        elapsed,
        len(actions_taken),
    )

    return ChatResponse(
        message=final_text,
        actions_taken=actions_taken,
        raw_response=final_text,
    )


async def process_chat_message_streaming(
    message: str,
    integration_configs: dict[str, dict],
    gemini_api_key: Optional[str] = None,
    smart_mode: bool = False,
) -> AsyncGenerator[dict, None]:
    """Process a message and stream plan/task updates using LangGraph execution."""
    provider = _selected_llm_provider()
    api_key = gemini_api_key or FALLBACK_GOOGLE_API_KEY
    if provider == "gemini" and not api_key:
        yield {
            "event_type": "error",
            "data": {
                "message": (
                    "No Gemini API key configured. Please add your Gemini API key in Settings "
                    "or set LLM_PROVIDER=ollama for local testing."
                )
            },
        }
        return

    available_services = sorted(
        service for service in integration_configs if service in SERVICE_SPECS
    )
    started_at = time.perf_counter()

    yield {
        "event_type": "planning",
        "data": {"status": "Loading MCP tools..."},
    }

    try:
        tools, setup_notes = await asyncio.wait_for(
            _load_mcp_tools(integration_configs),
            timeout=MCP_TOOL_LOAD_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        yield {
            "event_type": "error",
            "data": {
                "message": (
                    "Timed out while connecting to MCP servers. "
                    "Please retry or verify endpoint availability."
                )
            },
        }
        return
    except Exception as exc:
        logger.exception("Failed to initialize MCP tools for streaming")
        yield {
            "event_type": "error",
            "data": {"message": f"Failed to initialize MCP tools: {exc}"},
        }
        return

    if not tools:
        details = _format_setup_notes(setup_notes)
        message_text = (
            "No MCP tools are available for your connected integrations. "
            "Please configure the required MCP server URLs/commands and reconnect if needed."
        )
        if details:
            message_text = f"{message_text}\n\n{details}"
        yield {
            "event_type": "error",
            "data": {"message": message_text},
        }
        return

    yield {
        "event_type": "planning",
        "data": {"status": "Analyzing your request..."},
    }

    task_plan = parse_tasks_from_message(message, available_services)
    if task_plan.tasks:
        yield {
            "event_type": "plan",
            "data": task_plan.to_dict(),
        }

    try:
        llm = _get_llm(api_key, smart_mode=smart_mode, provider=provider)
    except Exception as exc:
        logger.exception("Failed to initialize streaming LLM provider=%s", provider)
        yield {
            "event_type": "error",
            "data": {"message": f"Failed to initialize LLM provider ({provider}): {exc}"},
        }
        return

    graph = _build_graph(llm, tools)

    initial_state = {
        "messages": [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=_build_user_prompt(message, available_services)),
        ]
    }

    tool_call_to_task: dict[str, str] = {}
    tool_call_to_action: dict[str, str] = {}
    used_task_ids: set[str] = set()
    actions_taken: list[ActionResult] = []
    latest_messages: list[Any] = []
    processed_count = 0
    final_message = ""
    action_cap_reached = False

    try:
        async with asyncio.timeout(MCP_STREAM_TIMEOUT_SECONDS):
            async for state in graph.astream(initial_state, stream_mode="values"):
                messages = state.get("messages", []) if isinstance(state, dict) else []
                if not isinstance(messages, list):
                    continue

                latest_messages = messages
                new_messages = messages[processed_count:]

                for msg in new_messages:
                    if isinstance(msg, AIMessage):
                        if not msg.tool_calls:
                            candidate = _content_to_text(msg.content).strip()
                            if candidate:
                                final_message = candidate

                        for tool_call in msg.tool_calls or []:
                            tool_name = str(tool_call.get("name", "tool") or "tool")
                            call_id = str(tool_call.get("id", "") or f"call_{len(tool_call_to_task) + 1}")
                            service = determine_service(tool_name, available_services)

                            assigned_task_id = _next_task_for_tool(task_plan, service, used_task_ids)
                            if assigned_task_id:
                                used_task_ids.add(assigned_task_id)
                                task_plan.update_task_status(assigned_task_id, TaskStatus.IN_PROGRESS)
                            else:
                                assigned_task_id = f"task_{len(tool_call_to_task) + 1}"

                            tool_call_to_task[call_id] = assigned_task_id
                            tool_call_to_action[call_id] = tool_name

                            yield {
                                "event_type": "task_started",
                                "data": {
                                    "task_id": assigned_task_id,
                                    "service": service,
                                    "action": tool_name,
                                    "description": tool_name,
                                },
                            }

                    elif isinstance(msg, ToolMessage):
                        call_id = str(getattr(msg, "tool_call_id", "") or "")
                        tool_name = tool_call_to_action.get(
                            call_id,
                            str(getattr(msg, "name", "tool") or "tool"),
                        )
                        service = determine_service(tool_name, available_services)

                        task_id = tool_call_to_task.get(call_id, f"task_{len(actions_taken) + 1}")
                        result_text = _truncate_text(_content_to_text(msg.content), MCP_MAX_TOOL_RESULT_CHARS)
                        success = _is_tool_success(msg, result_text)

                        if _task_exists(task_plan, task_id):
                            task_plan.update_task_status(
                                task_id,
                                TaskStatus.COMPLETED if success else TaskStatus.FAILED,
                                result=result_text if success else None,
                                error=result_text if not success else None,
                            )

                        actions_taken.append(
                            ActionResult(
                                service=service,
                                action=tool_name,
                                success=success,
                                result=result_text if success else None,
                                error=result_text if not success else None,
                            )
                        )

                        yield {
                            "event_type": "task_completed" if success else "task_failed",
                            "data": {
                                "task_id": task_id,
                                "service": service,
                                "action": tool_name,
                                "result": (
                                    _truncate_text(result_text, MCP_SSE_RESULT_PREVIEW_CHARS)
                                    if success
                                    else None
                                ),
                                "error": (
                                    _truncate_text(result_text, MCP_SSE_RESULT_PREVIEW_CHARS)
                                    if not success
                                    else None
                                ),
                            },
                        }

                        if len(actions_taken) >= MCP_MAX_ACTIONS:
                            action_cap_reached = True
                            break

                processed_count = len(messages)
                if action_cap_reached:
                    break

    except TimeoutError:
        yield {
            "event_type": "error",
            "data": {
                "message": (
                    "Streaming execution timed out before completion. "
                    "Please retry with a smaller or more specific request."
                )
            },
        }
        return

    except Exception as exc:
        logger.exception("Unhandled streaming orchestration error")
        yield {
            "event_type": "error",
            "data": {"message": f"Error processing request: {exc}"},
        }
        return

    if action_cap_reached:
        yield {
            "event_type": "error",
            "data": {
                "message": (
                    f"Execution stopped after {MCP_MAX_ACTIONS} tool calls for safety. "
                    "Please split your request into smaller steps."
                )
            },
        }
        return

    if not final_message:
        final_message = _find_final_message(latest_messages)

    setup_summary = _format_setup_notes(setup_notes)
    if setup_summary:
        final_message = f"{final_message}\n\n{setup_summary}"

    total_tasks = task_plan.total if task_plan.tasks else len(actions_taken)
    completed_tasks = task_plan.completed if task_plan.tasks else sum(1 for a in actions_taken if a.success)
    failed_tasks = task_plan.failed if task_plan.tasks else sum(1 for a in actions_taken if not a.success)

    elapsed = time.perf_counter() - started_at
    logger.info(
        "Streaming chat completed in %.2fs with %d tool actions (completed=%d failed=%d)",
        elapsed,
        len(actions_taken),
        completed_tasks,
        failed_tasks,
    )

    yield {
        "event_type": "complete",
        "data": {
            "message": final_message,
            "actions_taken": [action.model_dump() for action in actions_taken],
            "total_tasks": total_tasks,
            "completed_tasks": completed_tasks,
            "failed_tasks": failed_tasks,
        },
    }

