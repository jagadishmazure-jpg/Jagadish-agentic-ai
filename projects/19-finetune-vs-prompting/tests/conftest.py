import pytest

from finetune_lab.compare import DATA
from finetune_lab.dataset import load_split


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")


@pytest.fixture(scope="session")
def splits():
    return {s: load_split(DATA / f"{s}.jsonl") for s in ("train", "val", "test")}
