import pytest

from memory_agent.eval_suite import FakeClock
from memory_agent.graph import MemoryAgent


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def agent(clock):
    return MemoryAgent(clock=clock)
