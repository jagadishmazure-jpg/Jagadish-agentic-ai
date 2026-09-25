import itertools

import pytest

from care_e2e.graph import build_graph
from care_e2e.systems import seed_systems

_ids = itertools.count(1)


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.delenv("CARE_MCP_URLS", raising=False)


@pytest.fixture
def systems():
    return seed_systems()


@pytest.fixture
def graph(systems):
    return build_graph(systems)


@pytest.fixture
def ask():
    def _ask(graph, message, customer="C100", email="ana@example.com", tenant="acme-retail"):
        n = next(_ids)
        req = {
            "request_id": f"req-{n}",
            "channel": "web",
            "tenant": tenant,
            "customer_id": customer,
            "email": email,
            "message": message,
        }
        cfg = {"configurable": {"thread_id": f"t-{n}"}}
        return graph.invoke({"request": req}, cfg), cfg

    return _ask
