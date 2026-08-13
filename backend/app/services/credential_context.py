"""
Per-request credential isolation for the integration services.

The service modules keep their credentials in a module-level dict that the
`@tool` functions read at call time. Tool objects are module singletons, so two
users running an agent concurrently overwrote each other's tokens -- one user's
agent could post to another user's Slack.

The fix is a ContextVar per service. asyncio gives every task its own copy, so
concurrent requests cannot see each other's credentials, and each service's
module-level name is rebound to a proxy that reads from it. The 54 existing
tool bodies keep working unchanged: `_github_config.get("token")` now resolves
against the calling task's value instead of a shared dict.

A ContextVar rather than closures because it fixes all 13 services uniformly
without rewriting every tool body, and it also covers the background worker,
which runs outside any request.
"""

from collections.abc import Mapping
from contextvars import ContextVar
from typing import Any


class CredentialProxy(Mapping):
    """
    A dict-like view over a ContextVar.

    Implements Mapping so the existing `.get(...)`, `[...]`, and `in` usage in
    the service modules works untouched.
    """

    def __init__(self, name: str) -> None:
        # No mutable default: a dict passed as `default=` would be one shared
        # object across every context, reintroducing exactly the leak this
        # class exists to prevent. Unset reads return a fresh empty dict.
        self._var: ContextVar[dict[str, Any]] = ContextVar(name)

    def _current(self) -> dict[str, Any]:
        return self._var.get({})

    # -- Mapping interface, as used by the tool bodies --

    def get(self, key: str, default: Any = None) -> Any:
        return self._current().get(key, default)

    def __getitem__(self, key: str) -> Any:
        return self._current()[key]

    def __iter__(self):
        return iter(self._current())

    def __len__(self) -> int:
        return len(self._current())

    def __contains__(self, key: object) -> bool:
        return key in self._current()

    def __bool__(self) -> bool:
        return bool(self._current())

    def __repr__(self) -> str:
        # Never render values; these are live credentials.
        return f"<CredentialProxy keys={sorted(self._current())}>"

    # -- Mutation, used only by the get_*_tools factories --

    def set(self, values: dict[str, Any]) -> None:
        """Bind credentials for the current asyncio task."""
        self._var.set(dict(values))

    def clear(self) -> None:
        self._var.set({})


def install(module, attribute: str, name: str) -> CredentialProxy:
    """
    Replace a service module's credential dict with a task-local proxy.

    Args:
        module: The service module
        attribute: Name of its module-level config dict, e.g. "_github_config"
        name: Label for the ContextVar, used in debugging

    Returns:
        The proxy, so the factory can call `.set(...)` on it.
    """
    proxy = CredentialProxy(name)
    setattr(module, attribute, proxy)
    return proxy
