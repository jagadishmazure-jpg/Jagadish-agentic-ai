import itertools

import pytest

from control_plane.agents import build_network
from control_plane.journey import build_graph

_ids = itertools.count(1)


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")


@pytest.fixture
def net():
    return build_network()


@pytest.fixture
def ask(net):
    g = build_graph(net)

    def _ask(text, tenant="northwind", thread=None):
        cfg = {"configurable": {"thread_id": thread or f"t-{next(_ids)}"}}
        return g.invoke({"request": {"tenant": tenant, "text": text}}, cfg)

    return _ask
