"""HTTP contract shared by AgentCore Runtime (/ping, /invocations) and ECS (/ask)."""

from fastapi.testclient import TestClient

from it_desk.logging import CloudWatchSink, MemorySink, event
from it_desk.service import create_app


def test_ping_and_ask_round_trip():
    client = TestClient(create_app())
    ping = client.get("/ping")
    assert ping.status_code == 200
    assert ping.json()["status"] == "Healthy"
    assert ping.json()["provider"] == "mock"
    assert client.get("/healthz").json()["status"] == "Healthy"
    response = client.post("/ask", json={"question": "How do I reset a forgotten password?"})
    assert response.status_code == 200
    body = response.json()
    assert body["output"]["status"] == "answered"
    assert body["output"]["citations"][0]["id"] == "IT-ACCESS-1"
    assert "question" not in body["log"]
    assert len(body["log"]["question_sha256"]) == 16


def test_invocations_accepts_agentcore_envelopes():
    client = TestClient(create_app())
    prompt = client.post("/invocations", json={"prompt": "How do I report a phishing email?"})
    wrapped = client.post(
        "/invocations",
        json={"input": {"question": "How do I report a phishing email?"}},
    )
    assert prompt.status_code == 200 and wrapped.status_code == 200
    assert prompt.json()["output"]["citations"][0]["id"] == "IT-SEC-1"
    assert wrapped.json()["output"]["citations"][0]["id"] == "IT-SEC-1"
    assert client.post("/ask", json={}).status_code == 400


def test_log_record_omits_the_question_text():
    record = event(
        provider="mock",
        model="mock-chat-model",
        status="answered",
        latency_ms=3,
        citations=["IT-ACCESS-1"],
        question="my passphrase is swordfish-demo",
    )
    assert "swordfish-demo" not in str(record)
    assert record["question_sha256"]


class FakeLogs:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def create_log_stream(self, **kwargs):
        self.calls.append(("create", kwargs))

    def put_log_events(self, **kwargs):
        self.calls.append(("put", kwargs))
        return {"nextSequenceToken": "2"}


def test_cloudwatch_sink_puts_one_json_event():
    client = FakeLogs()
    sink = CloudWatchSink(client, "/it-desk/playbook", "local")
    line = sink.emit({"service": "it-desk-playbook", "status": "answered"})
    assert client.calls[0][0] == "create"
    assert client.calls[0][1]["logGroupName"] == "/it-desk/playbook"
    message = client.calls[1][1]["logEvents"][0]["message"]
    assert message == line
    assert "answered" in message
    sink.emit({"service": "it-desk-playbook", "status": "answered"})
    assert [name for name, _ in client.calls].count("create") == 1


def test_memory_sink_is_the_default():
    from it_desk.logging import build_sink

    assert isinstance(build_sink({}), MemorySink)
    sink = build_sink(
        {"IT_DESK_LOG_MODE": "cloudwatch", "IT_DESK_LOG_GROUP": "/it-desk/playbook"},
        client=FakeLogs(),
    )
    assert isinstance(sink, CloudWatchSink)
