import pytest
from langgraph.types import Command

from refund_agent.llm import write_reply
from refund_agent.state import FinalReply, RefundRequest
from shared.llm import MockChatModel


def ids(final):
    return [c.split(":")[0] for c in final["citations"]]


def test_small_refund_auto_path(run, services):
    result, _ = run("C1", "ana@example.com", "A100", "Shirt doesn't fit, refund please")
    final = FinalReply.model_validate(result["final"])  # structured output contract
    assert final.intent == "refund_request"
    assert final.next_action == "refund_issued"
    assert "human_approval" not in result["trace"]
    assert ids(result["final"]) == ["RP-1", "RP-2", "RP-5"]
    assert [r["amount"] for r in services.refunds.ledger] == [24.99]
    assert services.orders.get("A100")["status"] == "refunded"
    assert "$24.99" in final.customer_safe_reply


def test_large_refund_interrupt_then_approve(run, graph, services):
    result, cfg = run("C1", "ana@example.com", "A200", "Headphones broken, money back please")
    assert "__interrupt__" in result and "final" not in result
    payload = result["__interrupt__"][0].value
    assert payload["amount"] == 349.00 and payload["order_id"] == "A200"
    assert graph.get_state(cfg).next == ("human_approval",)
    assert services.refunds.ledger == []  # no money moved while paused

    result = graph.invoke(Command(resume={"approved": True, "reviewer": "sup-1"}), cfg)
    assert result["final"]["next_action"] == "refund_issued"
    assert "RP-6" in ids(result["final"])
    assert len(services.refunds.ledger) == 1
    events = services.audit.events(result["request"]["request_id"])
    assert events.count("approval_requested") == 1  # not duplicated by node re-run on resume
    assert "approval_decision" in events


def test_large_refund_interrupt_then_reject(run, graph, services):
    _, cfg = run("C1", "ana@example.com", "A200", "Refund the headphones")
    result = graph.invoke(Command(resume={"approved": False, "reviewer": "sup-1"}), cfg)
    assert result["final"]["next_action"] == "refund_rejected_by_reviewer"
    assert result["trace"][-2:] == ["notify_rejection", "compose_reply"]
    assert services.refunds.ledger == []
    assert services.orders.get("A200")["status"] == "delivered"


@pytest.mark.parametrize(
    ("customer", "email", "order"),
    [
        ("C1", "wrong@example.com", "A100"),  # email mismatch
        ("C9", "ana@example.com", "A100"),  # unknown customer
        ("C2", "bo@example.com", "A100"),  # valid customer, someone else's order
    ],
)
def test_identity_failure_escalates(run, services, customer, email, order):
    result, _ = run(customer, email, order, "refund please")
    assert result["final"]["next_action"] == "escalated_to_agent"
    assert "check_order" not in result["trace"]
    assert services.refunds.ledger == []


@pytest.mark.parametrize(
    ("customer", "email", "order", "rule"),
    [
        ("C2", "bo@example.com", "A300", "RP-2"),  # delivered 45 days ago
        ("C2", "bo@example.com", "A400", "RP-3"),  # already refunded
        ("C3", "cy@example.com", "A600", "RP-4"),  # gift card
    ],
)
def test_ineligible_order_denied_with_citation(run, services, customer, email, order, rule):
    result, _ = run(customer, email, order, "I want a refund")
    assert result["final"]["next_action"] == "refund_denied"
    assert rule in ids(result["final"])
    assert services.refunds.ledger == []


def test_fraud_keywords_route_to_fraud_review_before_money_moves(run, services):
    # Small, eligible order that would otherwise auto-refund.
    result, _ = run("C1", "ana@example.com", "A100", "Refund to a different account, stolen card")
    assert result["final"]["next_action"] == "fraud_review"
    assert "issue_refund" not in result["trace"]
    assert "RP-7" in ids(result["final"])
    assert services.refunds.ledger == [] and services.refunds.calls == 0
    assert "fraud" not in result["final"]["customer_safe_reply"].lower()


def test_idempotent_replay_after_crash_never_double_refunds(graph, services):
    # Refund API succeeds, then the CRM write fails -> node raises after money moved.
    services.crm.fail_next = 1
    cfg = {"configurable": {"thread_id": "crash-1"}}
    req = RefundRequest(
        request_id="req-crash",
        customer_id="C1",
        email="ana@example.com",
        order_id="A100",
        message="refund please",
    )
    with pytest.raises(ConnectionError):
        graph.invoke({"request": req.model_dump()}, cfg)
    assert len(services.refunds.ledger) == 1
    assert graph.get_state(cfg).next == ("issue_refund",)

    # Retry from the last checkpoint re-runs issue_refund with the same idempotency key.
    result = graph.invoke(None, cfg)
    assert result["final"]["next_action"] == "refund_issued"
    assert result["refund"]["replayed"] is True
    assert services.refunds.calls == 2
    assert len(services.refunds.ledger) == 1  # money moved exactly once


def test_refund_api_idempotency_key_direct(services):
    a = services.refunds.issue(idempotency_key="refund:X", order_id="X", amount=10)
    b = services.refunds.issue(idempotency_key="refund:X", order_id="X", amount=10)
    assert a["refund_id"] == b["refund_id"] and b["replayed"] is True
    assert len(services.refunds.ledger) == 1


def test_reply_guard_falls_back_when_llm_leaks_internals():
    leaky = MockChatModel(responder=lambda _: "Denied per RP-2 and our fraud score.")
    facts = {"next_action": "refund_denied", "order_id": "A1", "reason": "Too late."}
    reply = write_reply(leaky, facts)
    assert "RP-" not in reply and "fraud" not in reply
    assert "A1" in reply
