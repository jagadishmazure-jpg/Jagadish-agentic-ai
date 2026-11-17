"""Bedrock request bodies for Claude and Llama, and the mock-by-default switch."""

import json

import pytest

from it_desk.agent import ask
from it_desk.bedrock import (
    CLAUDE_MODEL_ID,
    LLAMA_MODEL_ID,
    BedrockChatModel,
    family_for,
    get_model,
    resolve_provider,
)
from shared.llm import MockChatModel


class Recorder:
    def __init__(self, payload: dict):
        self.payload = payload
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, model_id: str, body: dict) -> dict:
        self.calls.append((model_id, body))
        return self.payload


def test_provider_defaults_to_mock(monkeypatch):
    monkeypatch.delenv("IT_DESK_PROVIDER", raising=False)
    monkeypatch.setenv("BEDROCK_MODEL_ID", CLAUDE_MODEL_ID)
    assert resolve_provider() == "mock"
    assert isinstance(get_model(), MockChatModel)


def test_bedrock_provider_is_explicit(monkeypatch):
    monkeypatch.setenv("IT_DESK_PROVIDER", "bedrock")
    monkeypatch.delenv("BEDROCK_MODEL_ID", raising=False)
    model = get_model(invoker=Recorder({"content": [{"text": "ok"}]}))
    assert isinstance(model, BedrockChatModel)
    assert model.model_id == CLAUDE_MODEL_ID


def test_claude_body_uses_the_messages_api():
    seen = Recorder({"content": [{"text": "Use the Authenticator app."}]})
    model = BedrockChatModel(model_id=CLAUDE_MODEL_ID, invoker=seen)
    from langchain_core.messages import HumanMessage, SystemMessage

    text = model.invoke([SystemMessage("TASK: ANSWER"), HumanMessage("Is SMS allowed?")]).content
    assert text == "Use the Authenticator app."
    model_id, body = seen.calls[0]
    assert model_id == CLAUDE_MODEL_ID
    assert body["anthropic_version"] == "bedrock-2023-05-31"
    assert body["system"] == "TASK: ANSWER"
    assert body["messages"] == [{"role": "user", "content": "Is SMS allowed?"}]
    assert "prompt" not in body


def test_llama_body_uses_the_prompt_format():
    seen = Recorder({"generation": "Reset it in the portal."})
    model = BedrockChatModel(model_id=LLAMA_MODEL_ID, invoker=seen)
    from langchain_core.messages import HumanMessage, SystemMessage

    text = model.invoke([SystemMessage("be brief"), HumanMessage("password")]).content
    assert text == "Reset it in the portal."
    model_id, body = seen.calls[0]
    assert family_for(model_id) == "llama"
    assert body["prompt"].startswith("<|begin_of_text|>")
    assert "<|start_header_id|>system<|end_header_id|>" in body["prompt"]
    assert body["prompt"].rstrip().endswith("<|start_header_id|>assistant<|end_header_id|>")
    assert "messages" not in body


def test_unknown_model_is_rejected():
    with pytest.raises(ValueError):
        family_for("amazon.titan-text-express-v1")


def test_bedrock_failure_degrades_instead_of_inventing(monkeypatch):
    def boom(model_id: str, body: dict) -> dict:
        raise TimeoutError("bedrock timed out")

    monkeypatch.setenv("IT_DESK_PROVIDER", "bedrock")
    model = get_model(invoker=boom)
    final = ask("How do I reset a forgotten password?", llm=model)["final"]
    assert final["status"] == "answered"
    assert final["citations"][0]["id"] == "IT-ACCESS-1"
    assert "24 hours" in final["answer"]


def test_boto_invoker_serialises_json(monkeypatch):
    from it_desk.bedrock import BotoInvoker

    class FakeBody:
        def read(self):
            return json.dumps({"content": [{"text": "hi"}]}).encode()

    class FakeClient:
        def __init__(self):
            self.kwargs = None

        def invoke_model(self, **kwargs):
            self.kwargs = kwargs
            return {"body": FakeBody()}

    client = FakeClient()
    payload = BotoInvoker("us-east-1", client=client)(CLAUDE_MODEL_ID, {"messages": []})
    assert payload["content"][0]["text"] == "hi"
    assert client.kwargs["modelId"] == CLAUDE_MODEL_ID
    assert json.loads(client.kwargs["body"]) == {"messages": []}
    assert client.kwargs["contentType"] == "application/json"
