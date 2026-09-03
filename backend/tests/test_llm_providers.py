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
