"""Technician copilot graph.

intake (VIN decode via MCP, concern sanitised) -> [tsb (as-of repair date, applicability,
supersession: current TSB wins) || diagrams (caption-indexed wiring images, applicability)] ->
procedure (model guidance; safety check: torque specs and part numbers only from current TSBs,
citations only to retrieved TSBs/images) -> parts (ATP via MCP, part supersession) ->
warranty (coverage tool) -> warranty_approval (always HITL when covered) -> finalize
"""

from __future__ import annotations

import json
import operator
import re
from collections.abc import Sequence
from datetime import date
from typing import Annotated, Any, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Send, interrupt

from shared.context import RetrievalError, looks_like_injection, sanitize
from shared.llm import get_llm
from shared.observability import install
from shared.resilience import ModelUnavailableError, exit_record, with_fallback
from shared.tools import SystemOfRecordUnavailableError
from tech_copilot.knowledge import DOCS, REGISTRY, applies, builder, current_only, principal
from tech_copilot.sor import gateways
from tech_copilot.systems import Systems, seed_systems

TORQUE = re.compile(r"\b(\d+(?:\.\d+)?)\s?Nm\b")
PART = re.compile(r"\b\d{2}-\d{4}-[A-Z]\b")
CITE = re.compile(r"\[((?:TSB|IMG)-[A-Z0-9-]+)\]")
WARRANTY_ADMINS = {"wa-rivera", "wa-chen"}
TEXT = {d.doc_id: d.text.split(": ", 1)[1] for d in DOCS}


def specs(text: str) -> set[str]:
    return {f"{t} Nm" for t in TORQUE.findall(text)} | set(PART.findall(text))


def procedure_template(f: dict[str, Any]) -> str:
    if not f["tsbs"]:
        return (
            "No current TSB applies to this vehicle and concern. Follow the standard "
            "diagnostic flow for the DTCs."
        )
    out = [f"Per [{t}]: {TEXT[t]}" for t in f["tsbs"]]
    out += [f"Wiring: [{i}] {TEXT[i]}" for i in f["images"]]
    return "\n".join(out)


def mock_responder(msgs: Sequence[BaseMessage]) -> str:
    if "TASK: PROCEDURE" in str(msgs[0].content):
        return procedure_template(json.loads(str(msgs[-1].content)))
    return ""


def stale_responder(msgs: Sequence[BaseMessage]) -> str:
    """A model that 'remembers' the old bulletin's spec and part (wrong version)."""
    if "TASK: PROCEDURE" in str(msgs[0].content):
        return "Replace the coolant pump with 11-4455-A and torque the bolts to 25 Nm [TSB-21-044]."
    return ""


class TechState(TypedDict, total=False):
    request: dict[str, Any]
    vehicle: dict[str, Any]
    concern: str
    tsbs: list[str]
    dropped: dict[str, list[str]]
    images: list[str]
    procedure: str
    parts: list[dict[str, Any]]
    coverage: dict[str, Any] | None
    approval: dict[str, Any]
    claim: dict[str, Any] | None
    outcome: str
    exits: Annotated[list, operator.add]
    trace: Annotated[list, operator.add]


def build_graph(
    systems: Systems | None = None, llm: BaseChatModel | None = None, checkpointer: Any = None
):
    install()
    s = systems or seed_systems()
    gw = gateways(s)
    kb = builder()
    model = with_fallback(llm or get_llm(mock_responder=mock_responder))

    def as_of(state: TechState) -> date:
        return date.fromisoformat(state["request"]["repair_date"])

    def intake(state: TechState) -> Command:
        r = state["request"]
        try:
            v = gw["reader"].call("vehicle", "decode_vin", vin=r["vin"])
        except (SystemOfRecordUnavailableError, KeyError) as exc:
            return Command(
                goto=END,
                update={
                    "outcome": "vin_unresolved",
                    "trace": ["intake"],
                    "procedure": "Vehicle could not be identified; no bulletin guidance given.",
                    "exits": [exit_record("intake", "escalate", f"VIN decode failed: {exc}")],
                },
            )
        exits = []
        concern = r["concern"]
        if looks_like_injection(concern):
            exits.append(
                exit_record("intake", "degrade", "instruction-like text in concern neutralised")
            )
        concern = sanitize(concern).text
        upd = {"vehicle": v, "concern": concern, "exits": exits, "trace": ["intake"]}
        return Command(
            goto=[Send("tsb", {**state, **upd}), Send("diagrams", {**state, **upd})], update=upd
        )

    def query(state: TechState) -> str:
        return f"{state['concern']} {' '.join(state['request'].get('dtcs', []))}"

    def tsb(state: TechState) -> dict[str, Any]:
        v, d = state["vehicle"], as_of(state)
        try:
            b = kb.build(query(state), principal(), as_of=d, k=8, kinds=["tsb"])
        except RetrievalError as exc:
            return {
                "tsbs": [],
                "dropped": {},
                "trace": ["tsb"],
                "exits": [exit_record("tsb", "degrade", f"bulletins unavailable: {exc}")],
            }
        hits = list(dict.fromkeys(c.split("::")[0] for c in b.chunk_ids))
        fit = [h for h in hits if applies(h, v)]
        valid = {
            doc.doc_id
            for doc in DOCS
            if doc.kind == "tsb"
            and applies(doc.doc_id, v)
            and (doc.valid_from is None or doc.valid_from <= d)
            and (doc.valid_to is None or d <= doc.valid_to)
        }
        keep, superseded = current_only(fit, valid)
        return {
            "tsbs": keep,
            "trace": ["tsb"],
            "dropped": {
                "superseded": superseded,
                "not_applicable": [h for h in hits if h not in fit],
            },
        }

    def diagrams(state: TechState) -> dict[str, Any]:
        try:
            b = kb.build(
                f"wiring diagram connector circuit {query(state)}",
                principal(),
                as_of=as_of(state),
                k=4,
                kinds=["image"],
            )
        except RetrievalError as exc:
            return {
                "images": [],
                "trace": ["diagrams"],
                "exits": [exit_record("diagrams", "degrade", f"diagrams unavailable: {exc}")],
            }
        ids = list(dict.fromkeys(c.split("::")[0] for c in b.chunk_ids))
        return {
            "images": [i for i in ids if applies(i, state["vehicle"])],
            "trace": ["diagrams"],
        }

    def procedure(state: TechState) -> dict[str, Any]:
        systems_ = {REGISTRY[t].op_code for t in state["tsbs"]}
        images = [i for i in state["images"] if REGISTRY[i].op_code in systems_]
        f = {
            "vehicle": state["vehicle"],
            "concern": state["concern"],
            "tsbs": state["tsbs"],
            "images": images,
            "bulletins": {t: TEXT[t] for t in state["tsbs"]},
            "captions": {i: TEXT[i] for i in images},
        }
        exits = []
        try:
            text = str(
                model.invoke(
                    [
                        SystemMessage(
                            "TASK: PROCEDURE\nGive repair guidance using only the current "
                            "bulletins and diagrams provided. Cite [TSB-..] and [IMG-..]."
                        ),
                        HumanMessage(json.dumps(f)),
                    ]
                ).content
            )
        except ModelUnavailableError:
            text = procedure_template(f)
            exits.append(exit_record("procedure", "degrade", "model down: bulletin text"))
        allowed_specs = (
            set().union(*(specs(TEXT[t]) for t in state["tsbs"])) if state["tsbs"] else set()
        )
        bad_specs = specs(text) - allowed_specs
        bad_cites = set(CITE.findall(text)) - set(state["tsbs"]) - set(images)
        if bad_specs or bad_cites:  # wrong-version safety: never pass on stale specs
            text = procedure_template(f)
            exits.append(
                exit_record(
                    "procedure",
                    "degrade",
                    f"safety: specs {sorted(bad_specs)}"
                    f" cites {sorted(bad_cites)} not from current TSBs",
                )
            )
        return {"procedure": text, "images": images, "exits": exits, "trace": ["procedure"]}

    def parts(state: TechState) -> dict[str, Any]:
        out, exits = [], []
        for t in state["tsbs"]:
            for pn in REGISTRY[t].parts:
                try:
                    a = gw["reader"].call(
                        "parts", "check_atp", part_number=pn, dealer=state["request"]["dealer"]
                    )
                    if "superseded_by" in a:
                        a = {
                            **gw["reader"].call(
                                "parts",
                                "check_atp",
                                part_number=a["superseded_by"],
                                dealer=state["request"]["dealer"],
                            ),
                            "replaces": pn,
                        }
                    out.append(a)
                except SystemOfRecordUnavailableError:
                    out.append({"part_number": pn, "on_hand": None})
                    if not exits:
                        exits.append(
                            exit_record(
                                "parts",
                                "degrade",
                                "parts system down: ATP unknown, check with parts counter",
                            )
                        )
        return {"parts": out, "exits": exits, "trace": ["parts"]}

    def warranty(state: TechState) -> Command:
        if not state["tsbs"]:
            return Command(goto="finalize", update={"coverage": None, "trace": ["warranty"]})
        op = REGISTRY[state["tsbs"][0]].op_code
        try:
            c = gw["reader"].call(
                "warranty",
                "check_coverage",
                vin=state["request"]["vin"],
                op_code=op,
                repair_date=state["request"]["repair_date"],
            )
        except SystemOfRecordUnavailableError as exc:
            return Command(
                goto="finalize",
                update={
                    "coverage": {"covered": None, "op_code": op},
                    "trace": ["warranty"],
                    "exits": [exit_record("warranty", "degrade", f"coverage unknown: {exc}")],
                },
            )
        c = {**c, "op_code": op}
        return Command(
            goto="warranty_approval" if c["covered"] else "finalize",
            update={"coverage": c, "trace": ["warranty"]},
        )

    def warranty_approval(state: TechState) -> dict[str, Any]:
        d = interrupt(
            {
                "type": "warranty_claim",
                "ro": state["request"]["ro"],
                "vin": state["request"]["vin"],
                "coverage": state["coverage"],
                "tsbs": state["tsbs"],
                "parts": state["parts"],
            }
        )
        who = d.get("admin", "")
        if who not in WARRANTY_ADMINS:
            return {
                "approval": {"decision": "refused"},
                "trace": ["warranty_approval"],
                "exits": [
                    exit_record(
                        "warranty_approval",
                        "escalate",
                        f"{who or 'caller'} is not a warranty administrator",
                    )
                ],
            }
        return {
            "approval": {"decision": d.get("decision", "reject"), "admin": who},
            "trace": ["warranty_approval"],
        }

    def finalize(state: TechState) -> dict[str, Any]:
        c, ap = state.get("coverage"), state.get("approval") or {}
        exits = []
        claim = None
        if c and c.get("covered") and ap.get("decision") == "approve":
            try:
                claim = gw["claims"].call(
                    "warranty",
                    "submit_claim",
                    claim={
                        "ro": state["request"]["ro"],
                        "vin": state["request"]["vin"],
                        "op_code": c["op_code"],
                        "tsb": state["tsbs"][0],
                        "parts": [p["part_number"] for p in state["parts"]],
                        "approved_by": ap["admin"],
                    },
                    idempotency_key=f"claim:{state['request']['ro']}",
                    dry_run=False,
                )
                outcome = "warranty_claim_submitted"
            except SystemOfRecordUnavailableError as exc:
                outcome = "warranty_claim_pending"
                exits.append(exit_record("finalize", "degrade", f"warranty system: {exc}"))
        elif c and c.get("covered"):
            outcome = "warranty_not_approved"
        elif c and c.get("covered") is None:
            outcome = "coverage_unknown"
        elif c:
            outcome = "customer_pay"
        else:
            outcome = "diagnose"
        return {"claim": claim, "outcome": outcome, "exits": exits, "trace": ["finalize"]}

    g = StateGraph(TechState)
    g.add_node("intake", intake, destinations=("tsb", "diagrams", END))
    g.add_node("tsb", tsb)
    g.add_node("diagrams", diagrams)
    g.add_node("procedure", procedure)
    g.add_node("parts", parts)
    g.add_node("warranty", warranty, destinations=("warranty_approval", "finalize"))
    g.add_node("warranty_approval", warranty_approval)
    g.add_node("finalize", finalize)
    g.add_edge(START, "intake")
    g.add_edge(["tsb", "diagrams"], "procedure")
    g.add_edge("procedure", "parts")
    g.add_edge("parts", "warranty")
    g.add_edge("warranty_approval", "finalize")
    g.add_edge("finalize", END)
    return g.compile(checkpointer=checkpointer or MemorySaver(), name="tech_copilot")
