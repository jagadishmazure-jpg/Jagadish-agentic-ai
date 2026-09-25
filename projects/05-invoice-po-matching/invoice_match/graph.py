"""Extraction pipeline + three-way match.

extract 🤖 --invalid (attempt < 2, errors fed back)--> extract
        --invalid after 2 attempts--> draft_exception_note
        --valid--> fetch_erp (RetryPolicy on transient ERP errors; typed business errors
                   become exceptions) --> three_way_match
                      --clean--> approve_for_payment (idempotent post)
                      --exceptions--> draft_exception_note 🤖 -> AP exceptions queue

Doctrine wiring: the ERP is an MCP server reached through a ToolGateway (identity
mi-ap-invoice-matcher; typed business errors re-raised, PO payload schema-validated;
post_invoice is idempotent on the invoice number). The model is a fallback chain: extraction
degrades to the deterministic template parser (validation + the three-way match remain the
gate) and the note to a template. Invoice text is untrusted: suspected injected instructions
are neutralised and force AP review (SUSPICIOUS_CONTENT). Exits go to ``state["exits"]``.
"""

from __future__ import annotations

import json
import operator
import re
from typing import Annotated, Any, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy
from pydantic import ValidationError

from invoice_match import llm as prompts
from invoice_match.erp import (
    ERPUnavailableError,
    MockERP,
    POClosedError,
    PONotFoundError,
    seed_erp,
)
from invoice_match.matching import arithmetic_errors, three_way_match
from invoice_match.schema import Invoice, MatchException, MatchResult
from invoice_match.sor import build_gateway
from shared.context import looks_like_injection, sanitize
from shared.observability import install
from shared.resilience import ModelUnavailableError, exit_record, with_fallback
from shared.tools import SystemOfRecordUnavailableError

MAX_EXTRACTION_ATTEMPTS = 2


class InvoiceState(TypedDict, total=False):
    raw_text: str
    attempts: int
    invoice: dict[str, Any] | None
    extraction_errors: list[str]
    po: dict[str, Any] | None
    received: dict[str, float]
    already_invoiced: dict[str, float]
    exceptions: Annotated[list[dict[str, Any]], operator.add]
    result: dict[str, Any]
    trace: Annotated[list[str], operator.add]
    exits: Annotated[list[dict[str, str]], operator.add]


def build_graph(
    erp: MockERP | None = None,
    llm: BaseChatModel | None = None,
    *,
    retry_interval: float = 0.01,
):
    install()
    erp = erp if erp is not None else seed_erp()
    if llm is None:
        from shared.llm import get_llm

        llm = get_llm(mock_responder=prompts.mock_responder)
    llm = with_fallback(llm)
    gw = build_gateway(erp)

    def erp_call(tool: str, **args: Any) -> Any:
        try:
            return gw.call("erp", tool, **args)
        except SystemOfRecordUnavailableError as exc:  # outage -> node RetryPolicy
            raise ERPUnavailableError(str(exc)) from exc

    def extract(state: InvoiceState) -> dict[str, Any]:
        attempt = state.get("attempts", 0) + 1
        feedback = ""
        if state.get("extraction_errors"):
            feedback = (
                "Your previous extraction failed these checks; re-read the document "
                "carefully: " + "; ".join(state["extraction_errors"]) + "\n"
            )
        text, exits, flagged = state["raw_text"], [], []
        if looks_like_injection(text):  # invoice text is untrusted data
            text = sanitize(text, redact_pii=False).text
            if attempt == 1:
                exits.append(exit_record("extract", "escalate", "suspected prompt injection"))
                flagged.append(
                    MatchException(
                        code="SUSPICIOUS_CONTENT",
                        detail="invoice contains instruction-like text; AP must review",
                    ).model_dump()
                )
        try:
            raw = str(
                llm.invoke(
                    [
                        SystemMessage(prompts.extract_prompt(attempt, feedback)),
                        HumanMessage(text),
                    ]
                ).content
            )
        except ModelUnavailableError:
            raw = json.dumps(prompts.regex_extract(text, careful=attempt > 1))
            exits.append(exit_record("extract", "degrade", "model unavailable: template parser"))
        try:
            m = re.search(r"\{.*\}", raw, re.S)
            inv = Invoice.model_validate_json(m.group(0) if m else raw)
            errors = arithmetic_errors(inv)
        except ValidationError as e:
            inv, errors = None, [f"schema: {x['loc']}: {x['msg']}" for x in e.errors()][:5]
        return {
            "attempts": attempt,
            "invoice": inv.model_dump() if inv and not errors else None,
            "extraction_errors": errors,
            "trace": [f"extract#{attempt}"],
            "exits": exits,
            "exceptions": flagged,
        }

    def after_extract(state: InvoiceState) -> str:
        if state["invoice"]:
            return "fetch_erp"
        return "extract" if state["attempts"] < MAX_EXTRACTION_ATTEMPTS else "extraction_failed"

    def extraction_failed(state: InvoiceState) -> dict[str, Any]:
        exc = MatchException(code="EXTRACTION_FAILED", detail="; ".join(state["extraction_errors"]))
        return {"exceptions": [exc.model_dump()], "trace": ["extraction_failed"]}

    def fetch_erp(state: InvoiceState) -> dict[str, Any]:
        # ERPUnavailableError propagates -> RetryPolicy retries this node. Business errors are
        # typed and converted into exceptions (they won't fix themselves on retry).
        inv = state["invoice"]
        if erp_call("is_invoice_posted", invoice_number=inv["invoice_number"])["posted"]:
            exc = MatchException(
                code="DUPLICATE_INVOICE",
                detail=f"{inv['invoice_number']} was already posted in AP",
            )
            return {"po": None, "exceptions": [exc.model_dump()], "trace": ["fetch_erp"]}
        try:
            po = erp_call("get_purchase_order", po_number=inv["po_number"])
        except PONotFoundError as e:
            return {
                "po": None,
                "trace": ["fetch_erp"],
                "exceptions": [MatchException(code="PO_NOT_FOUND", detail=str(e)).model_dump()],
            }
        except POClosedError as e:
            return {
                "po": None,
                "trace": ["fetch_erp"],
                "exceptions": [MatchException(code="PO_CLOSED", detail=str(e)).model_dump()],
            }
        return {
            "po": po,
            "received": erp_call("get_goods_receipts", po_number=inv["po_number"]),
            "already_invoiced": erp_call("get_invoiced_quantities", po_number=inv["po_number"]),
            "trace": ["fetch_erp"],
        }

    def after_fetch(state: InvoiceState) -> str:
        return "three_way_match" if state.get("po") else "draft_exception_note"

    def match(state: InvoiceState) -> dict[str, Any]:
        found = three_way_match(
            state["invoice"], state["po"], state["received"], state["already_invoiced"]
        )
        return {"exceptions": [e.model_dump() for e in found], "trace": ["three_way_match"]}

    def after_match(state: InvoiceState) -> str:
        return "draft_exception_note" if state.get("exceptions") else "approve_for_payment"

    def approve_for_payment(state: InvoiceState) -> dict[str, Any]:
        inv = state["invoice"]
        doc = erp_call(
            "post_invoice",
            invoice=inv,
            idempotency_key=f"ap:{inv['invoice_number']}",
            dry_run=False,
        )["document_id"]
        res = MatchResult(
            invoice_number=inv["invoice_number"],
            po_number=inv["po_number"],
            status="approved",
            extraction_attempts=state["attempts"],
            payment_doc=doc,
            route_to="payment_run",
        )
        return {"result": res.model_dump(), "trace": ["approve_for_payment"]}

    def draft_exception_note(state: InvoiceState) -> dict[str, Any]:
        inv = state.get("invoice") or {}
        payload = {
            "invoice_number": inv.get("invoice_number"),
            "po_number": inv.get("po_number"),
            "vendor": inv.get("vendor"),
            "exceptions": state["exceptions"],
        }
        exits = []
        try:
            note = str(
                llm.invoke(
                    [SystemMessage(prompts.NOTE_SYSTEM), HumanMessage(json.dumps(payload))]
                ).content
            ).strip()
        except ModelUnavailableError:
            note = ""
            exits = [exit_record("draft_exception_note", "degrade", "model down: template note")]
        # Guard: the note must mention every exception code, otherwise use a plain template.
        if not note or any(e["code"] not in note for e in state["exceptions"]):
            note = "Exceptions:\n" + "\n".join(
                f"- {e['code']}: {e['detail']}" for e in state["exceptions"]
            )
        res = MatchResult(
            invoice_number=inv.get("invoice_number"),
            po_number=inv.get("po_number"),
            status="exception",
            exceptions=[MatchException(**e) for e in state["exceptions"]],
            extraction_attempts=state["attempts"],
            exception_note=note,
            route_to="ap_exceptions_queue",
        )
        return {"result": res.model_dump(), "trace": ["draft_exception_note"], "exits": exits}

    g = StateGraph(InvoiceState)
    g.add_node("extract", extract)
    g.add_node("extraction_failed", extraction_failed)
    g.add_node(
        "fetch_erp",
        fetch_erp,
        retry_policy=RetryPolicy(
            max_attempts=3,
            initial_interval=retry_interval,
            jitter=False,
            retry_on=ERPUnavailableError,
        ),
    )
    g.add_node("three_way_match", match)
    g.add_node("approve_for_payment", approve_for_payment)
    g.add_node("draft_exception_note", draft_exception_note)
    g.add_edge(START, "extract")
    g.add_conditional_edges("extract", after_extract, ["fetch_erp", "extract", "extraction_failed"])
    g.add_edge("extraction_failed", "draft_exception_note")
    g.add_conditional_edges("fetch_erp", after_fetch, ["three_way_match", "draft_exception_note"])
    g.add_conditional_edges(
        "three_way_match", after_match, ["approve_for_payment", "draft_exception_note"]
    )
    g.add_edge("approve_for_payment", END)
    g.add_edge("draft_exception_note", END)
    compiled = g.compile(name="invoice-po-matching")
    compiled.gateway = gw
    return compiled
