import pytest

from meeting_prep.graph import build_graph
from meeting_prep.sources import seed_sources


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")


@pytest.fixture
def prep():
    def _prep(sources=None, llm=None, **extra):
        sources = sources or seed_sources()
        graph = build_graph(sources, llm=llm)
        return graph.invoke(
            {
                "account_id": "ACME",
                "account_name": "Acme Corp",
                "meeting": {"goal": "renewal"},
                **extra,
            }
        )

    return _prep
