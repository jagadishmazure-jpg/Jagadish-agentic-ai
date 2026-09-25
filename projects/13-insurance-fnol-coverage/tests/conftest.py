import itertools

import pytest
from langgraph.types import Command

from fnol.graph import build_graph
from fnol.systems import seed_systems

_ids = itertools.count(1)


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")


@pytest.fixture
def systems():
    return seed_systems()


@pytest.fixture
def run(systems):
    def _run(doc, review=None, llm=None):
        g = build_graph(systems, llm=llm)
        cfg = {"configurable": {"thread_id": f"t-{next(_ids)}"}}
        r = g.invoke({"request": {"document_id": doc}}, cfg)
        if review is not None and "__interrupt__" in r:
            r = g.invoke(Command(resume=review), cfg)
        return r

    return _run
