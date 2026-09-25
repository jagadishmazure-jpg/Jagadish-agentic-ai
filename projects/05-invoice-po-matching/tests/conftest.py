import pytest

from invoice_match.erp import seed_erp
from invoice_match.graph import build_graph


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")


@pytest.fixture
def erp():
    return seed_erp()


@pytest.fixture
def graph(erp):
    return build_graph(erp)
