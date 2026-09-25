from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from shared.llm import MockChatModel
from shared.observability import install, run_config
from shared.resilience import with_fallback


class S(TypedDict):
    x: str


def test_graph_node_llm_spans_carry_thread_identity_tokens_cost():
    t = install()
    llm = with_fallback(MockChatModel(responder=lambda m: "answer " * 10))

    def node(s):
        return {"x": llm.invoke("question " * 40).content}

    g = StateGraph(S)
    g.add_node("answer", node)
    g.add_edge(START, "answer")
    g.add_edge("answer", END)
    graph = g.compile(name="otel-test-agent")
    before = t.cost.usd
    graph.invoke({"x": ""}, run_config("thread-otel-1", identity="svc-otel"))
    spans = [
        s
        for s in t.exporter.spans
        if s.attributes.get("thread.id") == "thread-otel-1" or s.name in ("node answer",)
    ]
    root = next(s for s in spans if s.name == "agent.run otel-test-agent")
    assert root.attributes["enduser.id"] == "svc-otel"
    node_span = next(
        s
        for s in t.exporter.spans
        if s.name == "node answer" and s.parent.span_id == root.context.span_id
    )
    llm_span = next(
        s
        for s in t.exporter.spans
        if s.name.startswith("llm ") and s.parent and s.parent.span_id == node_span.context.span_id
    )
    assert llm_span.attributes["gen_ai.usage.input_tokens"] > 50
    assert llm_span.attributes["gen_ai.served_by"] == "primary"
    assert t.cost.usd > before and t.cost.by_thread["thread-otel-1"] > 0
