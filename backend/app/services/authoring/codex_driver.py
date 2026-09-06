"""
The Codex authoring driver.

The third driver, and thin for the same reason the second is: everything that
makes autonomous mode safe -- the isolated worktree, `check_not_locus`, the
denylist enforced on the diff after the run, the size caps, the test gate, the
push with credential prompting disabled, the reviewer request -- lives in
`CliDriver` and is not reimplemented here.

**Authentication is a ChatGPT sign-in, not an API key.** `codex login` stores a
ChatGPT OAuth token in `~/.codex/auth.json` with `OPENAI_API_KEY` left null, so
a Plus or Pro subscription drives this with no key to store anywhere. Ambient,
like the other two drivers, and carrying the same cost stated rather than
hidden: every account on a deployment shares that one session, which is what
the ContextVar in `agent_runtime` exists to avoid for every other setting.

**On the sandbox flag, which is the one real decision here.** Codex ships its
own sandbox and `-s workspace-write` is the smaller grant -- it confines
model-run commands to the workspace, which is exactly what this driver needs.
It is not the default because on Windows it fails outright: the sandbox cannot
spawn a process (`CreateProcessAsUserW failed: 5 (Access is denied)`), so every
command the agent tries errors and the run ends having changed nothing while
reporting success at the process level. That is the failure mode this codebase
cares most about, so the default uses
`--dangerously-bypass-approvals-and-sandbox`, which Codex's own help describes
as "intended solely for running in environments that are externally sandboxed".

That description is accurate here, and it is the whole argument: the external
sandbox is the `git worktree` cut away from Locus's tree and from the
developer's checkout, the source path that passed the self-edit, git-repository
and origin checks, and the diff refused after the run if it touches CI
workflows, secrets or the credential path. This is the same grant OpenCode's
`--auto` and Claude Code's `bypassPermissions` already take -- not a larger
one. On a platform where Codex's sandbox works, setting the account's
invocation template to use `-s workspace-write` is strictly better, and is the
reason that template is a setting.

`--color never` is passed but is not sufficient on its own -- Codex still
emitted escape sequences with it set, because the flag governs its own
rendering and not what the tools it shells out to write. Output is captured
through a pipe and, on a failure, stored on `AuthoringAttempt.error`, which the
UI renders, so `CliDriver`'s `_plain` strips escapes from every driver's output
on the way out. The flag stays because asking is still cheaper than stripping.
"""

from __future__ import annotations

from app.services.authoring.opencode_driver import CliDriver

# `{prompt}` is the absolute path to the brief and `{workspace}` the checkout.
#
# The brief is referenced rather than inlined, as with Claude Code: `codex exec`
# takes its prompt as an argument and a context brief runs past the Windows
# command-line limit, which is why the shared path writes it to a file at all.
#
# `-C` sets the agent's working root. Passing it as well as running the process
# in the workspace is deliberate: the two are the same directory here, and
# stating it means a template someone copies elsewhere still points the agent
# at the checkout rather than at whatever it inherited.
DEFAULT_COMMAND = (
    'codex exec "Follow the brief in {prompt} and implement it. '
    'Commit your work. Do not push and do not open a pull request." '
    "-C {workspace} --dangerously-bypass-approvals-and-sandbox --color never"
)


class CodexDriver(CliDriver):
    """Codex, driven non-interactively in an isolated worktree."""

    name = "codex"
    binary = "codex"
    default_command = DEFAULT_COMMAND
    # A label rather than a guess. Codex picks its own model unless one is
    # pinned, and recording a specific name nobody selected would make
    # `AuthoringAttempt.model` a claim rather than a record.
    default_model_label = "codex-default"
