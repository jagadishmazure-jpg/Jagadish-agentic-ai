"""Amazon Bedrock chat model for Claude and Llama, with an offline mock by default.

Live calls happen only when ``IT_DESK_PROVIDER=bedrock``. The invoker is injectable so
tests can assert the request body without AWS credentials or the network.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from policy_qa.llm import mock_responder
from shared.llm import MockChatModel

Invoker = Callable[[str, dict[str, Any]], dict[str, Any]]

CLAUDE_MODEL_ID = "anthropic.claude-3-5-haiku-20241022-v1:0"
LLAMA_MODEL_ID = "meta.llama3-1-8b-instruct-v1:0"
ANTHROPIC_VERSION = "bedrock-2023-05-31"


def resolve_provider(env: dict[str, str] | None = None) -> str:
    """``mock`` unless ``IT_DESK_PROVIDER`` is ``bedrock``."""
    env = dict(os.environ) if env is None else env
    forced = env.get("IT_DESK_PROVIDER", "").strip().lower()
    if forced in ("mock", "bedrock"):
        return forced
    return "mock"


def family_for(model_id: str) -> str:
    mid = model_id.lower()
    if "claude" in mid or mid.startswith("anthropic."):
        return "claude"
    if "llama" in mid or mid.startswith("meta."):
        return "llama"
    raise ValueError(f"unsupported Bedrock model id {model_id!r}; use a Claude or Llama model id")


def _role(message: BaseMessage) -> str:
    if isinstance(message, SystemMessage):
        return "system"
    if isinstance(message, AIMessage):
        return "assistant"
    return "user"


def claude_body(messages: list[BaseMessage], *, temperature: float, max_tokens: int) -> dict:
    system = "\n".join(str(m.content) for m in messages if _role(m) == "system")
    turns = [
        {"role": _role(m), "content": str(m.content)} for m in messages if _role(m) != "system"
    ]
    body: dict[str, Any] = {
        "anthropic_version": ANTHROPIC_VERSION,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": turns,
    }
    if system:
        body["system"] = system
    return body


def llama_body(messages: list[BaseMessage], *, temperature: float, max_tokens: int) -> dict:
    parts = ["<|begin_of_text|>"]
    for message in messages:
        parts.append(
            f"<|start_header_id|>{_role(message)}<|end_header_id|>\n\n{message.content}<|eot_id|>"
        )
    parts.append("<|start_header_id|>assistant<|end_header_id|>\n\n")
    return {"prompt": "".join(parts), "max_gen_len": max_tokens, "temperature": temperature}


def text_from_response(family: str, payload: dict[str, Any]) -> str:
    if family == "claude":
        blocks = payload.get("content") or []
        if not blocks or "text" not in blocks[0]:
            raise ValueError("Bedrock Claude response has no text block")
        return str(blocks[0]["text"])
    generation = payload.get("generation")
    if not isinstance(generation, str):
        raise ValueError("Bedrock Llama response has no generation")
    return generation


class BotoInvoker:
    """``bedrock-runtime`` InvokeModel. Imported lazily so offline tests need no boto3."""

    def __init__(self, region: str, client: Any = None):
        self.region = region
        self._client = client

    def __call__(self, model_id: str, body: dict[str, Any]) -> dict[str, Any]:
        client = self._client or self._build()
        response = client.invoke_model(
            modelId=model_id,
            body=json.dumps(body),
            contentType="application/json",
            accept="application/json",
        )
        raw = response["body"].read()
        return json.loads(raw)

    def _build(self) -> Any:
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover - depends on the aws extra
            raise RuntimeError(
                "boto3 is not installed. Run: uv sync --extra aws (or set IT_DESK_PROVIDER=mock)"
            ) from exc
        self._client = boto3.client("bedrock-runtime", region_name=self.region)
        return self._client


class BedrockChatModel(BaseChatModel):
    """LangChain chat model that calls Bedrock InvokeModel for Claude or Llama."""

    model_id: str = CLAUDE_MODEL_ID
    region: str = "us-east-1"
    temperature: float = 0.0
    max_tokens: int = 512
    invoker: Any = Field(default=None)

    @property
    def _llm_type(self) -> str:
        return "bedrock-chat"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        family = family_for(self.model_id)
        if family == "claude":
            body = claude_body(messages, temperature=self.temperature, max_tokens=self.max_tokens)
        else:
            body = llama_body(messages, temperature=self.temperature, max_tokens=self.max_tokens)
        invoker = self.invoker or BotoInvoker(self.region)
        payload = invoker(self.model_id, body)
        text = text_from_response(family, payload).strip()
        message = AIMessage(content=text, response_metadata={"model_id": self.model_id})
        return ChatResult(generations=[ChatGeneration(message=message)])


def get_model(
    env: dict[str, str] | None = None, *, invoker: Invoker | None = None
) -> BaseChatModel:
    """Mock chat model, or Bedrock when ``IT_DESK_PROVIDER=bedrock``."""
    env = dict(os.environ) if env is None else env
    if resolve_provider(env) == "mock":
        return MockChatModel(responder=mock_responder)
    model_id = env.get("BEDROCK_MODEL_ID", "").strip() or CLAUDE_MODEL_ID
    region = env.get("AWS_REGION", "").strip() or env.get("AWS_DEFAULT_REGION", "").strip()
    region = region or "us-east-1"
    return BedrockChatModel(model_id=model_id, region=region, invoker=invoker)
