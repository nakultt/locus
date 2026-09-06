"""
The model backend is selectable, and the key is never exposed.

Locus defaults to the local MoE server. `LLM_PROVIDER` points it at OpenAI,
Anthropic or Gemini instead — a change in where your code goes, so the status
surface has to say which one is active and whether its key is set, without
ever returning the key itself.
"""

import pytest

from app.services.chat import llm


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in (
        "LLM_PROVIDER",
        "LLM_FAST_MODEL",
        "LLM_SMART_MODEL",
        "LLM_TIMEOUT_SECONDS",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "OPENCODE_API_KEY",
        "OPENCODE_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)


def test_defaults_to_local():
    assert llm._provider() == llm.LOCAL
    backend = llm.describe_backend()
    assert backend["provider"] == "moe-local"
    assert backend["is_local"] is True
    assert backend["base_url"] == llm.MOE_BASE_URL


def test_unknown_provider_falls_back_to_local(monkeypatch):
    """A typo must not silently send code to a third party."""
    monkeypatch.setenv("LLM_PROVIDER", "opnai")
    assert llm._provider() == llm.LOCAL


def test_aliases_resolve(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "Claude")
    assert llm._provider() == llm.ANTHROPIC
    monkeypatch.setenv("LLM_PROVIDER", "moe")
    assert llm._provider() == llm.LOCAL


def test_hosted_provider_without_key_names_the_variable(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    with pytest.raises(llm.LLMUnavailableError) as excinfo:
        llm.get_llm()
    assert "OPENAI_API_KEY" in str(excinfo.value)


def test_openai_binds_the_configured_model(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_SMART_MODEL", "gpt-4.1")

    model = llm.get_llm(smart_mode=True)
    assert model.model_name == "gpt-4.1"


def test_gemini_uses_the_openai_compatible_endpoint(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GOOGLE_API_KEY", "g-test")

    assert llm._api_key(llm.GEMINI) == "g-test"
    assert "generativelanguage.googleapis.com" in llm._base_url(llm.GEMINI)
    llm.get_llm()


def test_opencode_uses_responses_endpoint(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "opencode")
    monkeypatch.setenv("OPENCODE_API_KEY", "sk-zen-test")

    assert llm._provider() == llm.OPENCODE
    assert llm._api_key(llm.OPENCODE) == "sk-zen-test"
    assert llm._base_url(llm.OPENCODE) == "https://opencode.ai/zen/v1/responses"
    assert llm.default_base_url(llm.OPENCODE) == "https://opencode.ai/zen/v1/responses"

    fast, smart = llm._models(llm.OPENCODE)
    assert fast == "muse-spark-1.3-contributor-free"
    assert smart == "muse-spark-1.3-contributor-free"

    model = llm.get_llm()
    assert model.use_responses_api is True
    assert model.openai_api_base == "https://opencode.ai/zen/v1"


def test_opencode_aliases_resolve(monkeypatch):
    for alias in ("zen", "opencode-zen", "open-code", "OPENCODE"):
        monkeypatch.setenv("LLM_PROVIDER", alias)
        assert llm._provider() == llm.OPENCODE


def test_opencode_without_key_names_the_variable(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "opencode")
    with pytest.raises(llm.LLMUnavailableError) as excinfo:
        llm.get_llm()
    assert "OPENCODE_API_KEY" in str(excinfo.value)


def test_status_reports_key_presence_never_the_key(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret")

    backend = llm.describe_backend()
    assert backend["api_key_configured"] is True
    assert backend["api_key_env"] == "ANTHROPIC_API_KEY"
    assert "sk-ant-secret" not in repr(backend)

    listed = llm.available_providers()
    assert "sk-ant-secret" not in repr(listed)
    assert [p["id"] for p in listed if p["active"]] == ["anthropic"]
    assert all("api_key" not in k or k.endswith(("_env", "_configured")) for k in listed[0])


def test_local_check_is_unchanged_by_the_new_switch(monkeypatch):
    """The local path still asks MoE's /health, not a provider models list."""
    calls = []

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {"text_model": "ready"}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, **kwargs):
            calls.append(url)
            return Response()

    monkeypatch.setattr(llm.httpx, "AsyncClient", lambda **kw: Client())

    import asyncio

    available, message = asyncio.run(llm.check_llm_available())
    assert available is True
    assert calls == [llm._health_url()]
    assert "ready" in message


def test_hosted_check_reports_a_rejected_key_as_a_key_problem(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-wrong")

    class Response:
        status_code = 401

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, **kwargs):
            return Response()

    monkeypatch.setattr(llm.httpx, "AsyncClient", lambda **kw: Client())

    import asyncio

    available, message = asyncio.run(llm.check_llm_available())
    assert available is False
    assert "OPENAI_API_KEY" in message


def test_opencode_check_hits_models_endpoint(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "opencode")
    monkeypatch.setenv("OPENCODE_API_KEY", "sk-valid")

    calls = []

    class Response:
        status_code = 200

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, **kwargs):
            calls.append(url)
            return Response()

    monkeypatch.setattr(llm.httpx, "AsyncClient", lambda **kw: Client())

    import asyncio

    available, message = asyncio.run(llm.check_llm_available())
    assert available is True
    assert calls == ["https://opencode.ai/zen/v1/models"]
    assert "OpenCode Zen is reachable" in message



# ---------------------------------------------------------------- per-user

"""
The backend is a setting, not a deployment constant.

`llm_config` binds one user's provider, endpoint, models and key for the
current task; the environment stays as the deployment-wide default. These
pin the two things that make that safe: a bound config wins over the
environment, and a key only ever applies to the provider it was entered for.
"""


@pytest.fixture(autouse=True)
def unbound():
    """No config bound unless a test binds one."""
    from app.services.chat import llm_config

    llm_config.clear()
    yield
    llm_config.clear()


def _bind(**kwargs):
    from app.services.chat import llm_config

    llm_config.bind(llm_config.LLMConfig(**kwargs))


def test_user_settings_beat_the_environment(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "local")
    _bind(provider="openai", api_key="sk-user", smart_model="gpt-5-mine")

    assert llm._provider() == llm.OPENAI
    assert llm._models(llm.OPENAI)[1] == "gpt-5-mine"
    assert llm.describe_backend()["source"] == "settings"


def test_nothing_bound_still_reads_the_environment(monkeypatch):
    """A deployment that never opens the settings page is unaffected."""
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "g-env")

    assert llm._provider() == llm.GEMINI
    assert llm._api_key(llm.GEMINI) == "g-env"
    assert llm.describe_backend()["source"] == "environment"


def test_the_endpoint_is_configurable_for_every_provider():
    """vLLM, LiteLLM, OpenRouter and Azure are all 'OpenAI at another URL'."""
    _bind(provider="local", base_url="http://gpu-box:9000/v1")
    assert llm._base_url(llm.LOCAL) == "http://gpu-box:9000/v1"
    assert llm._health_url() == "http://gpu-box:9000/health"

    _bind(provider="openai", base_url="https://gateway.internal/v1", api_key="k")
    assert llm._base_url(llm.OPENAI) == "https://gateway.internal/v1"


def test_a_key_never_crosses_providers():
    """
    An OpenAI key handed to Anthropic produces a 401 that reads as an outage.

    The stored key belongs to the provider it was entered for, so switching
    the selector without clearing the field must not send it somewhere else.
    """
    _bind(provider="openai", api_key="sk-openai")

    assert llm._api_key(llm.OPENAI) == "sk-openai"
    assert llm._api_key(llm.ANTHROPIC) == ""
    assert llm._models(llm.ANTHROPIC) == llm._DEFAULT_MODELS[llm.ANTHROPIC]


def test_blank_fields_inherit_rather_than_override(monkeypatch):
    """Blank means 'use the default', not 'override with nothing'."""
    monkeypatch.setenv("MOE_FAST_MODEL", "deployment-fast")
    _bind(provider="local", fast_model=None, base_url=None)

    assert llm._models(llm.LOCAL)[0] == "deployment-fast"
    assert llm._base_url(llm.LOCAL) == llm.MOE_BASE_URL


def test_a_users_key_is_never_rendered():
    _bind(provider="anthropic", api_key="sk-ant-user-secret")

    assert "sk-ant-user-secret" not in repr(llm.describe_backend())
    assert "sk-ant-user-secret" not in repr(llm.available_providers())

    from app.services.chat import llm_config

    assert "sk-ant-user-secret" not in repr(llm_config.active())


def test_an_unknown_provider_from_a_user_falls_back_to_local():
    """The same rule the environment follows: fail towards the local backend."""
    _bind(provider="opnai", api_key="sk-typo")
    assert llm._provider() == llm.LOCAL


class TestTheBindingCannotBeMissed:
    """
    `get_integration_configs` binds the user's model backend, and is the only
    place that does. A path that builds the same credential dict by hand looks
    correct and runs on the deployment default instead -- which is
    indistinguishable from the setting never having saved.

    The QA classifier hit exactly this. The Slack events router had its own
    copy of the loop, so a tester's reply was classified against the local
    endpoint on an account that had configured a hosted provider, and the
    channel reported `Classifier unavailable: Connection error` for a backend
    the user had already moved off. `automerge`, the Gmail poller and the
    capabilities view carried the same copy.
    """

    def test_only_dependencies_builds_integration_configs(self):
        """
        A source check, for the same reason `test_project_board` pins a query
        as a string: nothing else can catch the next copy of this loop, and the
        symptom when one appears is a setting that appears not to save.
        """
        import pathlib

        app_root = pathlib.Path(__file__).resolve().parent.parent / "app"

        # The signal is the *pair*: walking the user's integrations while
        # decrypting each one's credentials is the config dict being built.
        # Listing integrations alone is not -- `auth.list_integrations` and the
        # chat router legitimately do that and never touch a credential.
        #
        # Either spelling of the decryption counts. `get_integration_configs`
        # decrypts straight from the rows it already loaded rather than calling
        # `crud.get_integration_credentials`, which re-queries them; matching
        # only the crud call would have left this guard matching nothing, which
        # passes and is indistinguishable from a guard that cannot fail.
        decrypts = ("get_integration_credentials(", "decrypt_credentials(")
        builders = set()
        for path in app_root.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            if "crud.get_user_integrations(" in source and any(
                d in source for d in decrypts
            ):
                builders.add(path.relative_to(app_root).as_posix())

        assert builders == {"core/dependencies.py"}, (
            "Build integration configs through get_integration_configs; a local "
            "copy of its loop silently skips the LLM/agent-runtime binding and "
            "the Google OAuth client credentials."
        )

    def test_get_integration_configs_binds_the_users_backend(self, monkeypatch):
        from app.core import dependencies
        from app.services.chat import llm, llm_config

        llm_config.clear()

        monkeypatch.setattr(
            dependencies.crud, "get_user_integrations", lambda _db, _uid: []
        )
        monkeypatch.setattr(
            llm_config, "for_user",
            lambda _db, _uid: llm_config.LLMConfig(
                provider="openai", api_key="sk-bound"
            ),
        )
        monkeypatch.setattr(dependencies.llm_config, "for_user", llm_config.for_user)

        dependencies.get_integration_configs(db=None, user_id=1)

        assert llm._provider() == llm.OPENAI
        llm_config.clear()


class TestMessageTextHandlesBlockContent:
    """
    A message's `.content` is a string only on the chat-completions wire
    format. The Responses API and Anthropic return a list of content blocks,
    and every analysis parser used to fall back to `str(content)` -- which
    stringifies the Python list, so a parser expecting JSON got
    `[{'id': 'rs_...', 'type': 'reasoning', ...}]`.

    It failed in the most misleading direction available at each site: the QA
    classifier called the tester's reply unclear, and the scanner and reviewer
    degraded to their error strings, while every surface rendered as though a
    model had read the code.
    """

    class _Response:
        def __init__(self, content):
            self.content = content

    def test_a_plain_string_is_returned_unchanged(self):
        assert llm.message_text(self._Response('{"verdict": "broken"}')) == (
            '{"verdict": "broken"}'
        )

    def test_a_responses_api_reasoning_block_is_skipped(self):
        """The shape that actually broke this, from OpenCode Zen."""
        response = self._Response([
            {"id": "rs_6a9d04", "type": "reasoning", "summary": [],
             "encrypted_content": "Q-PaDgHMfkLKSLbkRxBq"},
            {"type": "text", "text": '{"verdict": "broken", "reason": "no"}'},
        ])

        assert llm.message_text(response) == '{"verdict": "broken", "reason": "no"}'

    def test_an_anthropic_thinking_block_is_skipped(self):
        response = self._Response([
            {"type": "thinking", "thinking": "the tester said it did not work"},
            {"type": "text", "text": '{"verdict": "broken"}'},
        ])

        assert llm.message_text(response) == '{"verdict": "broken"}'

    def test_several_text_blocks_are_joined(self):
        response = self._Response([
            {"type": "text", "text": '{"verdict":'},
            {"type": "text", "text": ' "works"}'},
        ])

        assert llm.message_text(response) == '{"verdict": "works"}'

    def test_a_block_list_never_stringifies_the_python_object(self):
        """The regression itself: no `str(list)` may reach a parser."""
        text = llm.message_text(self._Response([
            {"id": "rs_1", "type": "reasoning", "encrypted_content": "x"},
        ]))

        assert "'type':" not in text
        assert text == ""

    def test_a_bare_message_works_as_well_as_a_response(self):
        """Callers pass an AIMessage in one place and a response in seven."""
        assert llm.message_text("already text") == "already text"

    def test_no_parser_reimplements_the_extraction(self):
        """
        A source check, like the binding one above. The seven copies of
        `content if isinstance(content, str) else str(content)` are exactly
        what this helper replaced, and a new one would fail the same way.
        """
        import pathlib

        app_root = pathlib.Path(__file__).resolve().parent.parent / "app"

        offenders = [
            path.relative_to(app_root).as_posix()
            for path in app_root.rglob("*.py")
            if "isinstance(response.content, str)" in path.read_text(encoding="utf-8")
            or "isinstance(content, str) else str(content)" in path.read_text(
                encoding="utf-8"
            )
        ]

        assert offenders == [], (
            "Read model output through llm.message_text; str() on a list of "
            "content blocks yields a repr, not the model's answer."
        )
