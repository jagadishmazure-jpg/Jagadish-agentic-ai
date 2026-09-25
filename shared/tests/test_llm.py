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
