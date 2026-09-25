"""Repo-wide pytest fixtures: fault isolation + chaos fixtures (kill model / retrieval /
system of record, inject a jailbreak). Project conftests add their own offline guards."""

from __future__ import annotations

import pytest

from shared import faults, resilience
from shared.chaos import JAILBREAK


@pytest.fixture(autouse=True)
def _isolate_faults():
    resilience.SLEEP_SCALE = 0.0  # no real backoff sleeps in tests
    faults.clear()
    yield
    faults.clear()


@pytest.fixture
def kill_model():
    """Every model deployment (primary + fallback) is down."""
    faults.inject("model")
    yield
    faults.clear("model")


@pytest.fixture
def kill_primary_model():
    faults.inject("model:primary")
    yield
    faults.clear("model:primary")


@pytest.fixture
def kill_retrieval():
    faults.inject("retrieval")
    yield
    faults.clear("retrieval")


@pytest.fixture
def kill_sor():
    """Call with a server name (or none for all systems of record): kill_sor('erp')."""
    injected: list[str] = []

    def _kill(server: str | None = None, times: int | None = None) -> None:
        name = f"sor:{server}" if server else "sor"
        faults.inject(name, times)
        injected.append(name)

    yield _kill
    for n in injected:
        faults.clear(n)


@pytest.fixture
def jailbreak() -> str:
    return JAILBREAK
