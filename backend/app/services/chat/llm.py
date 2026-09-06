"""
LLM Provider
Local-first, with an explicit opt-in to a hosted provider.

By default Locus talks to a local OpenAI-compatible server -- the MoE Model
Manager proxy on http://127.0.0.1:8081/v1 -- and nothing it reads leaves the
machine. The provider switches that: `openai`, `anthropic` and `gemini` send
the same prompts to a hosted API with a key you supply.

That switch is a real change in what happens to your code, not a performance
setting. The analysis models (the security scanner, the code reviewer, the QA
classifier, the asks summarizer) run automatically on every push; pointing them
at a hosted provider means diffs, Slack discussion and ticket text are sent to a
third party without anyone being asked each time. `describe_backend()` reports
which provider is active so the UI can say so plainly.

**Where the settings come from.** Every value here resolves in two steps: the
config bound for the current user (`llm_config`, entered in the UI and stored
encrypted), then the environment. Nothing is hard-coded to one endpoint -- the
base URL is configurable for hosted providers as well as the local one, because
vLLM, Ollama, LiteLLM, OpenRouter and an Azure deployment are all "OpenAI-
compatible at some other address". The environment remains the deployment-wide
default, so a single-tenant install that never opens the settings page behaves
exactly as it did.

A user's key is stored Fernet-encrypted and is never returned by any endpoint.
The status surface reports whether a key is present, not what it is.
"""

import os

import httpx
from dotenv import load_dotenv
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from app.services.chat import llm_config

load_dotenv()

# ---------------------------------------------------------------- providers

LOCAL = "local"
OPENAI = "openai"
ANTHROPIC = "anthropic"
GEMINI = "gemini"
OPENCODE = "opencode"

PROVIDERS = (LOCAL, OPENAI, ANTHROPIC, GEMINI, OPENCODE)

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
    "opencode": OPENCODE,
    "open-code": OPENCODE,
    "opencode-zen": OPENCODE,
    "zen": OPENCODE,
}

# Per-provider defaults. `smart_mode` selects the slower, stronger model.
# Every one of these is overridable with LLM_FAST_MODEL / LLM_SMART_MODEL.
_DEFAULT_MODELS = {
    OPENAI: ("gpt-4.1-mini", "gpt-4.1"),
    ANTHROPIC: ("claude-haiku-4-5-20251001", "claude-opus-5"),
    GEMINI: ("gemini-2.5-flash", "gemini-2.5-pro"),
    OPENCODE: ("muse-spark-1.3-contributor-free", "muse-spark-1.3-contributor-free"),
}

# Gemini is reached through its OpenAI-compatible endpoint rather than a fourth
# SDK; Anthropic has no equivalent we rely on, so it uses langchain-anthropic.
GEMINI_BASE_URL = os.getenv(
    "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/"
)
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
OPENCODE_BASE_URL = os.getenv(
    "OPENCODE_BASE_URL", "https://opencode.ai/zen/v1/responses"
)

_ENV_KEYS = {
    OPENAI: "OPENAI_API_KEY",
    ANTHROPIC: "ANTHROPIC_API_KEY",
    GEMINI: "GEMINI_API_KEY",
    OPENCODE: "OPENCODE_API_KEY",
}


def normalize_provider(raw: str | None) -> str:
    """
    Map anything a user or an env var can say to one of `PROVIDERS`.

    An unrecognized value resolves to local rather than raising: a typo must
    fail towards the backend that sends nothing off the machine, never towards
    a hosted one.
    """
    value = (raw or LOCAL).strip().lower()
    value = _PROVIDER_ALIASES.get(value, value)
    return value if value in PROVIDERS else LOCAL


def _settings():
    """The config bound for the current user, or None to use the environment."""
    return llm_config.active()


def _provider() -> str:
    """The active provider: the user's setting first, then the environment."""
    config = _settings()
    if config and config.provider:
        return normalize_provider(config.provider)
    return normalize_provider(os.getenv("LLM_PROVIDER"))


def _api_key(provider: str) -> str:
    """
    The key for a provider, or "" when none is configured.

    A stored key only applies to the provider it was entered for. Handing an
    OpenAI key to Anthropic because the user switched providers without
    clearing the field produces a 401 that reads as the provider being down.
    """
    config = _settings()
    if config and config.api_key and normalize_provider(config.provider) == provider:
        return config.api_key

    if provider == LOCAL:
        # MoE requires no auth, but the OpenAI client requires a non-empty key.
        return os.getenv("MOE_API_KEY", "local")
    # GOOGLE_API_KEY is the name the Google SDKs use; accept either.
    if provider == GEMINI:
        return (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
    return (os.getenv(_ENV_KEYS[provider], "") or "").strip()


def _models(provider: str) -> tuple[str, str]:
    """(fast, smart) model ids for a provider, after user and env overrides."""
    if provider == LOCAL:
        fast = os.getenv("MOE_FAST_MODEL", "gemma-4-26b-a4b")
        smart = os.getenv("MOE_SMART_MODEL", "qwen3.6-35b-a3b")
    else:
        fast, smart = _DEFAULT_MODELS[provider]

    fast = os.getenv("LLM_FAST_MODEL") or fast
    smart = os.getenv("LLM_SMART_MODEL") or smart

    # The user's own model ids win, and only for the provider they chose --
    # "gpt-4.1" left over from OpenAI must not be sent to a local server that
    # has never heard of it.
    config = _settings()
    if config and normalize_provider(config.provider) == provider:
        fast = config.fast_model or fast
        smart = config.smart_model or smart

    return fast, smart


def _base_url(provider: str) -> str:
    """
    The endpoint for a provider.

    Configurable for every provider, not only the local one: vLLM, Ollama,
    LiteLLM, OpenRouter and an Azure deployment are all "OpenAI-compatible at
    some other address", and a product cannot assume one of them.
    """
    config = _settings()
    if config and config.base_url and normalize_provider(config.provider) == provider:
        return config.base_url

    if provider == LOCAL:
        return os.getenv("MOE_BASE_URL", MOE_BASE_URL)
    if provider == OPENAI:
        return OPENAI_BASE_URL
    if provider == GEMINI:
        return GEMINI_BASE_URL
    if provider == OPENCODE:
        return OPENCODE_BASE_URL
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
    config = _settings()
    if config and config.timeout_seconds:
        return float(config.timeout_seconds)
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
        # Names both places a key can come from. The UI is where a tenant sets
        # one; the env var is the deployment-wide default and is what an
        # operator reading a log line will go looking for.
        raise LLMUnavailableError(
            f"Provider is {provider} but no API key is set. Add one under "
            f"Settings > System > Model backend, or set {_ENV_KEYS[provider]} "
            f"in backend/.env. Switch the provider to Local to use an "
            f"OpenAI-compatible server you run yourself."
        )

    if provider == ANTHROPIC:
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError as e:  # pragma: no cover - depends on install extras
            raise LLMUnavailableError(
                "The Anthropic provider needs langchain-anthropic. "
                "Install it with `uv sync --extra hosted`."
            ) from e

        return ChatAnthropic(
            model=model,
            api_key=key,
            base_url=_base_url(ANTHROPIC),
            temperature=temperature,
            timeout=timeout,
            max_retries=1,
        )

    if provider == OPENCODE:
        # OpenCode Zen serves generation at /responses.
        # ChatOpenAI with use_responses_api=True posts to /responses on base_url.
        base_url = _base_url(OPENCODE).rstrip("/").removesuffix("/responses")
        return ChatOpenAI(
            model=model,
            base_url=base_url,
            api_key=key,
            temperature=temperature,
            timeout=timeout,
            max_retries=1,
            use_responses_api=True,
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


def message_text(response) -> str:
    """
    The text a model returned, whatever shape the provider returned it in.

    **A message's `.content` is not a string.** It is a string on the OpenAI
    chat-completions wire format, which is what the local endpoint speaks, and
    a *list of content blocks* on the Responses API and on Anthropic. Every
    caller here used to write `content if isinstance(content, str) else
    str(content)`, which on a list stringifies the Python object -- so a parser
    expecting JSON received `[{'id': 'rs_...', 'type': 'reasoning', ...}]` and
    failed.

    That failed quietly and in the most misleading direction available at each
    site: the QA classifier reported the tester's reply as unclear, and the
    security scanner and code reviewer degraded to their error strings. The
    whole analysis half of the pipeline was dead on any provider that blocks
    its content, while every surface still rendered as though a model had read
    the code.

    Reasoning and thinking blocks are dropped rather than concatenated. They
    carry no `text` key -- a reasoning block holds `summary` and
    `encrypted_content` and an Anthropic thinking block holds `thinking` -- so
    taking `text` alone both selects the answer and excludes the scratchpad,
    which must never reach a prompt-parser or a rendered finding.
    """
    content = getattr(response, "content", response)

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        return "".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") not in ("reasoning", "thinking")
        )

    return str(content)


def _health_url() -> str:
    """MoE serves /health at the root, not under /v1."""
    return _base_url(LOCAL).rstrip("/").removesuffix("/v1") + "/health"


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
            f"Cannot reach the local model server at {_base_url(LOCAL)}. "
            "Start it, or point the endpoint at the server you run."
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
    label = {
        OPENAI: "OpenAI",
        ANTHROPIC: "Anthropic",
        GEMINI: "Gemini",
        OPENCODE: "OpenCode Zen",
    }[provider]

    if not key:
        return False, (
            f"{label} is selected but no API key is set. Add one in Settings, "
            f"or set {_ENV_KEYS[provider]} in backend/.env."
        )

    if provider == ANTHROPIC:
        url = _base_url(ANTHROPIC).rstrip("/") + "/v1/models"
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
    elif provider == OPENCODE:
        url = _base_url(OPENCODE).rstrip("/").removesuffix("/responses") + "/models"
        headers = {"Authorization": f"Bearer {key}"}
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
        return False, (
            f"{label} rejected the API key. Check it in Settings, or in "
            f"{_ENV_KEYS[provider]}."
        )
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


PROVIDER_LABELS = {
    LOCAL: "Local / self-hosted (OpenAI-compatible)",
    OPENAI: "OpenAI",
    ANTHROPIC: "Anthropic (Claude)",
    GEMINI: "Google Gemini",
    OPENCODE: "OpenCode Zen",
}


def default_base_url(provider: str) -> str:
    """
    The endpoint a provider falls back to with nothing configured.

    Rendered as the placeholder in the settings form, so the field can be left
    blank and still say what it will do -- an empty box with no hint is where
    someone types a guess.
    """
    if provider == LOCAL:
        return os.getenv("MOE_BASE_URL", MOE_BASE_URL)
    if provider == OPENAI:
        return OPENAI_BASE_URL
    if provider == GEMINI:
        return GEMINI_BASE_URL
    if provider == OPENCODE:
        return OPENCODE_BASE_URL
    return ANTHROPIC_BASE_URL


def default_models(provider: str) -> tuple[str, str]:
    """(fast, smart) ids for a provider before any per-user override."""
    if provider == LOCAL:
        return (
            os.getenv("LLM_FAST_MODEL") or os.getenv("MOE_FAST_MODEL", MOE_FAST_MODEL),
            os.getenv("LLM_SMART_MODEL") or os.getenv("MOE_SMART_MODEL", MOE_SMART_MODEL),
        )
    fast, smart = _DEFAULT_MODELS[provider]
    return os.getenv("LLM_FAST_MODEL") or fast, os.getenv("LLM_SMART_MODEL") or smart


def describe_backend() -> dict[str, str | bool | None]:
    """
    Backend details, for the settings/status endpoint.

    Never includes the key itself -- only whether one is configured, where it
    came from, and the environment variable that is the deployment-wide
    fallback when the user has not set one.
    """
    provider = _provider()
    fast, smart = _models(provider)
    config = _settings()
    from_user = bool(config and config.provider)

    return {
        "provider": "moe-local" if provider == LOCAL else provider,
        "is_local": provider == LOCAL,
        "base_url": _base_url(provider),
        "fast_model": fast,
        "smart_model": smart,
        "api_key_env": None if provider == LOCAL else _ENV_KEYS[provider],
        "api_key_configured": bool(_api_key(provider)) if provider != LOCAL else True,
        # Which of the two layers decided this. The UI says "your settings" or
        # "this deployment's default", because a value someone did not set and
        # cannot see the source of is the one they will not think to change.
        "source": "settings" if from_user else "environment",
    }


def available_providers() -> list[dict[str, str | bool]]:
    """
    Every provider Locus can be pointed at, and whether each is ready to use.

    The UI renders this as the options of the provider selector, along with the
    endpoint and model ids each one falls back to, so choosing is a visible
    choice rather than a guess at environment variable names.
    """
    entries: list[dict[str, str | bool]] = []
    active = _provider()

    for provider in PROVIDERS:
        fast, smart = default_models(provider)
        entries.append(
            {
                "id": provider,
                "label": PROVIDER_LABELS[provider],
                "is_local": provider == LOCAL,
                "active": provider == active,
                "api_key_env": "" if provider == LOCAL else _ENV_KEYS[provider],
                "api_key_configured": True if provider == LOCAL else bool(_api_key(provider)),
                "fast_model": fast,
                "smart_model": smart,
                "default_base_url": default_base_url(provider),
                # Local needs no key; every hosted one does. The form uses this
                # to require the field rather than letting a save succeed and
                # the next analysis fail with a 401.
                "needs_key": provider != LOCAL,
            }
        )
    return entries
