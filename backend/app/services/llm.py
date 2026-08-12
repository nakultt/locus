"""
LLM Provider
Local-first: talks to a MoE Model Manager (or any OpenAI-compatible) server.

Locus does not use a hosted model. All inference runs against a local
OpenAI-compatible endpoint, by default the MoE Model Manager proxy on
http://127.0.0.1:8081/v1. No API key is required; "local" is sent to satisfy
clients that insist on one.
"""

import os

import httpx
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()

# Base URL of the local OpenAI-compatible server (MoE Model Manager proxy).
MOE_BASE_URL = os.getenv("MOE_BASE_URL", "http://127.0.0.1:8081/v1")

# Model ids exposed by MoE. `smart_mode` selects the slower, stronger model.
MOE_FAST_MODEL = os.getenv("MOE_FAST_MODEL", "gemma-4-26b-a4b")
MOE_SMART_MODEL = os.getenv("MOE_SMART_MODEL", "qwen3.6-35b-a3b")

# MoE requires no auth, but the OpenAI client requires a non-empty key.
MOE_API_KEY = os.getenv("MOE_API_KEY", "local")

# Local generation is slower than a hosted API. A 30s default will time out
# mid-answer on an 8GB card; agent loops make several calls back to back.
MOE_TIMEOUT_SECONDS = float(os.getenv("MOE_TIMEOUT_SECONDS", "600"))


class LLMUnavailableError(RuntimeError):
    """Raised when the local model server is unreachable or has no model loaded."""


def get_llm(smart_mode: bool = False, temperature: float = 0.1) -> ChatOpenAI:
    """
    Create a chat model bound to the local MoE server.

    Args:
        smart_mode: Use the higher-capability model when True.
        temperature: Sampling temperature.
    """
    return ChatOpenAI(
        model=MOE_SMART_MODEL if smart_mode else MOE_FAST_MODEL,
        base_url=MOE_BASE_URL,
        api_key=MOE_API_KEY,
        temperature=temperature,
        timeout=MOE_TIMEOUT_SECONDS,
        max_retries=1,
    )


def _health_url() -> str:
    """MoE serves /health at the root, not under /v1."""
    return MOE_BASE_URL.rstrip("/").removesuffix("/v1") + "/health"


async def check_llm_available() -> tuple[bool, str]:
    """
    Check that the local model server is up and has a text model loaded.

    Returns:
        (available, human-readable message)
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(_health_url())

            if response.status_code != 200:
                return False, f"Model server returned HTTP {response.status_code}."

            health = response.json()
            text_state = health.get("text_model", "unloaded")

            if text_state == "ready":
                return True, "Local model is ready."
            if text_state == "loading":
                return False, "Model is still loading. Try again in a moment."
            if text_state == "error":
                return False, "The model runtime reported an error. Check the MoE app."

            return False, (
                "No text model is loaded. Open MoE Model Manager and load "
                f"{MOE_FAST_MODEL} or {MOE_SMART_MODEL}."
            )

    except httpx.ConnectError:
        return False, (
            f"Cannot reach the local model server at {MOE_BASE_URL}. "
            "Start MoE Model Manager and load a text model."
        )
    except Exception as e:
        return False, f"Model server check failed: {e}"


def describe_backend() -> dict[str, str | None]:
    """Backend details, for the settings/status endpoint."""
    return {
        "provider": "moe-local",
        "base_url": MOE_BASE_URL,
        "fast_model": MOE_FAST_MODEL,
        "smart_model": MOE_SMART_MODEL,
    }
