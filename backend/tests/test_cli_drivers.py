"""
The Claude Code and Codex drivers, and what makes an additional driver safe.

Autonomous mode had exactly one driver, so `get_driver` returned either
OpenCode or a no-op and one third-party binary breaking took the whole mode
with it -- which is what happened: it hung at `init` with no output on every
model, including a purely local one and a model name that does not exist.

Almost nothing here is new behaviour -- both drivers are `CliDriver` plus four
attributes. The value of these tests is in the two places an additional driver
can go wrong: dispatch (a name that resolves to the wrong driver, or to none
when the driver is installed) and settings that are not portable between
drivers.
"""

import pytest

from app.services.authoring import agent_runtime, authoring
from app.services.authoring.claude_driver import ClaudeCodeDriver
from app.services.authoring.codex_driver import CodexDriver
from app.services.authoring.opencode_driver import CliDriver, OpenCodeDriver


@pytest.fixture(autouse=True)
def clean_runtime(monkeypatch):
    """No account bound and no environment, so each test states its own."""
    for name in (
        "LOCUS_AUTHORING_DRIVER",
        "LOCUS_AUTHORING_COMMAND",
        "LOCUS_OPENCODE_MODEL",
        "LOCUS_AUTHORING_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)
    agent_runtime.clear()
    yield
    agent_runtime.clear()


class TestDispatch:
    def test_claude_resolves_to_the_claude_driver(self):
        assert authoring.get_driver("claude").name == "claude"

    def test_opencode_still_resolves_to_opencode(self):
        assert authoring.get_driver("opencode").name == "opencode"

    def test_codex_resolves_to_the_codex_driver(self):
        assert authoring.get_driver("codex").name == "codex"

    @pytest.mark.parametrize(
        "spelling", ["claude-code", "Claude_Code", "CLAUDECODE", " claude "]
    )
    def test_familiar_spellings_are_accepted(self, spelling):
        """
        A spelling that reached `get_driver` unnormalized would resolve to the
        do-nothing driver and report "no authoring driver configured" for a
        driver that is installed.
        """
        assert agent_runtime.normalize_driver(spelling) == "claude"

    @pytest.mark.parametrize(
        "spelling", ["codex-cli", "OpenAI-Codex", " codex "]
    )
    def test_codex_spellings_are_accepted(self, spelling):
        assert agent_runtime.normalize_driver(spelling) == "codex"

    @pytest.mark.parametrize("typo", ["clude", "codx", "cloud", ""])
    def test_a_typo_still_resolves_to_nothing(self, typo):
        """
        The rule adding a driver must not weaken: guessing would run a shell in
        a checkout on the strength of a typo.
        """
        assert agent_runtime.normalize_driver(typo) is None

    def test_an_unknown_driver_is_the_do_nothing_one(self):
        assert authoring.get_driver("nope").name == "none"


class TestTheSharedMachineryIsNotReimplemented:
    """
    The reason a second driver is cheap. Every rule that makes autonomous mode
    survivable -- the isolated worktree, `check_not_locus`, the denylist on the
    diff after the run, the size caps, the test gate, the push with prompting
    disabled -- lives in `CliDriver`. A driver that reimplemented any of it
    would drift from the other one fix at a time.
    """

    def test_every_driver_is_a_cli_driver(self):
        assert issubclass(ClaudeCodeDriver, CliDriver)
        assert issubclass(CodexDriver, CliDriver)
        assert issubclass(OpenCodeDriver, CliDriver)

    @pytest.mark.parametrize("driver", [ClaudeCodeDriver, CodexDriver])
    def test_it_overrides_only_the_documented_attributes(self, driver):
        own = {name for name in vars(driver) if not name.startswith("__")}
        assert own == {"name", "binary", "default_command", "default_model_label"}

    def test_the_module_defines_no_authoring_logic(self):
        """
        A source check, because the failure it prevents is a slow one: a driver
        that grows its own copy of the denylist or the push is a driver whose
        safety rules stop matching the other's.
        """
        import pathlib

        source = (
            pathlib.Path(__file__).resolve().parent.parent
            / "app" / "services" / "authoring" / "claude_driver.py"
        ).read_text(encoding="utf-8")

        for forbidden in ("run_git", "denied_paths", "prepare_workspace", "def author"):
            assert forbidden not in source, forbidden

    def test_the_codex_module_defines_no_authoring_logic_either(self):
        import pathlib

        source = (
            pathlib.Path(__file__).resolve().parent.parent
            / "app" / "services" / "authoring" / "codex_driver.py"
        ).read_text(encoding="utf-8")

        for forbidden in ("run_git", "denied_paths", "prepare_workspace", "def author"):
            assert forbidden not in source, forbidden


class TestTheInvocation:
    def test_the_prompt_is_one_argument_not_split_into_words(self, tmp_path):
        """
        `claude -p` takes its message as a single argument. Non-posix splitting
        -- required on Windows so backslashes in paths survive -- keeps the
        quotes, so without stripping them the CLI receives a literal `"..."`
        including the quote characters.
        """
        argv = ClaudeCodeDriver().build_command(
            tmp_path / ".locus-prompt.md", tmp_path
        )

        assert argv[0] == "claude"
        assert argv[1] == "-p"
        assert not argv[2].startswith('"')
        assert ".locus-prompt.md" in argv[2]

    def test_the_brief_is_referenced_rather_than_inlined(self, tmp_path):
        """
        A context brief runs to thousands of characters, past the command-line
        limit on Windows -- the same reason the shared path writes it to a file
        at all. So the message names the file and the agent reads it.
        """
        argv = ClaudeCodeDriver().build_command(
            tmp_path / ".locus-prompt.md", tmp_path
        )

        assert str(tmp_path / ".locus-prompt.md") in argv[2]
        assert "--add-dir" in argv

    def test_it_tells_the_agent_not_to_open_the_pull_request(self, tmp_path):
        """The driver's contract is to open it. Two would be worse than none."""
        argv = ClaudeCodeDriver().build_command(
            tmp_path / ".locus-prompt.md", tmp_path
        )
        assert "do not open a pull request" in argv[2].lower()

    def test_opencode_is_unaffected_by_the_quote_stripping(self, tmp_path):
        """Its template carries no quotes, so stripping must be a no-op."""
        argv = OpenCodeDriver().build_command(
            tmp_path / ".locus-prompt.md", tmp_path
        )
        assert argv[0] == "opencode"
        assert argv[1] == "run"


class TestSettingsDoNotCrossBetweenDrivers:
    """
    The bug this feature introduced and then fixed. `command` and `model` are
    one account-level setting each, shared across drivers -- but neither value
    is portable. Selecting Claude Code with an OpenCode template still stored
    ran `opencode run ... --model opencode/muse-spark-...`, which is the
    "looks like the setting never saved" failure with a shell behind it.
    """

    def _bind(self, **kwargs):
        agent_runtime.bind(agent_runtime.AgentRuntime(**kwargs))

    def test_an_opencode_template_is_not_run_by_the_claude_driver(self, tmp_path):
        self._bind(command="opencode run --cwd {workspace} -f {prompt}")

        argv = ClaudeCodeDriver().build_command(
            tmp_path / ".locus-prompt.md", tmp_path
        )

        assert argv[0] == "claude"

    def test_an_opencode_model_is_not_recorded_against_a_claude_run(self):
        """
        A model name is one provider's catalogue entry. Recording
        `opencode/muse-spark-1.3` against a Claude Code run would make
        `AuthoringAttempt.model` a claim rather than a record, and that record
        is what makes autonomous mode auditable.
        """
        self._bind(
            command="opencode run --cwd {workspace}",
            model="opencode/muse-spark-1.3-contributor-free",
        )

        assert ClaudeCodeDriver()._model() == "claude-code-default"

    def test_a_matching_template_is_honoured(self, tmp_path):
        """
        The override still works for the driver it was written for -- this must
        not become "stored templates are ignored".
        """
        self._bind(command="claude -p {prompt} --add-dir {workspace} --verbose")

        argv = ClaudeCodeDriver().build_command(
            tmp_path / ".locus-prompt.md", tmp_path
        )

        assert argv[0] == "claude"
        assert "--verbose" in argv

    def test_a_matching_template_keeps_the_pinned_model(self, tmp_path):
        self._bind(command="claude -p {prompt}", model="claude-opus-5")

        assert ClaudeCodeDriver()._model() == "claude-opus-5"
        argv = ClaudeCodeDriver().build_command(
            tmp_path / ".locus-prompt.md", tmp_path
        )
        assert argv[-2:] == ["--model", "claude-opus-5"]

    def test_opencode_keeps_its_own_stored_settings(self, tmp_path):
        self._bind(
            command="opencode run --cwd {workspace} -f {prompt}",
            model="opencode/muse-spark-1.3-contributor-free",
        )

        assert OpenCodeDriver()._model() == "opencode/muse-spark-1.3-contributor-free"
        assert OpenCodeDriver().build_command(
            tmp_path / ".locus-prompt.md", tmp_path
        )[0] == "opencode"

    def test_no_stored_template_uses_the_drivers_own_default(self, tmp_path):
        self._bind(command=None)

        assert ClaudeCodeDriver().build_command(
            tmp_path / ".locus-prompt.md", tmp_path
        )[0] == "claude"
        assert OpenCodeDriver().build_command(
            tmp_path / ".locus-prompt.md", tmp_path
        )[0] == "opencode"


class TestTheRecordedModel:
    """
    "Every `AuthoringAttempt` records which model ran" is the claim that makes
    autonomous mode auditable, and it was false: `author()` read
    `LOCUS_OPENCODE_MODEL` from the environment while `build_command` passed
    the *account's* setting to the CLI, so an account that pinned a model had
    every attempt recorded against a different one.
    """

    def test_the_recorded_model_is_the_one_passed_to_the_cli(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("LOCUS_OPENCODE_MODEL", "from-the-environment")
        agent_runtime.bind(agent_runtime.AgentRuntime(
            command="opencode run -f {prompt} --cwd {workspace}",
            model="from-the-account",
        ))

        driver = OpenCodeDriver()
        argv = driver.build_command(tmp_path / ".locus-prompt.md", tmp_path)

        assert driver._model() == "from-the-account"
        assert argv[argv.index("--model") + 1] == "from-the-account"

    def test_no_pinned_model_records_a_label_not_a_guess(self):
        """
        Naming a specific model nobody selected would be a claim about the run
        rather than a record of it.
        """
        agent_runtime.bind(agent_runtime.AgentRuntime())

        assert ClaudeCodeDriver()._model() == "claude-code-default"
        assert OpenCodeDriver()._model() == "opencode-default"


class TestCodexInvocation:
    """
    Codex is the third driver and the one whose sandbox decision is explicit.
    """

    def test_the_prompt_is_one_argument(self, tmp_path):
        argv = CodexDriver().build_command(tmp_path / ".locus-prompt.md", tmp_path)

        assert argv[:2] == ["codex", "exec"]
        assert not argv[2].startswith('"')
        assert str(tmp_path / ".locus-prompt.md") in argv[2]

    def test_it_tells_the_agent_not_to_open_the_pull_request(self, tmp_path):
        argv = CodexDriver().build_command(tmp_path / ".locus-prompt.md", tmp_path)
        assert "do not open a pull request" in argv[2].lower()

    def test_the_working_root_is_stated(self, tmp_path):
        """
        `-C` as well as running in the workspace. The two are the same
        directory here, and stating it means a template someone copies still
        points the agent at the checkout rather than at whatever it inherited.
        """
        argv = CodexDriver().build_command(tmp_path / ".locus-prompt.md", tmp_path)
        assert argv[argv.index("-C") + 1] == str(tmp_path)

    def test_colour_is_off(self, tmp_path):
        """
        Not cosmetic: this output is stored on `AuthoringAttempt.error` and
        rendered. The flag is not sufficient on its own -- `_plain` strips what
        gets through -- but asking is cheaper than stripping.
        """
        argv = CodexDriver().build_command(tmp_path / ".locus-prompt.md", tmp_path)
        assert argv[argv.index("--color") + 1] == "never"

    def test_the_sandbox_decision_is_explicit(self, tmp_path):
        """
        Codex's own sandbox is the smaller grant and would be preferred, but on
        Windows it cannot spawn a process -- every command the agent runs fails
        while the process still exits 0, which is the "looks like success"
        shape this codebase cares most about. The bypass is what Codex's help
        calls for when the caller is externally sandboxed, which the worktree
        and the post-run denylist are.
        """
        argv = CodexDriver().build_command(tmp_path / ".locus-prompt.md", tmp_path)
        assert "--dangerously-bypass-approvals-and-sandbox" in argv


class TestOutputReachesPeopleReadable:
    """
    Agent output is not only logged: on a failure it becomes
    `AuthoringResult.error`, is stored on the attempt row, and is rendered in
    the UI. Escape codes reach a person as literal noise around the one line
    they need.
    """

    def test_escapes_are_stripped(self):
        from app.services.authoring.opencode_driver import _plain

        raw = (
            "\x1b[2mdim\x1b[0m \x1b[31mred\x1b[39m plain "
            "\x1b]8;;http://example.test\x07link\x1b]8;;\x07 end"
        )

        assert _plain(raw) == "dim red plain link end"

    def test_plain_text_is_untouched(self):
        from app.services.authoring.opencode_driver import _plain

        assert _plain("semgrep failed: exit 2") == "semgrep failed: exit 2"

    def test_asking_the_cli_is_not_relied_on(self):
        """
        Codex emitted escapes with `--color never` set, because the flag
        governs its own rendering and not what the tools it shells out to
        write. One place that cannot be missed beats three flags that can.
        """
        import pathlib

        source = (
            pathlib.Path(__file__).resolve().parent.parent
            / "app" / "services" / "authoring" / "opencode_driver.py"
        ).read_text(encoding="utf-8")

        assert source.count("_plain(") >= 3
