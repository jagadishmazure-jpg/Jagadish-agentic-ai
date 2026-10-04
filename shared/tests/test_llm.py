from langchain_core.messages import HumanMessage

from shared.llm import MockChatModel, get_llm, resolve_provider


def test_resolve_provider_defaults_to_mock():
    assert resolve_provider({}) == "mock"


def test_resolve_provider_prefers_azure_when_complete():
    env = {
        "AZURE_OPENAI_ENDPOINT": "https://x",
        "AZURE_OPENAI_API_KEY": "k",
        "AZURE_OPENAI_DEPLOYMENT": "d",
        "OPENAI_API_KEY": "k2",
    }
    assert resolve_provider(env) == "azure"


def test_resolve_provider_partial_azure_falls_back_to_openai():
    env = {"AZURE_OPENAI_ENDPOINT": "https://x", "OPENAI_API_KEY": "k"}
    assert resolve_provider(env) == "openai"


def test_forced_provider_wins():
    assert resolve_provider({"LLM_PROVIDER": "mock", "OPENAI_API_KEY": "k"}) == "mock"


def test_mock_is_deterministic_and_uses_responder():
    llm = get_llm(provider="mock", mock_responder=lambda msgs: "ok:" + msgs[-1].content)
    assert isinstance(llm, MockChatModel)
    out1 = llm.invoke([HumanMessage(content="hi")]).content
    out2 = llm.invoke([HumanMessage(content="hi")]).content
    assert out1 == out2 == "ok:hi"


def test_mock_supports_tool_calling_agents():
    from langchain.agents import create_agent
    from langchain_core.messages import AIMessage, ToolMessage
    from langchain_core.tools import tool

    @tool
    def add(a: int, b: int) -> int:
        """Add two ints."""
        return a + b

    def responder(msgs):
        if not any(isinstance(m, ToolMessage) for m in msgs):
            return AIMessage("", tool_calls=[{"name": "add", "args": {"a": 2, "b": 3}, "id": "1"}])
        return AIMessage(f"sum={msgs[-1].content}")

    llm = MockChatModel(responder=responder)
    assert llm.bind_tools([add]).bound_tools == ["add"]
    agent = create_agent(llm, [add])
    out = agent.invoke({"messages": [HumanMessage("2+3?")]})
    assert out["messages"][-1].content == "sum=5"


def test_resolve_provider_azure_needs_no_key():
    env = {"AZURE_OPENAI_ENDPOINT": "https://x", "AZURE_OPENAI_DEPLOYMENT": "d"}
    assert resolve_provider(env) == "azure"


def test_azure_auth_uses_key_only_when_set():
    from shared.llm import azure_auth_kwargs

    assert azure_auth_kwargs({"AZURE_OPENAI_API_KEY": "k"}) == {"api_key": "k"}


def _fake_identity(monkeypatch):
    import sys
    import types

    calls = {}
    mod = types.ModuleType("azure.identity")

    class FakeCredential:
        pass

    def get_bearer_token_provider(cred, scope):
        calls["cred"], calls["scope"] = cred, scope
        return lambda: "token"

    mod.DefaultAzureCredential = FakeCredential
    mod.get_bearer_token_provider = get_bearer_token_provider
    monkeypatch.setitem(sys.modules, "azure.identity", mod)
    return calls, FakeCredential


def test_azure_auth_is_keyless_by_default(monkeypatch):
    from shared.llm import AZURE_SCOPE, azure_auth_kwargs

    calls, cred = _fake_identity(monkeypatch)
    kw = azure_auth_kwargs({})
    assert set(kw) == {"azure_ad_token_provider"} and kw["azure_ad_token_provider"]() == "token"
    assert isinstance(calls["cred"], cred) and calls["scope"] == AZURE_SCOPE


def test_get_llm_azure_keyless_passes_token_provider(monkeypatch):
    import langchain_openai

    _fake_identity(monkeypatch)
    seen = {}

    class FakeAzure:
        def __init__(self, **kw):
            seen.update(kw)

    monkeypatch.setattr(langchain_openai, "AzureChatOpenAI", FakeAzure)
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://x")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "d")
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    get_llm(provider="azure")
    assert "api_key" not in seen and callable(seen["azure_ad_token_provider"])
    assert seen["azure_deployment"] == "d"


def test_get_llm_azure_with_key_does_not_touch_identity(monkeypatch):
    import sys

    import langchain_openai

    seen = {}

    class FakeAzure:
        def __init__(self, **kw):
            seen.update(kw)

    monkeypatch.setattr(langchain_openai, "AzureChatOpenAI", FakeAzure)
    monkeypatch.setitem(sys.modules, "azure.identity", None)  # import would fail if attempted
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://x")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "d")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "k")
    get_llm(provider="azure")
    assert seen["api_key"] == "k" and "azure_ad_token_provider" not in seen


def test_mock_stays_default_without_env(monkeypatch):
    for v in ("LLM_PROVIDER", "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_DEPLOYMENT", "OPENAI_API_KEY"):
        monkeypatch.delenv(v, raising=False)
    assert isinstance(get_llm(), MockChatModel)
