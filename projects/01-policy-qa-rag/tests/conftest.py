import pytest

from policy_qa.graph import build_graph


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")


@pytest.fixture
def graph():
    return build_graph()


@pytest.fixture
def ask(graph):
    def _ask(question):
        return graph.invoke({"question": question})

    return _ask
