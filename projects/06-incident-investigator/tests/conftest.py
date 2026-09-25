import itertools

import pytest

from incident_agent.graph import build_graph
from incident_agent.systems import seed_systems

_ids = itertools.count(1)


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")


@pytest.fixture
def systems():
    return seed_systems()


@pytest.fixture
def start():
    def _start(graph, alert):
        cfg = {"configurable": {"thread_id": f"t{next(_ids)}"}}
        return graph.invoke({"alert": alert}, cfg), cfg

    return _start


@pytest.fixture
def graph(systems):
    return build_graph(systems)
