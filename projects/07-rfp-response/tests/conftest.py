import pytest

from rfp_agent.graph import build_graph
from rfp_agent.knowledge import RFP
from rfp_agent.llm import mock_responder
from shared.llm import MockChatModel


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")


@pytest.fixture(scope="module")
def result():
    # explicit mock: module-scoped fixtures run before the autouse env fixture
    return build_graph(llm=MockChatModel(responder=mock_responder)).invoke({"rfp_text": RFP})
