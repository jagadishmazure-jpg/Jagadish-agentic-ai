import pytest

from ticket_triage.graph import build_graph


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")


@pytest.fixture
def triage():
    graph = build_graph()

    def _triage(body, subject="Support", tid="T-X", g=None):
        return (g or graph).invoke({"ticket": {"id": tid, "subject": subject, "body": body}})

    return _triage
