import itertools

import pytest

from orchestration_lab.graph import build_graph, run_pattern
from orchestration_lab.sor import LoanSystems

_ids = itertools.count(1)


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")


@pytest.fixture
def run():
    """run(pattern, loan_id, **harness kwargs) -> the pattern graph's final state."""
    return run_pattern


@pytest.fixture
def arena():
    """arena(**build_graph kwargs) -> (graph, systems, config) on a fresh thread."""

    def _make(**kw):
        systems = kw.pop("systems", None) or LoanSystems()
        g = build_graph(systems=systems, **kw)
        return g, systems, {"configurable": {"thread_id": f"t-{next(_ids)}"}}

    return _make


def agents(out) -> list[str]:
    return [t["agent"] for t in out["turns"]]
