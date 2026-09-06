"""
The Claude Code authoring driver.

The second driver, and deliberately a thin one. Everything that makes
autonomous mode safe -- the isolated worktree, `check_not_locus`, the denylist
enforced on the diff after the run, the size caps, the test gate, the push with
credential prompting disabled, the reviewer request -- lives in `CliDriver` and
is not reimplemented here. This module names the binary and its invocation.

**Why a second driver at all.** `get_driver` returned either OpenCode or a
no-op, so one CLI failing took autonomous mode with it -- and one did, hanging
at `init` with no output on every model, including a purely local one and a
model name that does not exist. A mode whose availability depends on a single
third-party binary that can break under you overnight is a mode that is off
more often than anyone intends.

**Authentication is ambient**, the same arrangement OpenCode has: whatever
`claude login` set up on the machine. Nothing is passed in the child
environment and no key is stored. The cost is stated plainly rather than hidden
-- every account on a deployment shares that one session, which is exactly what
the ContextVar in `agent_runtime` exists to avoid for every *other* setting. On
a single-operator install that is fine and is what was asked for; a
multi-tenant deployment wanting per-account credentials needs a key setting
this driver does not have. It fails loudly when the session lapses
(`OAuth session expired and could not be refreshed`, in seconds), which is
worth something on its own next to a silent hang.

**The brief is referenced, not inlined.** `claude -p` takes its message as an
argument, and a context brief runs to thousands of characters -- past the
command-line limit on Windows, which is the same reason `CliDriver` writes the
prompt to a file. So the message points at `.locus-prompt.md` in the workspace
and the agent reads it with its own tools. The file is written and removed by
the shared path, so nothing here has to know it exists beyond naming it.

`--permission-mode bypassPermissions` is not a smaller grant than OpenCode's
shell. It is the same capability held by the same compensating constraints: a
ticket a human handed over, a worktree isolated from Locus's tree and from the
developer's checkout, a source path that passed the self-edit, git-repository
and origin checks, and a diff refused afterwards if it touches CI workflows,
secrets or the credential path.
"""

from __future__ import annotations

from app.services.authoring.opencode_driver import CliDriver

# `{prompt}` is the absolute path to the brief and `{workspace}` the checkout.
#
# A template, not hard-coded flags, for the reason the OpenCode one is: a
# coding CLI's surface moves, and a driver pinning today's flags breaks on an
# upgrade with a non-zero exit and no useful message. The account-level command
# override applies to whichever driver is selected.
#
# `--add-dir` is passed as well as running in the workspace, because the agent
# is told to read a file by path and must be allowed to reach it. Pinning a
# model is left to `agent_runtime.model()`, which `build_command` appends as
# `--model` -- the same flag both CLIs use.
#
# The account's stored command and model are only honoured when the stored
# template actually invokes `claude`; see `CliDriver._own_settings`. A template
# left over from another driver is ignored rather than run, because switching
# the driver would otherwise keep executing the previous one's binary.
DEFAULT_COMMAND = (
    'claude -p "Follow the brief in {prompt} and implement it. '
    'Commit your work. Do not push and do not open a pull request." '
    "--permission-mode bypassPermissions --add-dir {workspace}"
)


class ClaudeCodeDriver(CliDriver):
    """Claude Code, driven headlessly in an isolated worktree."""

    name = "claude"
    binary = "claude"
    default_command = DEFAULT_COMMAND
    # A label rather than a guess. Claude Code picks its own model unless one
    # is pinned, and recording a specific name nobody selected would make
    # `AuthoringAttempt.model` a claim rather than a record.
    default_model_label = "claude-code-default"
