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

import os

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
    def test_it_overrides_only_the_documented_surface(self, driver):
        """
        Identity, and how this CLI spells its two knobs -- reasoning and which
        models it offers. Anything beyond this is authoring logic moving out of
        `CliDriver` and starting to drift, which is the failure a second driver
        makes possible and a third makes likely.
        """
        own = {name for name in vars(driver) if not name.startswith("__")}
        assert own <= {
            # identity
            "name", "binary", "default_command", "default_model_label",
            # how this CLI is told to think harder
            "effort_levels", "effort_args",
            # what this CLI offers in the model dropdown
            "static_model_choices", "discover_models",
        }, sorted(own)

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

    def test_the_sandbox_decision_is_explicit_and_per_platform(self, tmp_path):
        """
        Codex's own sandbox is the smaller grant and is used wherever it works.
        On Windows it cannot spawn a process -- every command the agent runs
        fails while the process still exits 0, which is the "looks like
        success" shape this codebase cares most about -- so there, and only
        there, the bypass Codex's help calls for when the caller is externally
        sandboxed (the worktree and the post-run denylist) is used instead.

        Pinned per platform rather than to the bypass everywhere, because the
        argument for the bypass is "the smaller grant is broken here" and that
        argument does not travel to a platform where it runs.
        """
        argv = CodexDriver().build_command(tmp_path / ".locus-prompt.md", tmp_path)

        if os.name == "nt":
            assert "--dangerously-bypass-approvals-and-sandbox" in argv
            assert "workspace-write" not in argv
        else:
            assert argv[argv.index("-s") + 1] == "workspace-write"
            assert "--dangerously-bypass-approvals-and-sandbox" not in argv


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


class TestPerDriverModelAndReasoning:
    """
    Model and reasoning are stored per driver, because neither value carries
    across one. A model name is one provider's catalogue entry, and the three
    CLIs spell reasoning three different ways -- `--variant`, `--effort`, and a
    `-c model_reasoning_effort=` config override -- so a single shared setting
    either reaches the wrong CLI or has to be ignored.
    """

    def _bind(self, options: dict, **kwargs):
        import json

        agent_runtime.bind(agent_runtime.AgentRuntime(
            driver_options=json.dumps(options), **kwargs
        ))

    def test_each_driver_reads_its_own_entry(self, tmp_path):
        self._bind({
            "codex": {"model": "gpt-5.6-luna"},
            "claude": {"model": "opus"},
        })

        assert CodexDriver()._model() == "gpt-5.6-luna"
        assert ClaudeCodeDriver()._model() == "opus"

    def test_one_drivers_model_never_reaches_another(self):
        """The failure this replaced: a Claude run recorded an OpenCode model."""
        self._bind({"opencode": {"model": "opencode/muse-spark-1.3"}})

        assert ClaudeCodeDriver()._model() == "claude-code-default"
        assert CodexDriver()._model() == "codex-default"

    def test_reasoning_is_spelled_the_way_each_cli_wants(self, tmp_path):
        self._bind({
            "codex": {"effort": "high"},
            "claude": {"effort": "xhigh"},
            "opencode": {"effort": "max"},
        })
        prompt = tmp_path / ".locus-prompt.md"

        codex = CodexDriver().build_command(prompt, tmp_path)
        claude = ClaudeCodeDriver().build_command(prompt, tmp_path)
        opencode = OpenCodeDriver().build_command(prompt, tmp_path)

        # Codex has no reasoning flag at all -- it is a config override, and
        # the value is TOML so it has to be quoted.
        assert codex[-2:] == ["-c", 'model_reasoning_effort="high"']
        assert claude[-2:] == ["--effort", "xhigh"]
        assert opencode[-2:] == ["--variant", "max"]

    def test_a_level_the_cli_would_reject_is_dropped(self, tmp_path):
        """
        Codex exits 1 on an unknown level, which would spend an authoring
        attempt on a typo in a settings field. `xhigh` is valid for Codex and
        Claude and not for OpenCode, so it is the case that proves the check is
        per driver rather than one shared list.
        """
        self._bind({
            "opencode": {"effort": "xhigh"},
            "codex": {"effort": "wildly-invalid"},
        })
        prompt = tmp_path / ".locus-prompt.md"

        assert "--variant" not in OpenCodeDriver().build_command(prompt, tmp_path)
        assert "-c" not in CodexDriver().build_command(prompt, tmp_path)

    def test_nothing_pinned_passes_no_flags(self, tmp_path):
        self._bind({})
        prompt = tmp_path / ".locus-prompt.md"

        argv = ClaudeCodeDriver().build_command(prompt, tmp_path)
        assert "--effort" not in argv
        assert "--model" not in argv

    def test_the_default_label_is_never_passed_as_a_model(self, tmp_path):
        """
        `claude-code-default` is what gets *recorded* when nothing is pinned.
        Passing it to `--model` would name a model that does not exist.
        """
        self._bind({})

        argv = ClaudeCodeDriver().build_command(
            tmp_path / ".locus-prompt.md", tmp_path
        )

        assert "claude-code-default" not in argv

    def test_unparseable_stored_options_are_absent_not_fatal(self):
        """
        The same rule a malformed number follows: falling through beats
        guessing, and here the guess reaches a CLI.
        """
        agent_runtime.bind(agent_runtime.AgentRuntime(driver_options="{not json"))

        assert agent_runtime.driver_options("codex") == {}
        assert CodexDriver()._model() == "codex-default"

    def test_the_legacy_pin_still_works_for_its_own_driver(self, tmp_path):
        """
        `authoring_model` predates this and must keep working, or an upgrade
        silently unpins a model someone chose.
        """
        agent_runtime.bind(agent_runtime.AgentRuntime(
            command="opencode run -f {prompt} --cwd {workspace}",
            model="opencode/muse-spark-1.3-contributor-free",
        ))

        assert OpenCodeDriver()._model() == "opencode/muse-spark-1.3-contributor-free"
        assert ClaudeCodeDriver()._model() == "claude-code-default"

    def test_a_per_driver_pin_wins_over_the_legacy_one(self):
        self._bind(
            {"opencode": {"model": "opencode/newer"}},
            command="opencode run -f {prompt}",
            model="opencode/older",
        )

        assert OpenCodeDriver()._model() == "opencode/newer"

    def test_every_driver_declares_levels_it_can_spell(self):
        """
        The form renders `effort_levels` and the driver validates against it,
        so a driver that declares a level it cannot turn into argv would offer
        a choice that silently does nothing.
        """
        for driver in (OpenCodeDriver(), ClaudeCodeDriver(), CodexDriver()):
            assert driver.effort_levels, driver.name
            for level in driver.effort_levels:
                assert driver.effort_args(level), (driver.name, level)


class TestTheModelDropdownIsNotAGuess:
    """
    The dropdown offers what the CLI actually accepts. A hand-written catalogue
    of a provider's model names would go stale the week after it was written,
    and a model id that does not exist is a failed attempt that spends the
    bound -- so each driver either asks its CLI or offers only what the CLI's
    own documentation names.
    """

    def test_claude_offers_the_aliases_its_help_documents(self):
        """
        Aliases rather than pinned version strings: an alias keeps pointing at
        the current model of its tier, where a pinned name goes stale silently
        and the settings page cannot tell you.
        """
        assert set(ClaudeCodeDriver.static_model_choices) == {
            "opus", "sonnet", "haiku", "fable",
        }

    def test_no_driver_hard_codes_a_provider_catalogue(self):
        """
        The rule, as a bound on the static lists. Not "never write model ids
        down" -- Codex has no listing command and its documented set is the
        only way to offer a useful dropdown -- but a list past a handful is
        somebody having transcribed a whole catalogue, which is the thing that
        goes stale silently.
        """
        for driver in (OpenCodeDriver, ClaudeCodeDriver, CodexDriver):
            assert len(driver.static_model_choices) <= 10, driver.name

    def test_discovery_failing_costs_the_list_and_nothing_else(self, monkeypatch):
        """
        `model_choices` renders a settings page. One of these CLIs hangs
        indefinitely on its main verb, so a driver that cannot answer must cost
        an empty dropdown rather than the page you would use to switch away
        from it.
        """
        monkeypatch.setattr(
            "app.services.authoring.opencode_driver.probe_cli",
            lambda *_a, **_kw: "",
        )

        assert OpenCodeDriver.model_choices() == []

    def test_probe_swallows_a_missing_binary(self):
        from app.services.authoring.opencode_driver import probe_cli

        assert probe_cli(["definitely-not-a-real-binary-xyz", "--help"]) == ""

    def test_choices_are_deduped_and_ordered(self, monkeypatch):
        monkeypatch.setattr(
            "app.services.authoring.opencode_driver.probe_cli",
            lambda *_a, **_kw: "a/one\na/two\na/one\n",
        )

        assert OpenCodeDriver.model_choices() == ["a/one", "a/two"]

    def test_the_capability_endpoint_never_fails_over_a_broken_cli(self, monkeypatch):
        """
        The settings page must load even when a driver's CLI is unusable.
        """
        from app.routers import webhooks

        def explode(_driver):
            raise RuntimeError("the CLI is broken")

        monkeypatch.setattr(
            OpenCodeDriver, "model_choices", classmethod(lambda cls: explode(cls))
        )

        caps = webhooks._driver_capabilities()

        assert {c.name for c in caps} == {"opencode", "claude", "codex"}
        assert next(c for c in caps if c.name == "opencode").model_choices == []


CONFIG_WITH_NEW_MODEL = 'model = "gpt-6-something-new"\nmodel_reasoning_effort = "high"\n'
CONFIG_WITH_ONLY_A_PROFILE = '[profiles.other]\nmodel = "not-selected"\n'


def _codex_home(tmp_path, monkeypatch, config: str):
    home = tmp_path / "home"
    (home / ".codex").mkdir(parents=True)
    (home / ".codex" / "config.toml").write_text(config, encoding="utf-8")
    monkeypatch.setattr("os.path.expanduser", lambda _p: str(home))
    return home


class TestCodexModelList:
    """
    Codex cannot enumerate its own models, so the list is transcribed from
    OpenAI's docs -- which makes *what is left out* the load-bearing part. A
    model id that does not exist is a failed attempt that spends the bound.
    """

    def test_retired_models_are_not_offered(self):
        """
        `gpt-5.4` and `gpt-5.4-mini` retired from Codex on 31 August 2026.
        Their documented replacements are offered in their place.
        """
        offered = set(CodexDriver.static_model_choices)

        assert "gpt-5.4" not in offered
        assert "gpt-5.4-mini" not in offered
        assert {"gpt-5.6-terra", "gpt-5.6-luna"} <= offered

    def test_models_deprecated_for_chatgpt_signin_are_not_offered(self):
        """
        ChatGPT sign-in is the only way this driver authenticates -- it exists
        precisely so that no API key is needed -- so a model deprecated for
        that sign-in is one this driver can never use.
        """
        offered = set(CodexDriver.static_model_choices)

        assert "gpt-5.2" not in offered
        assert "gpt-5.3-codex" not in offered

    def test_only_models_a_chatgpt_account_can_run_are_offered(self):
        """
        The docs list is broader than the subscription, and this driver exists
        precisely so no API key is needed. Each of these answers "not supported
        when using Codex with a ChatGPT account" despite being listed as
        recommended -- checked against the CLI, not read off the page. A
        dropdown entry that always fails costs a spent authoring attempt.
        """
        offered = set(CodexDriver.static_model_choices)

        assert offered == {"gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.5"}
        for unavailable in ("gpt-6-astra", "gpt-5.6-sol", "gpt-5.3-codex-spark"):
            assert unavailable not in offered

    def test_minimal_is_not_offered_as_a_reasoning_level(self):
        """
        Codex's generic error lists `minimal`, but the models a ChatGPT account
        can run reject it -- "'minimal' is not supported with the
        'gpt-5.6-luna' model" -- so the valid set is per model, not per CLI.
        """
        assert "minimal" not in CodexDriver.effort_levels
        assert set(CodexDriver.effort_levels) == {
            "none", "low", "medium", "high", "xhigh", "max",
        }

    def test_the_configured_model_is_offered_first(self, tmp_path, monkeypatch):
        """
        A machine already running a custom or newer model should see it at the
        top rather than have to retype it under "Other".
        """
        _codex_home(tmp_path, monkeypatch, CONFIG_WITH_NEW_MODEL)

        assert CodexDriver.model_choices()[0] == "gpt-6-something-new"

    def test_a_model_from_a_profile_section_is_not_offered(self, tmp_path, monkeypatch):
        """
        Only the top-level `model`. A `[profiles.x]` section sets one for a
        profile nobody selected, and offering it would be a name that does
        nothing.
        """
        _codex_home(tmp_path, monkeypatch, CONFIG_WITH_ONLY_A_PROFILE)

        assert "not-selected" not in CodexDriver.model_choices()

    def test_a_missing_config_costs_only_the_discovered_entry(self, tmp_path, monkeypatch):
        monkeypatch.setattr("os.path.expanduser", lambda _p: str(tmp_path / "nope"))

        assert CodexDriver.model_choices() == list(CodexDriver.static_model_choices)
