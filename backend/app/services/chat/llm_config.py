"""
The active model backend, resolved per user and bound per task.

`llm.py` used to read `LLM_PROVIDER`, the endpoint and the API key straight
out of the environment. That is right for one machine and wrong for a
product: two tenants of one deployment cannot share a `.env`, changing a
model id meant restarting the backend, and the local endpoint
(`http://127.0.0.1:8081/v1`) was hard-coded as the thing every other option
was an exception to. This module makes all of it configuration a user enters
in the UI, with the environment kept as the deployment-wide default.

**The resolved config lives in a ContextVar, for exactly the reason
credentials do.** `get_llm()` is called from thirteen places, none of which
takes a user -- the security scanner, the QA classifier and the chat agent
all just ask for a model. A module-level "current settings" dict would let
two users' background jobs overwrite each other's provider, which is the same
bug `app/core/credential_context.py` exists to prevent, one layer along, and
with a worse outcome: one tenant's diffs would be sent to another tenant's
hosted provider on their API key.

Binding happens in `get_integration_configs`, the one place every path that
reaches a model already builds its per-user state. Nothing is bound outside a
user's work, and an unbound read falls back to the environment, so the local
single-tenant deployment behaves exactly as it did.
"""

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

# Blank strings are stored as None; a field that is None means "fall back to
# the environment", which is what lets someone override the endpoint without
# also having to restate both model ids.


@dataclass(frozen=True)
class LLMConfig:
    """One user's model backend. Every field is optional; None means inherit."""

    provider: str | None = None
    base_url: str | None = None
    fast_model: str | None = None
    smart_model: str | None = None
    api_key: str | None = None
    timeout_seconds: float | None = None

    def __repr__(self) -> str:  # pragma: no cover - defensive
        # Never render the key. This object reaches log lines and tracebacks.
        return (
            f"LLMConfig(provider={self.provider!r}, base_url={self.base_url!r}, "
            f"fast_model={self.fast_model!r}, smart_model={self.smart_model!r}, "
            f"api_key={'set' if self.api_key else 'unset'})"
        )


# No mutable default and no default instance: an unset read returns None so
# `llm.py` can tell "nothing configured, use the environment" apart from "a
# user configured the empty string".
_active: ContextVar[LLMConfig | None] = ContextVar("llm_config", default=None)


def active() -> LLMConfig | None:
    """The config bound to the current task, or None outside a user's work."""
    return _active.get()


def bind(config: LLMConfig | None) -> None:
    """Bind a config for the current asyncio task."""
    _active.set(config)


def clear() -> None:
    _active.set(None)


def _clean(value: Any) -> str | None:
    """Blank and whitespace-only values are absent, not empty overrides."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def from_row(row) -> LLMConfig:
    """
    Build a config from an `LLMSetting` row, decrypting the key.

    A key that will not decrypt is treated as absent rather than raised on:
    the caller is a background loop mid-sweep, and a stored value that cannot
    be read is a configuration problem the status endpoint should report, not
    a reason for the QA poller to stop.
    """
    from app.core import security

    api_key: str | None = None
    if row.encrypted_api_key:
        try:
            api_key = _clean(security.decrypt_token(row.encrypted_api_key))
        except Exception:
            api_key = None

    return LLMConfig(
        provider=_clean(row.provider),
        base_url=_clean(row.base_url),
        fast_model=_clean(row.fast_model),
        smart_model=_clean(row.smart_model),
        api_key=api_key,
        timeout_seconds=row.timeout_seconds,
    )


def for_user(db: Session, user_id: int) -> LLMConfig | None:
    """
    The stored config for a user, or None when they have not set one.

    Swallows its own failure: this is called on every path that reaches a
    model, and a settings read that fails must degrade to the environment
    default rather than take the chat request or the analysis down with it.
    """
    try:
        from app import crud

        row = crud.get_llm_setting(db, user_id)
    except Exception:
        return None
    return from_row(row) if row else None


def bind_for_user(db: Session, user_id: int) -> LLMConfig | None:
    """Resolve and bind in one step. Returns what was bound."""
    config = for_user(db, user_id)
    bind(config)
    return config
