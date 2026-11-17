"""IT desk playbook agent: project 01's corrective RAG graph over the IT playbooks.

The graph, prompts, sanitiser, grader and groundedness check are the Azure project's.
This module only swaps the corpus and the chat model (mock, or Bedrock when asked).
"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models import BaseChatModel

from it_desk.bedrock import get_model
from it_desk.playbook import load_chunks
from policy_qa.graph import build_graph
from policy_qa.retriever import BM25Retriever


def build_agent(llm: BaseChatModel | None = None):
    return build_graph(retriever=BM25Retriever(load_chunks()), llm=llm or get_model())


def ask(question: str, *, llm: BaseChatModel | None = None) -> dict[str, Any]:
    """Run one question. The returned state includes ``final`` (status, answer, citations)."""
    return build_agent(llm).invoke({"question": question})
