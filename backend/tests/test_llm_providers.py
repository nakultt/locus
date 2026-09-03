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
