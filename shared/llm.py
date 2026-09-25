"""LLM factory: offline-first.

``get_llm()`` returns, in order of precedence:

1. ``LLM_PROVIDER`` env var if set (``mock`` | ``azure`` | ``openai``).
2. ``AzureChatOpenAI`` when AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY and
   AZURE_OPENAI_DEPLOYMENT are all set.
3. ``ChatOpenAI`` when OPENAI_API_KEY is set.
4. A deterministic :class:`MockChatModel` otherwise (tests, CI, laptops on a plane).

``langchain-openai`` is an optional extra and is imported lazily.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from typing import Any, Literal

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

Provider = Literal["mock", "azure", "openai"]
Responder = Callable[[Sequence[BaseMessage]], "str | AIMessage"]

AZURE_VARS = ("AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_DEPLOYMENT")


def _default_responder(messages: Sequence[BaseMessage]) -> str:
    last = messages[-1].content if messages else ""
    text = last if isinstance(last, str) else str(last)
    return f"[mock] {text[:200]}"


class MockChatModel(BaseChatModel):
    """Deterministic chat model. Behaviour is supplied by a ``responder`` callable.

    Each project passes its own rule-based responder so demos and tests are
    reproducible without network access, while the calling code is identical to
    what runs against a real model. A responder returns either text or a full
    ``AIMessage`` (e.g. one carrying ``tool_calls`` for agent loops).
    """

    responder: Responder = _default_responder
    bound_tools: list[str] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "mock-chat-model"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        out = self.responder(messages)
        message = out if isinstance(out, AIMessage) else AIMessage(content=out)
        return ChatResult(generations=[ChatGeneration(message=message)])

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> MockChatModel:
        """Support tool-calling agents (e.g. ``create_react_agent``).

        The responder decides which tool calls to emit by returning an ``AIMessage``
        with ``tool_calls``; bound tool names are recorded for introspection.
        """
        names = [getattr(t, "name", None) or getattr(t, "__name__", str(t)) for t in tools]
        return self.model_copy(update={"bound_tools": names})


def resolve_provider(env: dict[str, str] | None = None) -> Provider:
    env = dict(os.environ) if env is None else env
    forced = env.get("LLM_PROVIDER", "").strip().lower()
    if forced in ("mock", "azure", "openai"):
        return forced  # type: ignore[return-value]
    if all(env.get(v) for v in AZURE_VARS):
        return "azure"
    if env.get("OPENAI_API_KEY"):
        return "openai"
    return "mock"


def get_llm(
    *,
    temperature: float = 0.0,
    mock_responder: Responder | None = None,
    provider: Provider | None = None,
) -> BaseChatModel:
    """Return a chat model for the current environment (see module docstring)."""
    provider = provider or resolve_provider()
    if provider == "mock":
        return MockChatModel(responder=mock_responder or _default_responder)

    try:
        from langchain_openai import AzureChatOpenAI, ChatOpenAI
    except ImportError as exc:  # pragma: no cover - depends on installed extras
        raise RuntimeError(
            "langchain-openai is not installed. Run: uv sync --extra openai"
        ) from exc

    if provider == "azure":
        return AzureChatOpenAI(
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            api_key=os.environ["AZURE_OPENAI_API_KEY"],
            azure_deployment=os.environ["AZURE_OPENAI_DEPLOYMENT"],
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21"),
            temperature=temperature,
        )
    return ChatOpenAI(model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"), temperature=temperature)
