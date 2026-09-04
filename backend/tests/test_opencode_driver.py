"""
The OpenCode driver's decisions -- not OpenCode.

The subprocess is faked throughout. What is exercised is everything around it:
where the code is found, where the agent is allowed to write, what is refused
after the run, and which outcomes open a pull request.

Real git repositories are built on disk, because the rules being tested are
about worktrees, remotes and commit authorship, and a mock of git would only
prove the mock agrees with itself.
"""

import subprocess
from pathlib import Path

import pytest

from app.services.authoring import opencode_driver as driver
from app.services.authoring import workspace as ws
from app.services.authoring.authoring import AuthoringRequest


def git(args: list[str], cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def make_repo(path: Path, *, origin: str = "acme/api") -> Path:
    """A real repository with one commit and a plausible origin."""
    path.mkdir(parents=True, exist_ok=True)
    git(["init", "-b", "main"], path)
    git(["config", "user.email", "dev@example.com"], path)
    git(["config", "user.name", "A Developer"], path)
    (path / "README.md").write_text("hello\n")
    git(["add", "-A"], path)
    git(["commit", "-m", "initial"], path)
    git(["remote", "add", "origin", f"https://github.com/{origin}.git"], path)
    return path


def request(**kwargs) -> AuthoringRequest:
    base = dict(ticket_key="LOC-42", title="Add the thing", repo="acme/api")
    base.update(kwargs)
    return AuthoringRequest(**base)


class TestSourceResolution:
    def test_a_path_that_is_locus_own_tree_is_refused_and_named(self, monkeypatch):
        """
        The single most important rule in the feature, and with a code root it
        is the *likely* misconfiguration rather than a hypothetical: Locus at
        E:\\Github\\locus plus LOCUS_CODE_ROOT=E:\\Github resolves the `locus`
        repo to the directory holding backend/.env and ENCRYPTION_KEY.
        """
        root = ws.locus_root()

        with pytest.raises(ws.WorkspaceError) as exc:
            ws.check_not_locus(root)

        assert "Locus's own tree" in str(exc.value)
        assert "ENCRYPTION_KEY" in str(exc.value)

    def test_a_path_containing_locus_is_refused_too(self, monkeypatch):
        """Checked in both directions: the parent of Locus is just as bad."""
        with pytest.raises(ws.WorkspaceError):
            ws.check_not_locus(ws.locus_root().parent)

    def test_a_mismatched_origin_is_refused(self, tmp_path):
        """
        `<root>/<name>` is a guess from a folder name, and acme/api and
        beta/api collapse to the same directory under a flat root. Pointing the
        agent at the wrong codebase produces a confident, entirely wrong pull
        request -- worse than refusing, because it looks like success.
        """
        repo = make_repo(tmp_path / "api", origin="beta/api")

        with pytest.raises(ws.WorkspaceError) as exc:
            ws.check_origin_matches(repo, "acme/api")

        assert "beta/api" in str(exc.value)

    def test_a_matching_origin_passes_in_either_url_form(self, tmp_path):
        repo = make_repo(tmp_path / "api")
        ws.check_origin_matches(repo, "acme/api")

        git(["remote", "set-url", "origin", "git@github.com:acme/api.git"], repo)
        ws.check_origin_matches(repo, "acme/api")

    def test_a_path_that_is_not_a_repository_is_a_configuration_error(self, tmp_path):
        plain = tmp_path / "not-a-repo"
        plain.mkdir()

        with pytest.raises(ws.WorkspaceError) as exc:
            ws.check_is_git_repo(plain)

        assert "not a git repository" in str(exc.value)

    def test_root_slash_name_resolves(self, tmp_path, monkeypatch):
        make_repo(tmp_path / "api")
        monkeypatch.setenv(ws.CODE_ROOT_ENV, str(tmp_path))

        assert ws.resolve_source("acme/api", None) == tmp_path / "api"

    def test_root_slash_owner_slash_name_resolves(self, tmp_path, monkeypatch):
        """For people who nest by organisation."""
        make_repo(tmp_path / "acme" / "api")
        monkeypatch.setenv(ws.CODE_ROOT_ENV, str(tmp_path))

        assert ws.resolve_source("acme/api", None) == tmp_path / "acme" / "api"

    def test_neither_existing_falls_back_to_a_clone(self, tmp_path, monkeypatch):
        """
        A monorepo folder is a convenience, not a requirement. A repo Locus has
        never seen must still work, or the mode only functions on machines that
        happen to be set up correctly.
        """
        monkeypatch.setenv(ws.CODE_ROOT_ENV, str(tmp_path))

        assert ws.resolve_source("acme/unknown", None) is None

    def test_no_code_root_at_all_falls_back_to_a_clone(self, monkeypatch):
        monkeypatch.delenv(ws.CODE_ROOT_ENV, raising=False)

        assert ws.resolve_source("acme/api", None) is None

    def test_an_explicit_source_path_that_does_not_exist_raises(self, tmp_path):
        """
        Someone who named a path meant that path. Silently cloning a second
        copy elsewhere is how you end up debugging why your changes are not in
        your checkout.
        """
        with pytest.raises(ws.WorkspaceError):
            ws.resolve_source("acme/api", str(tmp_path / "nowhere"))

    def test_an_explicit_source_path_beats_the_root(self, tmp_path, monkeypatch):
        make_repo(tmp_path / "api")
        explicit = make_repo(tmp_path / "elsewhere" / "api")
        monkeypatch.setenv(ws.CODE_ROOT_ENV, str(tmp_path))

        assert ws.resolve_source("acme/api", str(explicit)) == explicit


class TestWorktree:
    def test_the_source_checkout_is_left_completely_untouched(
        self, tmp_path, monkeypatch
    ):
        """
        The reason isolation is not negotiable. A shared checkout can only have
        one branch out at a time, and an agent running `git checkout` in the
        directory someone is working in destroys their afternoon and looks like
        a successful run.
        """
        source = make_repo(tmp_path / "api")
        monkeypatch.setenv(ws.CODE_ROOT_ENV, str(tmp_path))
        monkeypatch.setenv(ws.WORKSPACE_ROOT_ENV, str(tmp_path / "workspaces"))
        monkeypatch.delenv(ws.ALLOW_IN_PLACE_ENV, raising=False)

        # Something uncommitted, exactly as a developer would have.
        (source / "scratch.txt").write_text("my afternoon\n")
        before = git(["rev-parse", "--abbrev-ref", "HEAD"], source).strip()

        workspace = driver.prepare_workspace(
            "acme/api",
            source_path=None,
            ticket_key="LOC-42",
            attempt=1,
            base_branch="main",
            existing_branch=None,
        )

        assert workspace.path != source
        assert workspace.path.exists()
        assert git(["rev-parse", "--abbrev-ref", "HEAD"], source).strip() == before
        assert (source / "scratch.txt").read_text() == "my afternoon\n"

        driver.remove_workspace(workspace)

    def test_the_worktree_is_removed_on_success_and_kept_on_failure(
        self, tmp_path, monkeypatch
    ):
        make_repo(tmp_path / "api")
        monkeypatch.setenv(ws.CODE_ROOT_ENV, str(tmp_path))
        monkeypatch.setenv(ws.WORKSPACE_ROOT_ENV, str(tmp_path / "workspaces"))

        workspace = driver.prepare_workspace(
            "acme/api", source_path=None, ticket_key="LOC-1", attempt=1,
            base_branch="main", existing_branch=None,
        )
        path = workspace.path
        assert path.exists()

        driver.remove_workspace(workspace)
        assert not path.exists()

    def test_a_linked_branch_is_continued_rather_than_recreated(
        self, tmp_path, monkeypatch
    ):
        """
        A rework builds on what the reviewer already read rather than starting
        over, and the ticket's Development-panel link keeps pointing at the
        right place.
        """
        source = make_repo(tmp_path / "api")
        git(["branch", "feature/LOC-42"], source)
        monkeypatch.setenv(ws.CODE_ROOT_ENV, str(tmp_path))
        monkeypatch.setenv(ws.WORKSPACE_ROOT_ENV, str(tmp_path / "workspaces"))

        workspace = driver.prepare_workspace(
            "acme/api", source_path=None, ticket_key="LOC-42", attempt=2,
            base_branch="main", existing_branch="feature/LOC-42",
        )

        assert workspace.branch == "feature/LOC-42"
        assert git(
            ["rev-parse", "--abbrev-ref", "HEAD"], workspace.path
        ).strip() == "feature/LOC-42"

        driver.remove_workspace(workspace)


class TestHumanCommits:
    def _workspace_on_branch(self, tmp_path, monkeypatch, author_email: str):
        source = make_repo(tmp_path / "api")
        git(["checkout", "-b", "feature/LOC-42"], source)
        (source / "work.py").write_text("started\n")
        git(["add", "-A"], source)
        git(["-c", f"user.email={author_email}", "-c", "user.name=Someone",
             "commit", "-m", "wip"], source)
        git(["checkout", "main"], source)

        monkeypatch.setenv(ws.CODE_ROOT_ENV, str(tmp_path))
        monkeypatch.setenv(ws.WORKSPACE_ROOT_ENV, str(tmp_path / "workspaces"))
        return driver.prepare_workspace(
            "acme/api", source_path=None, ticket_key="LOC-42", attempt=2,
            base_branch="main", existing_branch="feature/LOC-42",
        )

    def test_a_humans_commits_are_detected(self, tmp_path, monkeypatch):
        """An agent overwriting a person's work is the worst thing it can do."""
        workspace = self._workspace_on_branch(
            tmp_path, monkeypatch, "someone@example.com"
        )

        assert driver.human_commits_on(workspace, "main", "feature/LOC-42") is True

        driver.remove_workspace(workspace)

    def test_a_previous_attempts_commits_are_not_a_human(self, tmp_path, monkeypatch):
        """A rework must build on the last attempt, not refuse because of it."""
        workspace = self._workspace_on_branch(
            tmp_path, monkeypatch, driver.AGENT_EMAIL
        )

        assert driver.human_commits_on(workspace, "main", "feature/LOC-42") is False

        driver.remove_workspace(workspace)


class TestDenylist:
    def test_a_workflow_file_is_denied(self):
        """
        A model that read attacker-influenced text must not edit what CI runs.
        """
        assert driver.denied_paths([".github/workflows/ci.yml"]) == [
            ".github/workflows/ci.yml"
        ]

    @pytest.mark.parametrize("path", [
        "backend/.env", ".env", "config/.env.local",
        "certs/server.pem", "deploy/id_rsa.key",
        "backend/app/security.py",
        "backend/app/services/credential_context.py",
    ])
    def test_secrets_and_the_credential_path_are_denied(self, path):
        assert driver.denied_paths([path]) == [path]

    @pytest.mark.parametrize("path", [
        "app/environment.py", "src/keyboard.ts", "docs/pemberton.md",
        "app/services/keys.py",
    ])
    def test_innocent_lookalikes_are_allowed(self, path):
        """`.env` must not catch environment.py, or the mode is unusable."""
        assert driver.denied_paths([path]) == []

    def test_migrations_are_deliberately_allowed(self):
        """
        Schema changes are legitimate work. The review and CI gates are what
        catch a bad one.
        """
        assert driver.denied_paths(["backend/migrations/024_thing.py"]) == []


class TestPrompt:
    def test_carries_the_context_every_ask_and_the_rejection(self):
        prompt = driver.build_prompt(request(
            description="Make the button work",
            context="## Slack\nsomebody said something",
            asks=["add the word orange too", "and rename the helper"],
            rejection="the button still does nothing",
        ))

        assert "Make the button work" in prompt
        assert "somebody said something" in prompt
        assert "add the word orange too" in prompt
        assert "and rename the helper" in prompt
        assert "the button still does nothing" in prompt

    def test_says_outright_when_discussion_was_withheld(self, monkeypatch):
        """
        A reader otherwise cannot tell a missing brief from a suppressed one --
        the same reason a search that matched nothing is recorded.
        """
        monkeypatch.setenv("LOCUS_AUTHORING_CONTEXT", "ticket_only")

        prompt = driver.build_prompt(request(context="").scoped())
        assert "deliberately withheld" in prompt

    def test_tells_the_agent_not_to_open_the_pull_request(self):
        """
        The driver's contract is to open it. An agent that also opens one
        produces two.
        """
        prompt = driver.build_prompt(request())
        assert "do not open a pull request" in prompt.lower()


class TestCommand:
    def test_is_a_template_not_hard_coded_flags(self, monkeypatch):
        """
        OpenCode's CLI surface moves, and a driver pinning today's flags breaks
        on an upgrade with a non-zero exit and no useful message.
        """
        monkeypatch.setenv("LOCUS_OPENCODE_CMD", "my-agent --file {prompt}")
        monkeypatch.delenv("LOCUS_OPENCODE_MODEL", raising=False)

        # The rendered path is compared as the platform writes it. Hard-coding
        # the POSIX form asserted the separator rather than the template, and
        # failed on Windows -- where this driver is expected to run, since the
        # source root and workspace root are both native paths.
        prompt = Path("/tmp/p.md")
        assert driver.build_command(prompt, Path("/tmp/w")) == [
            "my-agent", "--file", str(prompt)
        ]

    def test_the_model_is_opencode_own_unless_pinned(self, monkeypatch):
        monkeypatch.delenv("LOCUS_OPENCODE_CMD", raising=False)
        monkeypatch.delenv("LOCUS_OPENCODE_MODEL", raising=False)

        assert "--model" not in driver.build_command(Path("/p"), Path("/w"))

        monkeypatch.setenv("LOCUS_OPENCODE_MODEL", "some-model")
        assert "--model" in driver.build_command(Path("/p"), Path("/w"))


class TestPullRequestBody:
    def test_names_the_driver_and_the_model_first(self):
        """
        Knowing a diff was model-written is material to how carefully it is
        read, and hiding it is the most dishonest thing this feature could do.
        """
        body = driver.build_pr_body(
            request(), driver="opencode", model="some-model-v2",
            test_failure=None, doc_url=None,
        )

        assert body.splitlines()[0].startswith("> **Machine-authored.**")
        assert "opencode" in body
        assert "some-model-v2" in body

    def test_a_github_issue_gets_a_closing_keyword(self):
        """So `get_linked_issues` finds it."""
        body = driver.build_pr_body(
            request(ticket_key="acme/api#7"), driver="opencode", model=None,
            test_failure=None, doc_url=None,
        )

        assert "Closes acme/api#7" in body

    def test_a_failing_final_attempt_states_the_failure(self):
        """
        Opening nothing after three tries leaves the human with silence, which
        reads as the feature being broken. A failing PR they can see is
        strictly better as long as it is labelled -- and the merge gate
        requires green CI, so it cannot land.
        """
        body = driver.build_pr_body(
            request(), driver="opencode", model=None,
            test_failure="FAILED tests/test_thing.py::test_it", doc_url=None,
        )

        assert "test gate failed" in body.lower()
        assert "test_thing.py" in body

    def test_carries_the_report_link(self):
        body = driver.build_pr_body(
            request(), driver="opencode", model=None, test_failure=None,
            doc_url="https://docs.google.com/document/d/abc/edit",
        )

        assert "https://docs.google.com/document/d/abc/edit" in body

    def test_names_the_asks_it_is_responding_to(self):
        body = driver.build_pr_body(
            request(
                attempt=2, trigger="changes_requested",
                asks=["add the word orange too"],
            ),
            driver="opencode", model=None, test_failure=None, doc_url=None,
        )

        assert "attempt 2" in body
        assert "add the word orange too" in body


# --- The run, end to end ---------------------------------------------------


@pytest.fixture
def bare_origin(tmp_path):
    """
    A bare repository standing in for GitHub, so pushes actually go somewhere.

    Without a real remote the push step cannot be exercised, and the push is
    where "the branch moved under us" is detected.
    """
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(origin)], check=True,
                   capture_output=True)

    source = make_repo(tmp_path / "api")
    git(["remote", "set-url", "origin", str(origin)], source)
    git(["push", "-u", "origin", "main"], source)
    return source


@pytest.fixture
def configured(bare_origin, tmp_path, monkeypatch):
    monkeypatch.setenv(ws.CODE_ROOT_ENV, str(tmp_path))
    monkeypatch.setenv(ws.WORKSPACE_ROOT_ENV, str(tmp_path / "workspaces"))
    monkeypatch.delenv(ws.ALLOW_IN_PLACE_ENV, raising=False)
    monkeypatch.delenv("LOCUS_AUTHORING_CONTEXT", raising=False)

    # The origin check compares against the URL, which is now a path. Point the
    # check at what this fixture actually built.
    monkeypatch.setattr(ws, "check_origin_matches", lambda path, repo: None)
    return bare_origin


def fake_agent(writes: dict[str, str] | None = None, *, returncode: int = 0,
               output: str = "done"):
    """An agent that writes the given files into the worktree, then exits."""

    async def run(command, workspace, timeout=None):
        for name, content in (writes or {}).items():
            target = Path(workspace) / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        return returncode, output

    return run


def opened_pr(number: int = 42):
    async def create(token, repo, **kwargs):
        return {"number": number, "html_url": f"https://github.invalid/pr/{number}"}

    return create


@pytest.fixture
def github(monkeypatch):
    from app.services.integrations import github_pr

    async def default_branch(token, repo):
        return "main"

    monkeypatch.setattr(github_pr, "get_default_branch", default_branch)
    monkeypatch.setattr(github_pr, "create_pull_request", opened_pr())
    return github_pr


CONFIGS = {"github": {"token": "t"}}


class TestAuthorRun:
    @pytest.mark.asyncio
    async def test_a_clean_run_opens_the_pull_request(
        self, configured, github, monkeypatch
    ):
        monkeypatch.setattr(driver, "run_agent", fake_agent({"feature.py": "ok\n"}))

        result = await driver.OpenCodeDriver().author(request(), CONFIGS)

        assert result.opened is True
        assert result.pr_number == 42
        assert result.files_changed == 1
        assert result.error is None

    @pytest.mark.asyncio
    async def test_an_empty_diff_opens_no_pull_request(
        self, configured, github, monkeypatch
    ):
        """
        An empty pull request puts a reviewer's name on a request to read a
        diff that does not exist.
        """
        monkeypatch.setattr(driver, "run_agent", fake_agent({}))

        result = await driver.OpenCodeDriver().author(request(), CONFIGS)

        assert result.opened is False
        assert "no changes" in result.error

    @pytest.mark.asyncio
    async def test_a_denylisted_path_aborts_and_opens_nothing(
        self, configured, github, monkeypatch
    ):
        """
        It does not open a PR with those files reverted: a run that tried is a
        signal worth surfacing, and editing the agent's diff means the reviewer
        reads something the agent did not produce.
        """
        monkeypatch.setattr(driver, "run_agent", fake_agent({
            "feature.py": "ok\n",
            ".github/workflows/ci.yml": "on: push\n",
        }))

        result = await driver.OpenCodeDriver().author(request(), CONFIGS)

        assert result.opened is False
        assert ".github/workflows/ci.yml" in result.error

    @pytest.mark.asyncio
    async def test_a_diff_over_the_file_cap_records_the_measurement(
        self, configured, github, monkeypatch
    ):
        """
        Not retried with a smaller scope: the ticket was too big for the mode,
        which is information the human should get.
        """
        monkeypatch.setenv("LOCUS_MAX_CHANGED_FILES", "2")
        monkeypatch.setattr(driver, "run_agent", fake_agent(
            {f"f{n}.py": "x\n" for n in range(5)}
        ))

        result = await driver.OpenCodeDriver().author(request(), CONFIGS)

        assert result.opened is False
        assert "too large to review" in result.error
        assert result.files_changed == 5

    @pytest.mark.asyncio
    async def test_a_non_zero_exit_is_recorded_with_its_output(
        self, configured, github, monkeypatch
    ):
        monkeypatch.setattr(
            driver, "run_agent",
            fake_agent({}, returncode=3, output="model unavailable"),
        )

        result = await driver.OpenCodeDriver().author(request(), CONFIGS)

        assert result.opened is False
        assert "exited 3" in result.error
        assert "model unavailable" in result.error

    @pytest.mark.asyncio
    async def test_a_timeout_is_recorded_as_one(
        self, configured, github, monkeypatch
    ):
        monkeypatch.setattr(
            driver, "run_agent",
            fake_agent({}, returncode=124, output="Timed out after 1200s"),
        )

        result = await driver.OpenCodeDriver().author(request(), CONFIGS)

        assert result.opened is False
        assert "Timed out" in result.error

    @pytest.mark.asyncio
    async def test_prepare_command_failing_stops_before_the_model_runs(
        self, configured, github, monkeypatch
    ):
        """The cheapest possible place to find out the environment is wrong."""
        invoked = []

        async def never(command, workspace, timeout=None):
            invoked.append(command)
            return 0, ""

        monkeypatch.setattr(driver, "run_agent", never)

        result = await driver.OpenCodeDriver().author(
            request(settings={"prepare_command": "exit 7"}), CONFIGS
        )

        assert result.opened is False
        assert "prepare_command failed" in result.error
        assert invoked == []

    @pytest.mark.asyncio
    async def test_the_test_gate_failing_with_attempts_left_opens_nothing(
        self, configured, github, monkeypatch
    ):
        monkeypatch.setattr(driver, "run_agent", fake_agent({"feature.py": "ok\n"}))

        result = await driver.OpenCodeDriver().author(
            request(settings={"test_command": "exit 1", "attempts_remaining": 2}),
            CONFIGS,
        )

        assert result.opened is False
        assert "test gate failed" in result.error

    @pytest.mark.asyncio
    async def test_the_test_gate_failing_on_the_last_attempt_opens_it_anyway(
        self, configured, github, monkeypatch
    ):
        """
        Opening nothing after three tries leaves the human with silence, which
        reads as the feature being broken.
        """
        bodies = {}

        async def capture(token, repo, **kwargs):
            bodies.update(kwargs)
            return {"number": 43, "html_url": "https://github.invalid/pr/43"}

        monkeypatch.setattr(github, "create_pull_request", capture)
        monkeypatch.setattr(driver, "run_agent", fake_agent({"feature.py": "ok\n"}))

        result = await driver.OpenCodeDriver().author(
            request(settings={"test_command": "exit 1", "attempts_remaining": 0}),
            CONFIGS,
        )

        assert result.opened is True
        assert "test gate failed" in bodies["body"].lower()

    @pytest.mark.asyncio
    async def test_human_commits_hand_the_work_item_back_without_running(
        self, configured, github, monkeypatch
    ):
        git(["checkout", "-b", "feature/LOC-42"], configured)
        (configured / "theirs.py").write_text("mine\n")
        git(["add", "-A"], configured)
        git(["-c", "user.email=someone@example.com", "-c", "user.name=S",
             "commit", "-m", "wip"], configured)
        git(["push", "-u", "origin", "feature/LOC-42"], configured)
        git(["checkout", "main"], configured)

        invoked = []

        async def never(command, workspace, timeout=None):
            invoked.append(command)
            return 0, ""

        monkeypatch.setattr(driver, "run_agent", never)

        result = await driver.OpenCodeDriver().author(
            request(existing_branch="feature/LOC-42"), CONFIGS
        )

        assert result.opened is False
        assert result.hand_back_reason
        assert "already started" in result.hand_back_reason
        assert invoked == []

    @pytest.mark.asyncio
    async def test_no_github_token_fails_before_touching_anything(
        self, configured, github
    ):
        result = await driver.OpenCodeDriver().author(request(), {})

        assert result.opened is False
        assert "not connected" in result.error

    @pytest.mark.asyncio
    async def test_a_configuration_error_is_reported_as_one(
        self, configured, github, monkeypatch
    ):
        """
        Distinct from an authoring failure. "Your source path points at Locus"
        and "the agent could not write this ticket" want completely different
        responses.
        """
        result = await driver.OpenCodeDriver().author(
            request(settings={"source_path": "/definitely/not/here"}), CONFIGS
        )

        assert result.opened is False
        assert "does not exist" in result.error

    @pytest.mark.asyncio
    async def test_the_workspace_is_kept_on_failure(
        self, configured, github, monkeypatch, tmp_path
    ):
        """A failed run whose tree is gone is close to undebuggable."""
        monkeypatch.setattr(driver, "run_agent", fake_agent({
            "feature.py": "ok\n", ".github/workflows/ci.yml": "x\n",
        }))

        result = await driver.OpenCodeDriver().author(request(), CONFIGS)

        assert result.opened is False
        assert Path(result.workspace_path).exists()

    @pytest.mark.asyncio
    async def test_the_workspace_is_removed_on_success(
        self, configured, github, monkeypatch
    ):
        monkeypatch.setattr(driver, "run_agent", fake_agent({"feature.py": "ok\n"}))

        result = await driver.OpenCodeDriver().author(request(), CONFIGS)

        assert result.opened is True
        assert not Path(result.workspace_path).exists()

    @pytest.mark.asyncio
    async def test_the_prompt_file_reaches_the_agent_with_the_brief_in_it(
        self, configured, github, monkeypatch
    ):
        seen = {}

        async def capture(command, workspace, timeout=None):
            for arg in command:
                if str(arg).endswith(".locus-prompt.md"):
                    seen["prompt"] = Path(arg).read_text()
            (Path(workspace) / "feature.py").write_text("ok\n")
            return 0, ""

        monkeypatch.setenv(
            "LOCUS_OPENCODE_CMD", "agent --prompt-file {prompt} --cwd {workspace}"
        )
        monkeypatch.setattr(driver, "run_agent", capture)

        await driver.OpenCodeDriver().author(
            request(
                context="## Slack\nthe requirement",
                asks=["add the word orange too"],
                rejection="it did nothing",
            ),
            CONFIGS,
        )

        assert "the requirement" in seen["prompt"]
        assert "add the word orange too" in seen["prompt"]
        assert "it did nothing" in seen["prompt"]

    @pytest.mark.asyncio
    async def test_the_attempt_records_the_model_that_ran(
        self, configured, github, monkeypatch
    ):
        monkeypatch.setenv("LOCUS_OPENCODE_MODEL", "some-model-v2")
        monkeypatch.setattr(driver, "run_agent", fake_agent({"feature.py": "ok\n"}))

        result = await driver.OpenCodeDriver().author(request(), CONFIGS)

        assert result.model == "some-model-v2"
