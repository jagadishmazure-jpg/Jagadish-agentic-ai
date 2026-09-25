import itertools

import pytest

from supply_chain.graph import build_graph
from supply_chain.services import seed_services

_ids = itertools.count(1)


@pytest.fixture
def services():
    return seed_services()


@pytest.fixture
def graph(services):
    # default_llms() -> deterministic mocks (tests force LLM_PROVIDER=mock below)
    return build_graph(services)


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")


@pytest.fixture
def start():
    """Start a run for `sku` on a fresh thread; returns (result, config)."""

    def _start(graph, sku):
        cfg = {"configurable": {"thread_id": f"t-{next(_ids)}"}}
        return graph.invoke({"sku": sku, "horizon_weeks": 4}, cfg), cfg

    return _start
