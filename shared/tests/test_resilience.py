import pytest

from shared import faults
from shared.llm import MockChatModel, get_resilient_llm
from shared.resilience import (
    Backoff,
    CircuitBreaker,
    CircuitOpenError,
    FiveExitPolicy,
    ModelUnavailableError,
    exit_table,
    retry_call,
    with_fallback,
)


def test_retry_with_backoff_recovers_then_exhausts():
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise ConnectionError("503")
        return "ok"

    assert retry_call(flaky, backoff=Backoff(attempts=3)) == "ok" and len(calls) == 3
    with pytest.raises(ConnectionError):
        retry_call(
            lambda: (_ for _ in ()).throw(ConnectionError("down")), backoff=Backoff(attempts=2)
        )


def test_circuit_breaker_opens_and_half_opens():
    now = [0.0]
    br = CircuitBreaker("x", failure_threshold=2, reset_after_s=10, clock=lambda: now[0])
    for _ in range(2):
        with pytest.raises(ValueError):
            br.call(lambda: (_ for _ in ()).throw(ValueError()))
    assert br.state == "open"
    with pytest.raises(CircuitOpenError):
        br.call(lambda: 1)
    now[0] = 11
    assert br.state == "half_open" and br.call(lambda: 1) == 1 and br.state == "closed"


def test_fallback_chain_primary_fallback_then_unavailable():
    llm = with_fallback(
        MockChatModel(responder=lambda m: "p"), MockChatModel(responder=lambda m: "f")
    )
    assert llm.invoke("hi").content == "p"
    with faults.fault("model:primary"):
        out = llm.invoke("hi")
        assert out.content == "f" and out.response_metadata["served_by"] == "fallback"
    with faults.fault("model"), pytest.raises(ModelUnavailableError):
        llm.invoke("hi")
    assert llm.usage == {"primary": 1, "fallback": 1}


def test_breaker_skips_dead_primary_and_bind_tools_keeps_chain():
    llm = get_resilient_llm(mock_responder=lambda m: "ok", provider="mock")
    faults.inject("model:primary")
    for _ in range(3):
        llm.invoke("x")
    faults.clear()
    assert llm.breaker("primary").state == "open"
    assert llm.invoke("x").response_metadata["served_by"] == "fallback"
    bound = llm.bind_tools([])
    assert bound.breaker("primary") is llm.breaker("primary")


def test_five_exit_policy_validation_and_table():
    row = {
        "node": "n",
        "success": "a",
        "retry": "b",
        "compensate": "c",
        "degrade": "d",
        "escalate": "e",
    }
    assert "| `n` | a | b | c | d | e |" in exit_table([FiveExitPolicy.from_dict(row)])
    with pytest.raises(ValueError, match="degrade"):
        FiveExitPolicy.from_dict({**row, "degrade": ""})
