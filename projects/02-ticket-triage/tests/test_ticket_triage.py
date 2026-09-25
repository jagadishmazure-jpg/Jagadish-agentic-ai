import pytest

from shared.llm import MockChatModel
from ticket_triage.graph import build_graph
from ticket_triage.llm import mock_responder
from ticket_triage.pii import luhn_ok, redact
from ticket_triage.schema import TriageResult


@pytest.mark.parametrize(
    ("body", "queue"),
    [
        ("I was charged twice on my invoice, please refund", "billing_queue"),
        ("The mobile app shows an error and crash on launch", "tech_support_queue"),
        ("Locked out, password reset fails and login loops", "account_security_queue"),
        (
            "Feature suggestion: would be great to export CSV, please add it",
            "product_feedback_queue",
        ),
        ("Please cancel and close my account, we are switching to a competitor", "retention_queue"),
    ],
)
def test_routes_to_intent_queue(triage, body, queue):
    r = triage(body)
    res = TriageResult.model_validate(r["result"])
    assert res.route == "queue" and res.queue == queue
    assert r["trace"][-1] == queue


def test_critical_urgency_pages_on_call_with_1h_sla(triage):
    r = triage("Production down: API endpoint returns 500 error for all customers")
    assert r["result"]["page_on_call"] is True and r["result"]["sla_hours"] == 1


def test_mid_confidence_asks_clarifying_question(triage):
    r = triage("The dashboard is broken.")
    assert r["result"]["route"] == "clarify"
    assert r["result"]["classification"]["confidence"] < 0.6
    assert "?" in r["result"]["customer_reply"]


def test_low_confidence_goes_to_human(triage):
    r = triage("Hi there, quick question for you.")
    assert r["result"]["route"] == "human_review"
    assert r["result"]["queue"] == "triage_human_queue"


def test_pii_is_redacted_before_any_llm_call(triage):
    seen = []

    def spy(msgs):
        seen.extend(str(m.content) for m in msgs)
        return mock_responder(msgs)

    g = build_graph(llm=MockChatModel(responder=spy))
    body = (
        "Refund my invoice. Card 4111 1111 1111 1111, SSN 123-45-6789, "
        "email a.b@example.com, phone 555-123-4567, order 1234567890123"
    )
    r = triage(body, g=g)
    blob = "\n".join(seen)
    for secret in ("4111 1111 1111 1111", "123-45-6789", "a.b@example.com", "555-123-4567"):
        assert secret not in blob
    assert "1234567890123" in blob  # non-Luhn long number (order id) is kept
    assert r["result"]["redactions"] == {"EMAIL": 1, "CARD": 1, "SSN": 1, "PHONE": 1}
    assert "vault" not in r  # originals are never stored in graph state


def test_redact_unit_and_luhn():
    text, vault, counts = redact("mail x@y.io or x2@y.io")
    assert counts["EMAIL"] == 2
    assert text == "mail [EMAIL_1] or [EMAIL_2]" and vault["[EMAIL_2]"] == "x2@y.io"
    assert luhn_ok("4111111111111111") and not luhn_ok("4111111111111112")


def test_invalid_schema_is_repaired_once(triage):
    calls = {"n": 0}

    def flaky(msgs):
        if str(msgs[0].content).startswith("TASK: CLASSIFY"):
            calls["n"] += 1
            return '{"intent": "billing", "urgency": "URGENT!!!", "confidence": 3}'
        return mock_responder(msgs)  # repair prompt -> valid JSON

    r = triage(
        "I was charged twice on my invoice", g=build_graph(llm=MockChatModel(responder=flaky))
    )
    assert r["trace"] == [
        "redact_pii",
        "classify",
        "validate",
        "repair",
        "validate",
        "billing_queue",
    ]
    assert r["result"]["repair_attempts"] == 1


def test_repair_failure_escalates_to_human(triage):
    g = build_graph(llm=MockChatModel(responder=lambda _: "sorry, I can't produce JSON"))
    r = triage("I was charged twice on my invoice", g=g)
    assert r["trace"].count("repair") == 1
    assert r["result"]["route"] == "human_review"
    assert "schema validation failed" in r["result"]["reason"]
    assert r["result"]["classification"] is None
