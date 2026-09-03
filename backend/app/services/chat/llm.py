"""
LLM Provider
Local-first, with an explicit opt-in to a hosted provider.

By default Locus talks to a local OpenAI-compatible server — the MoE Model
Manager proxy on http://127.0.0.1:8081/v1 — and nothing it reads leaves the
machine. `LLM_PROVIDER` switches that: `openai`, `anthropic` and `gemini` send
the same prompts to a hosted API with a key you supply.

That switch is a real change in what happens to your code, not a performance
setting. The analysis models (the security scanner, the code reviewer, the QA
classifier, the asks summarizer) run automatically on every push; pointing them
at a hosted provider means diffs, Slack discussion and ticket text are sent to a
third party without anyone being asked each time. `describe_backend()` reports
which provider is active so the UI can say so plainly.

Keys are read from the environment, never from the database and never returned
by any endpoint. The status surface reports whether a key is present, not what
it is.
"""

import os

import httpx
from dotenv import load_dotenv
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

load_dotenv()

# ---------------------------------------------------------------- providers

LOCAL = "local"
OPENAI = "openai"
ANTHROPIC = "anthropic"
GEMINI = "gemini"

PROVIDERS = (LOCAL, OPENAI, ANTHROPIC, GEMINI)

# Aliases people actually type. "moe" and "moe-local" are what the local
# backend used to be called, and "claude" and "google" are the product names
# rather than the API ones.
_PROVIDER_ALIASES = {
    "moe": LOCAL,
    "moe-local": LOCAL,
    "local-moe": LOCAL,
    "openai-compatible": LOCAL,
    "claude": ANTHROPIC,
    "google": GEMINI,
    "google-gemini": GEMINI,
}

# Per-provider defaults. `smart_mode` selects the slower, stronger model.
# Every one of these is overridable with LLM_FAST_MODEL / LLM_SMART_MODEL.
_DEFAULT_MODELS = {
    OPENAI: ("gpt-4.1-mini", "gpt-4.1"),
    ANTHROPIC: ("claude-haiku-4-5-20251001", "claude-opus-5"),
    GEMINI: ("gemini-2.5-flash", "gemini-2.5-pro"),
}

# Gemini is reached through its OpenAI-compatible endpoint rather than a fourth
# SDK; Anthropic has no equivalent we rely on, so it uses langchain-anthropic.
GEMINI_BASE_URL = os.getenv(
    "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/"
)
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")

_ENV_KEYS = {
    OPENAI: "OPENAI_API_KEY",
    ANTHROPIC: "ANTHROPIC_API_KEY",
    GEMINI: "GEMINI_API_KEY",
}


def _provider() -> str:
    """The configured provider, normalized. Unknown values fall back to local."""
    raw = (os.getenv("LLM_PROVIDER") or LOCAL).strip().lower()
    raw = _PROVIDER_ALIASES.get(raw, raw)
    return raw if raw in PROVIDERS else LOCAL


def _api_key(provider: str) -> str:
    """The key for a hosted provider, or "" when none is configured."""
    if provider == LOCAL:
        # MoE requires no auth, but the OpenAI client requires a non-empty key.
        return os.getenv("MOE_API_KEY", "local")
    # GOOGLE_API_KEY is the name the Google SDKs use; accept either.
    if provider == GEMINI:
        return (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
    return (os.getenv(_ENV_KEYS[provider], "") or "").strip()


def _models(provider: str) -> tuple[str, str]:
    """(fast, smart) model ids for a provider, after env overrides."""
    if provider == LOCAL:
        fast = os.getenv("MOE_FAST_MODEL", "gemma-4-26b-a4b")
        smart = os.getenv("MOE_SMART_MODEL", "qwen3.6-35b-a3b")
    else:
        fast, smart = _DEFAULT_MODELS[provider]
    return (
        os.getenv("LLM_FAST_MODEL") or fast,
        os.getenv("LLM_SMART_MODEL") or smart,
    )


def _base_url(provider: str) -> str:
    if provider == LOCAL:
        return MOE_BASE_URL
    if provider == OPENAI:
        return OPENAI_BASE_URL
    if provider == GEMINI:
        return GEMINI_BASE_URL
    return ANTHROPIC_BASE_URL


# Base URL of the local OpenAI-compatible server (MoE Model Manager proxy).
MOE_BASE_URL = os.getenv("MOE_BASE_URL", "http://127.0.0.1:8081/v1")

# Kept as module-level names because existing code and tests read them. They
# describe the local backend specifically; use `_models()` for the active one.
MOE_FAST_MODEL = os.getenv("MOE_FAST_MODEL", "gemma-4-26b-a4b")
MOE_SMART_MODEL = os.getenv("MOE_SMART_MODEL", "qwen3.6-35b-a3b")
MOE_API_KEY = os.getenv("MOE_API_KEY", "local")

# Local generation is slower than a hosted API. A 30s default will time out
# mid-answer on an 8GB card; agent loops make several calls back to back. A
# hosted provider does not need the same headroom but is not harmed by it.
MOE_TIMEOUT_SECONDS = float(os.getenv("MOE_TIMEOUT_SECONDS", "600"))


class LLMUnavailableError(RuntimeError):
    """Raised when the configured model backend cannot serve a request."""


def _timeout() -> float:
    return float(os.getenv("LLM_TIMEOUT_SECONDS") or os.getenv("MOE_TIMEOUT_SECONDS", "600"))


def get_llm(smart_mode: bool = False, temperature: float = 0.1) -> BaseChatModel:
    """
    Create a chat model bound to the configured backend.

    Args:
        smart_mode: Use the higher-capability model when True.
        temperature: Sampling temperature.

    Raises:
        LLMUnavailableError: A hosted provider is selected with no API key set,
            or its client library is not installed. Both are configuration
            mistakes, and failing here names them — the alternative is a 401
            from a third party that reads like the provider being down.
    """
    provider = _provider()
    fast, smart = _models(provider)
    model = smart if smart_mode else fast
    key = _api_key(provider)
    timeout = _timeout()

    if provider != LOCAL and not key:
        raise LLMUnavailableError(
            f"LLM_PROVIDER={provider} but {_ENV_KEYS[provider]} is not set. "
            f"Set it in backend/.env, or set LLM_PROVIDER=local to use the "
            f"MoE Model Manager."
        )

    if provider == ANTHROPIC:
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError as e:  # pragma: no cover - depends on install extras
            raise LLMUnavailableError(
                "LLM_PROVIDER=anthropic needs langchain-anthropic. "
                "Install it with `uv sync --extra hosted`."
            ) from e

        return ChatAnthropic(
            model=model,
            api_key=key,
            base_url=ANTHROPIC_BASE_URL,
            temperature=temperature,
            timeout=timeout,
            max_retries=1,
        )

    # local, openai and gemini all speak the OpenAI wire format.
    return ChatOpenAI(
        model=model,
        base_url=_base_url(provider),
        api_key=key,
        temperature=temperature,
        timeout=timeout,
        max_retries=1,
    )


def _health_url() -> str:
    """MoE serves /health at the root, not under /v1."""
    return MOE_BASE_URL.rstrip("/").removesuffix("/v1") + "/health"


async def _check_local() -> tuple[bool, str]:
    fast, smart = _models(LOCAL)
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
                f"No text model is loaded. Open MoE Model Manager and load {fast} or {smart}."
            )

    except httpx.ConnectError:
        return False, (
            f"Cannot reach the local model server at {MOE_BASE_URL}. "
            "Start MoE Model Manager and load a text model."
        )
    except Exception as e:
        return False, f"Model server check failed: {e}"


async def _check_hosted(provider: str) -> tuple[bool, str]:
    """
    Confirm the key works, by listing models rather than by generating.

    A list call costs nothing and distinguishes the two failures worth telling
    apart: a key that is wrong (401, and no amount of waiting fixes it) and a
    provider that is unreachable.
    """
    key = _api_key(provider)
    label = {OPENAI: "OpenAI", ANTHROPIC: "Anthropic", GEMINI: "Gemini"}[provider]

    if not key:
        return False, (
            f"{label} is selected but {_ENV_KEYS[provider]} is not set in backend/.env."
        )

    if provider == ANTHROPIC:
        url = ANTHROPIC_BASE_URL.rstrip("/") + "/v1/models"
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
    else:
        url = _base_url(provider).rstrip("/") + "/models"
        headers = {"Authorization": f"Bearer {key}"}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers=headers)
    except httpx.ConnectError:
        return False, f"Cannot reach {label} at {url}."
    except Exception as e:
        return False, f"{label} check failed: {e}"

    if response.status_code in (401, 403):
        return False, f"{label} rejected the API key in {_ENV_KEYS[provider]}."
    if response.status_code != 200:
        return False, f"{label} returned HTTP {response.status_code}."

    fast, smart = _models(provider)
    return True, f"{label} is reachable. Using {fast} (fast) and {smart} (smart)."


async def check_llm_available() -> tuple[bool, str]:
    """
    Check that the configured backend can serve a request.

    Returns:
        (available, human-readable message)
    """
    provider = _provider()
    if provider == LOCAL:
        return await _check_local()
    return await _check_hosted(provider)


def describe_backend() -> dict[str, str | bool | None]:
    """
    Backend details, for the settings/status endpoint.

    Never includes the key itself — only whether one is configured, and the
    environment variable to set when it is not.
    """
    provider = _provider()
    fast, smart = _models(provider)
    return {
        "provider": "moe-local" if provider == LOCAL else provider,
        "is_local": provider == LOCAL,
        "base_url": _base_url(provider),
        "fast_model": fast,
        "smart_model": smart,
        "api_key_env": None if provider == LOCAL else _ENV_KEYS[provider],
        "api_key_configured": bool(_api_key(provider)) if provider != LOCAL else True,
    }


def available_providers() -> list[dict[str, str | bool]]:
    """
    Every provider Locus can be pointed at, and whether each is ready to use.

    The UI renders this so switching is a documented choice rather than a
    guess at environment variable names.
    """
    entries: list[dict[str, str | bool]] = []
    for provider in PROVIDERS:
        fast, smart = (
            _models(LOCAL) if provider == LOCAL else _DEFAULT_MODELS[provider]
        )
        entries.append(
            {
                "id": provider,
                "label": {
                    LOCAL: "Local (MoE Model Manager)",
                    OPENAI: "OpenAI",
                    ANTHROPIC: "Anthropic (Claude)",
                    GEMINI: "Google Gemini",
                }[provider],
                "is_local": provider == LOCAL,
                "active": provider == _provider(),
                "api_key_env": "" if provider == LOCAL else _ENV_KEYS[provider],
                "api_key_configured": True if provider == LOCAL else bool(_api_key(provider)),
                "fast_model": os.getenv("LLM_FAST_MODEL") or fast,
                "smart_model": os.getenv("LLM_SMART_MODEL") or smart,
            }
        )
    return entries
