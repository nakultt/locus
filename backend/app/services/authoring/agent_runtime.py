"""
How this account's agent runs, resolved per user and bound per task.

The driver, the model, the invocation template, how much of the brief leaves
the machine, the diff bounds, the commit identity, where repositories sit and
where the agent may work were all environment variables. That made every one
of them a single operator's answer for every tenant on the deployment --
including `LOCUS_AUTHORING_CONTEXT`, which decides whether a team's internal
Slack discussion may be sent to a third party. That is a tenant's policy, not
the operator's.

**Resolution is three-layered and always in the same order:** the config bound
for the current user, then the environment variable, then the constant in the
code. A blank at any layer falls through rather than overriding with nothing,
so an account that sets only the model keeps the deployment's command
template, and a deployment that sets nothing behaves exactly as it did.

**The bound config lives in a ContextVar**, for the same reason credentials and
the model backend do (`app/core/credential_context.py`,
`app/services/chat/llm_config.py`). `AGENT_EMAIL` alone is read from six places
across two modules, none of which takes a user; threading a settings object
through all of them is a wide refactor of the one subsystem that runs a shell
in a checkout. A module-level "current settings" is the alternative and it is
the bug those two modules exist to prevent: two users' authoring runs would
overwrite each other's source root, and the loser would have its agent pointed
at the winner's code.

`get_integration_configs` binds it, which is where every path that reaches the
driver already builds its per-user state.

**None of this weakens the workspace checks.** `check_not_locus`,
`check_is_git_repo` and `check_origin_matches` run on the resolved path
whatever produced it, and the diff denylist is enforced after the run. A user
who points `code_root` at Locus's own tree gets the named configuration error
that setting `LOCUS_CODE_ROOT` there has always produced -- the checks were
never trusting the source of the value, which is what makes it safe to let a
user supply it.
"""

from __future__ import annotations

import os
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

# The constants, in one place. Each is the last layer: what a run uses when
# neither the account nor the environment says anything.
DEFAULT_DRIVER = "none"
DEFAULT_CONTEXT_MODE = "full"
DEFAULT_TIMEOUT_SECONDS = 1200
DEFAULT_MAX_CHANGED_FILES = 25
DEFAULT_MAX_CHANGED_LINES = 600
DEFAULT_MAX_OPEN_PRS = 3
DEFAULT_AGENT_NAME = "Locus"
DEFAULT_AGENT_EMAIL = "locus-agent@users.noreply.github.com"
DEFAULT_WORKSPACE_TTL_DAYS = 3
DEFAULT_CALENDAR_SWEEP_MINUTES = 30
DEFAULT_CALENDAR_LOOKAHEAD_DAYS = 14

# `none` is the do-nothing driver and stays the fallback for anything
# unrecognized. Three real drivers rather than one, because `get_driver`
# returning either OpenCode or a no-op made autonomous mode depend on a single
# third-party binary -- and one broke, hanging with no output on every model
# including a local one and a name that does not exist.
VALID_DRIVERS = ("opencode", "claude", "codex", "none")

# What a person might reasonably type or a preset might carry, mapped to the
# stored name. Normalizing on the way in rather than matching loosely at every
# read: the stored value is what `get_driver` dispatches on, and a second
# spelling reaching it would resolve to the do-nothing driver and report
# "no authoring driver configured" for a driver that is installed.
DRIVER_ALIASES = {
    "claude-code": "claude",
    "codex-cli": "codex",
    "openai-codex": "codex",
    "claude_code": "claude",
    "claudecode": "claude",
    "open-code": "opencode",
    "open_code": "opencode",
}
CONTEXT_MODES = ("full", "ticket_only")


@dataclass(frozen=True)
class AgentRuntime:
    """One account's runtime settings. None on a field means inherit."""

    driver: str | None = None
    model: str | None = None
    command: str | None = None
    context_mode: str | None = None
    timeout_seconds: int | None = None
    max_changed_files: int | None = None
    max_changed_lines: int | None = None
    max_open_prs: int | None = None
    agent_name: str | None = None
    agent_email: str | None = None
    code_root: str | None = None
    workspace_root: str | None = None
    # Tri-state, like the column: None inherits, True and False are choices.
    allow_in_place: bool | None = None
    workspace_ttl_days: int | None = None
    # Newline- or comma-separated GitHub logins, stored as typed.
    pr_reviewers: str | None = None
    calendar_sweep_minutes: int | None = None
    calendar_lookahead_days: int | None = None


_active: ContextVar[AgentRuntime | None] = ContextVar("agent_runtime", default=None)


def active() -> AgentRuntime | None:
    """The runtime bound to the current task, or None outside a user's work."""
    return _active.get()


def bind(runtime: AgentRuntime | None) -> None:
    _active.set(runtime)


def clear() -> None:
    _active.set(None)


# ------------------------------------------------------------------ parsing


def _text(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _int(value: Any) -> int | None:
    """
    A value that will not parse is absent, not zero.

    Zero is a real answer for several of these bounds and a catastrophic one
    for the rest -- a timeout of zero kills every attempt instantly -- so a
    malformed stored value must fall through to the default rather than be
    coerced into the most destructive number in the range.
    """
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _flag(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def parse_logins(value: Any) -> list[str]:
    """
    GitHub logins from a hand-typed list, one per line or comma-separated.

    A leading `@` is stripped, because that is how people write a mention and
    GitHub's API wants the bare login. Order is preserved and duplicates are
    dropped: the request is one call carrying the whole list, and GitHub
    rejects the whole of it if any entry is bad, so a login repeated on two
    lines must not become two entries.
    """
    logins: list[str] = []
    seen: set[str] = set()

    for line in str(value or "").replace(",", "\n").splitlines():
        login = line.strip().lstrip("@")
        if login and login.lower() not in seen:
            seen.add(login.lower())
            logins.append(login)

    return logins


def normalize_driver(value: str | None) -> str | None:
    """
    A recognized driver name, or None.

    An unrecognized name resolves to None rather than to a working driver:
    falling through to the do-nothing one reports "no authoring driver
    configured", where guessing would run a shell in a checkout on the
    strength of a typo. Aliases are resolved first, so a familiar spelling is
    not treated as a typo -- but only spellings of a driver that exists.
    """
    cleaned = (value or "").strip().lower()
    cleaned = DRIVER_ALIASES.get(cleaned, cleaned)
    return cleaned if cleaned in VALID_DRIVERS else None


def normalize_context_mode(value: str | None) -> str | None:
    cleaned = (value or "").strip().lower()
    return cleaned if cleaned in CONTEXT_MODES else None


# ------------------------------------------------------- layered resolution


def _resolve(field: str, env: str, default, cast=_text):
    """
    Account setting, then environment variable, then the code's constant.

    Both layers go through `cast`, not just the environment. The stored value
    is validated on write, but a row predating that validation -- or any other
    path that builds an `AgentRuntime` -- would otherwise hand an unrecognized
    driver name straight through the check that exists to stop it.
    """
    runtime = active()
    if runtime is not None:
        value = cast(getattr(runtime, field, None))
        if value is not None and value != "":
            return value

    from_env = cast(os.getenv(env))
    if from_env is not None and from_env != "":
        return from_env

    return default


def driver_name() -> str:
    value = _resolve("driver", "LOCUS_AUTHORING_DRIVER", None, normalize_driver)
    return value or DEFAULT_DRIVER


def model() -> str:
    """The pinned model, or "" to let the driver use its own."""
    return _resolve("model", "LOCUS_OPENCODE_MODEL", "") or ""


def command(default: str) -> str:
    """
    The invocation template. The caller supplies the driver's own default,
    because the template is the driver's business and this module should not
    hold a second copy of it that can drift.
    """
    return _resolve("command", "LOCUS_OPENCODE_CMD", default)


def context_mode() -> str:
    value = _resolve(
        "context_mode", "LOCUS_AUTHORING_CONTEXT", None, normalize_context_mode
    )
    return value or DEFAULT_CONTEXT_MODE


def timeout_seconds(default: int = DEFAULT_TIMEOUT_SECONDS) -> int:
    """
    The wall clock for one attempt.

    Every numeric accessor here takes the caller's own module constant as the
    last layer rather than holding a second copy of the number. The constant
    *is* the deployment default -- it is where the environment variable is read
    at import -- so duplicating it would give one setting two defaults that can
    drift, and a test patching the constant would silently not be testing what
    the code uses.
    """
    return int(_resolve(
        "timeout_seconds", "LOCUS_AUTHORING_TIMEOUT_SECONDS", default, _int,
    ))


def max_changed_files(default: int = DEFAULT_MAX_CHANGED_FILES) -> int:
    return int(_resolve(
        "max_changed_files", "LOCUS_MAX_CHANGED_FILES", default, _int,
    ))


def max_changed_lines(default: int = DEFAULT_MAX_CHANGED_LINES) -> int:
    return int(_resolve(
        "max_changed_lines", "LOCUS_MAX_CHANGED_LINES", default, _int,
    ))


def max_open_prs(default: int = DEFAULT_MAX_OPEN_PRS) -> int:
    return int(_resolve(
        "max_open_prs", "LOCUS_MAX_OPEN_AUTONOMOUS_PRS", default, _int,
    ))


def agent_name(default: str = DEFAULT_AGENT_NAME) -> str:
    return _resolve("agent_name", "LOCUS_AGENT_NAME", default)


def agent_email(default: str = DEFAULT_AGENT_EMAIL) -> str:
    return _resolve("agent_email", "LOCUS_AGENT_EMAIL", default)


def code_root() -> str:
    return _resolve("code_root", "LOCUS_CODE_ROOT", "") or ""


def workspace_root_setting() -> str:
    return _resolve("workspace_root", "LOCUS_WORKSPACE_ROOT", "") or ""


def allow_in_place() -> bool:
    value = _resolve("allow_in_place", "LOCUS_ALLOW_IN_PLACE", None, _flag)
    return bool(value)


def workspace_ttl_days(default: int = DEFAULT_WORKSPACE_TTL_DAYS) -> int:
    return int(_resolve(
        "workspace_ttl_days", "LOCUS_WORKSPACE_TTL_DAYS", default, _int,
    ))


def pr_reviewers() -> list[str]:
    """
    Who is asked to review the pull requests the agent opens.

    Empty is the meaningful default and stays the fallback: requesting a review
    from somebody who never asked for one is a notification they cannot undo,
    so this only ever does what an account explicitly typed.
    """
    return parse_logins(_resolve("pr_reviewers", "LOCUS_AUTHORING_PR_REVIEWERS", ""))


def calendar_sweep_minutes(default: int = DEFAULT_CALENDAR_SWEEP_MINUTES) -> int:
    return int(_resolve(
        "calendar_sweep_minutes", "LOCUS_CALENDAR_SWEEP_MINUTES", default, _int,
    ))


def calendar_lookahead_days(default: int = DEFAULT_CALENDAR_LOOKAHEAD_DAYS) -> int:
    return int(_resolve(
        "calendar_lookahead_days", "LOCUS_CALENDAR_LOOKAHEAD_DAYS", default, _int,
    ))


# ----------------------------------------------------------------- binding


def from_row(row) -> AgentRuntime:
    """Build a runtime from a `PRAgentDefaults` row."""
    return AgentRuntime(
        driver=normalize_driver(row.authoring_driver),
        model=_text(row.authoring_model),
        command=_text(row.authoring_command),
        context_mode=normalize_context_mode(row.authoring_context),
        timeout_seconds=_int(row.authoring_timeout_seconds),
        max_changed_files=_int(row.max_changed_files),
        max_changed_lines=_int(row.max_changed_lines),
        max_open_prs=_int(row.max_open_autonomous_prs),
        agent_name=_text(row.agent_commit_name),
        agent_email=_text(row.agent_commit_email),
        code_root=_text(row.code_root),
        workspace_root=_text(row.workspace_root),
        allow_in_place=None if row.allow_in_place is None else bool(row.allow_in_place),
        workspace_ttl_days=_int(row.workspace_ttl_days),
        pr_reviewers=_text(getattr(row, "autonomous_pr_reviewers", None)),
        calendar_sweep_minutes=_int(row.calendar_sweep_minutes),
        calendar_lookahead_days=_int(row.calendar_lookahead_days),
    )


def for_user(db: Session, user_id: int) -> AgentRuntime | None:
    """
    The stored runtime for a user, or None when they have saved none.

    Swallows its own failure for the same reason `llm_config.for_user` does:
    it runs on every path that reaches the agent, and a settings read that
    fails must degrade to the deployment default rather than take a background
    sweep down with it.
    """
    try:
        from app import models

        row = db.query(models.PRAgentDefaults).filter(
            models.PRAgentDefaults.owner_id == user_id
        ).first()
    except Exception:
        # Rolled back before returning, or the swallow is a lie on Postgres: a
        # failed statement poisons the whole session, so every later query in
        # the same request dies with "current transaction is aborted" and the
        # real cause -- an unmigrated column here -- never appears in the
        # traceback. That is what makes degrading to the deployment default
        # actually degrade rather than take the request down two frames later.
        try:
            db.rollback()
        except Exception:
            pass
        return None
    return from_row(row) if row else None


def bind_for_user(db: Session, user_id: int) -> AgentRuntime | None:
    runtime = for_user(db, user_id)
    bind(runtime)
    return runtime


def describe() -> dict[str, Any]:
    """
    Every resolved value, for the settings surface.

    Nothing here is a secret -- these are paths, bounds and a model id -- so
    unlike `llm.describe_backend` this returns the values themselves. The UI
    renders them as the placeholders under each blank field, which is what
    makes "blank inherits" legible rather than mysterious.
    """
    return {
        "driver": driver_name(),
        "model": model(),
        "command": command(""),
        "context_mode": context_mode(),
        "timeout_seconds": timeout_seconds(),
        "max_changed_files": max_changed_files(),
        "max_changed_lines": max_changed_lines(),
        "max_open_prs": max_open_prs(),
        "agent_name": agent_name(),
        "agent_email": agent_email(),
        "code_root": code_root(),
        "workspace_root": workspace_root_setting(),
        "allow_in_place": allow_in_place(),
        "workspace_ttl_days": workspace_ttl_days(),
        "pr_reviewers": pr_reviewers(),
        "calendar_sweep_minutes": calendar_sweep_minutes(),
        "calendar_lookahead_days": calendar_lookahead_days(),
    }
