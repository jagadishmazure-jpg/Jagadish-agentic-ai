import pytest

from invoice_match.erp import ERPUnavailableError
from invoice_match.graph import build_graph
from invoice_match.invoices import INVOICES
from invoice_match.llm import mock_responder
from invoice_match.matching import three_way_match
from invoice_match.schema import MatchResult
from shared.llm import MockChatModel


def codes(r):
    return sorted({e["code"] for e in r["result"]["exceptions"]})


def test_clean_invoice_is_approved_and_posted(graph, erp):
    r = graph.invoke({"raw_text": INVOICES["clean"]})
    res = MatchResult.model_validate(r["result"])
    assert res.status == "approved" and res.route_to == "payment_run"
    assert res.payment_doc == erp.posted["INV-1001"]["doc"]
    assert r["trace"] == ["extract#1", "fetch_erp", "three_way_match", "approve_for_payment"]


def test_variances_become_typed_exceptions_with_note(graph, erp):
    r = graph.invoke({"raw_text": INVOICES["variance"]})
    assert r["result"]["status"] == "exception"
    assert codes(r) == ["PRICE_VARIANCE", "QTY_EXCEEDS_RECEIPT", "UNKNOWN_LINE"]
    note = r["result"]["exception_note"]
    assert all(c in note for c in codes(r)) and "Next step" in note
    assert erp.posted == {}


def test_po_not_found_is_business_exception(graph):
    r = graph.invoke({"raw_text": INVOICES["no_po"]})
    assert codes(r) == ["PO_NOT_FOUND"] and "three_way_match" not in r["trace"]


def test_closed_po(graph):
    text = INVOICES["clean"].replace("PO-5001", "PO-5009")
    r = graph.invoke({"raw_text": text})
    assert codes(r) == ["PO_CLOSED"]


def test_duplicate_invoice_is_never_paid_twice(graph, erp):
    graph.invoke({"raw_text": INVOICES["clean"]})
    r = graph.invoke({"raw_text": INVOICES["clean"]})
    assert codes(r) == ["DUPLICATE_INVOICE"]
    assert len(erp.posted) == 1
    assert erp.post_invoice({"invoice_number": "INV-1001"}) == erp.posted["INV-1001"]["doc"]


def test_extraction_retry_with_feedback_recovers(graph):
    r = graph.invoke({"raw_text": INVOICES["messy"]})
    assert r["trace"][:2] == ["extract#1", "extract#2"]
    assert r["result"]["status"] == "approved" and r["result"]["extraction_attempts"] == 2


def test_feedback_is_passed_to_second_attempt(erp):
    prompts = []

    def spy(msgs):
        prompts.append(str(msgs[0].content))
        return mock_responder(msgs)

    build_graph(erp, llm=MockChatModel(responder=spy)).invoke({"raw_text": INVOICES["messy"]})
    assert "sum of lines 160.00 != subtotal 410.00" in prompts[1]


def test_extraction_fails_after_budget(erp):
    g = build_graph(
        erp,
        llm=MockChatModel(
            responder=lambda m: "no idea" if "EXTRACT" in str(m[0].content) else mock_responder(m)
        ),
    )
    r = g.invoke({"raw_text": INVOICES["clean"]})
    assert r["trace"][:3] == ["extract#1", "extract#2", "extraction_failed"]
    assert codes(r) == ["EXTRACTION_FAILED"] and r["result"]["route_to"] == "ap_exceptions_queue"


def test_transient_erp_error_is_retried_by_retry_policy(graph, erp):
    erp.unavailable_for = 2
    r = graph.invoke({"raw_text": INVOICES["clean"]})
    assert r["result"]["status"] == "approved"
    assert r["trace"].count("fetch_erp") == 1  # retries are inside the node, not new steps


def test_persistent_erp_outage_propagates_not_misfiled_as_exception(graph, erp):
    erp.unavailable_for = 10
    with pytest.raises(ERPUnavailableError):
        graph.invoke({"raw_text": INVOICES["clean"]})
    assert erp.posted == {}


def test_price_within_tolerance_matches():
    po = {
        "vendor": "V",
        "currency": "USD",
        "lines": [{"sku": "A-1", "qty": 10, "unit_price": 10.0}],
    }
    inv = {
        "vendor": "v ",
        "currency": "USD",
        "lines": [{"sku": "A-1", "description": "a", "qty": 10, "unit_price": 10.15}],
    }
    assert three_way_match(inv, po, {"A-1": 10}, {}) == []
    inv["lines"][0]["unit_price"] = 10.30
    assert [e.code for e in three_way_match(inv, po, {"A-1": 10}, {})] == ["PRICE_VARIANCE"]


def test_note_guard_falls_back_to_template(erp):
    def lazy(msgs):
        if "EXCEPTION_NOTE" in str(msgs[0].content):
            return "Looks fine, pay it."
        return mock_responder(msgs)

    r = build_graph(erp, llm=MockChatModel(responder=lazy)).invoke(
        {"raw_text": INVOICES["variance"]}
    )
    assert r["result"]["exception_note"].startswith("Exceptions:")
    assert "PRICE_VARIANCE" in r["result"]["exception_note"]
