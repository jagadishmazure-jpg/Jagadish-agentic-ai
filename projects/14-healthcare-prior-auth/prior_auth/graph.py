"""Prior-authorization graph.

provider channel: intake (PHI redaction, fact extraction, injection flag) ->
  [eligibility (MCP; failure -> 'unknown') || policy (ACL + plan-year RAG)] -> criteria
  (deterministic) -> coverage_language (subgraph behind a kill switch) -> draft_packet
  (draft only) -> clinician_approval (interrupt) -> submit (clinician-signed)
member channel: intake -> member_reply (status only; hard guardrail against medical advice)
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

from prior_auth import criteria as crit
from prior_auth.knowledge import builder, principal
from prior_auth.phi import install_log_filter, redact
from prior_auth.sor import gateways
from prior_auth.systems import CLINICIANS, MEMBERS, Systems, seed_systems
from shared.context import RetrievalError, looks_like_injection
from shared.llm import get_llm
from shared.observability import install
from shared.resilience import ModelUnavailableError, exit_record, with_fallback
from shared.tools import RemoteToolError, SystemOfRecordUnavailableError

ADVICE = re.compile(
    r"\byou should\b|\bi recommend\b|\bwe recommend\b|\btry (taking|using)\b|\b\d+\s?mg\b|"
    r"\bdosage\b|\b(stop|start) taking\b|\bibuprofen|\bnaproxen|\bstretch(es|ing)?\b|"
    r"\bice (it|the)\b|\byou (probably |likely )?have\b|\bsurgery is\b",
    re.I,
)
ASKS_ADVICE = re.compile(
    r"\bshould i\b|\bwhat (should|can) i take\b|\bis it safe\b|\bhow much\b.*\btake\b|"
    r"\bwhat do you recommend\b|\bhow (do|can) i treat\b",
    re.I,
)
REFUSAL = (
    "I can't give medical advice. Please talk to your doctor, or call the 24/7 nurse "
    "line on the back of your member card."
)
CITE = re.compile(r"\[([A-Z0-9-]+)\]")
log = install_log_filter(m["name"] for m in MEMBERS.values())


def coverage_template(f: dict[str, Any]) -> str:
    c = f["criteria"]
    cites = " ".join(f"[{d}]" for d in c["policies"])
    met = "; ".join(c["met"]) or "none documented"
    unmet = "; ".join(c["unmet"]) or "none"
    return f"Criteria met: {met}. Criteria not met: {unmet}. Policy basis: {cites}."


def member_template(f: dict[str, Any]) -> str:
    if not f["requests"]:
        return "We don't see a prior authorization request on file for you yet."
    parts = [f"CPT {r['cpt']}: {r['status']}" for r in f["requests"]]
    return "Your prior authorization requests: " + "; ".join(parts) + "."


def mock_responder(msgs: Sequence[BaseMessage]) -> str:
    sys_, human = str(msgs[0].content), str(msgs[-1].content)
    if "TASK: COVERAGE" in sys_:
        return "Medical necessity summary. " + coverage_template(json.loads(human))
    if "TASK: MEMBER" in sys_:
        return member_template(json.loads(human))
    return ""


class PAState(TypedDict, total=False):
    request: dict[str, Any]
    note_redacted: str
    facts: dict[str, Any]
    flags: list[str]
    eligibility: dict[str, Any]
    retrieved: list[str]
    citations: list[str]
    criteria: dict[str, Any]
    narrative: str | None
    packet: dict[str, Any]
    draft_id: str
    approval: dict[str, Any]
    submission: dict[str, Any] | None
    answer: str
    exits: Annotated[list, operator.add]
    trace: Annotated[list, operator.add]


def build_coverage_language(model, switches):
    """The coverage-language subgraph (model wording of the criteria) - behind a kill switch."""

    class CL(TypedDict, total=False):
        criteria: dict[str, Any]
        retrieved: list[str]
        note_redacted: str
        narrative: str | None
        exits: Annotated[list, operator.add]

    def draft(state: CL) -> dict[str, Any]:
        if not switches.coverage_language:
            return {
                "narrative": None,
                "exits": [
                    exit_record(
                        "coverage_language", "degrade", "kill switch: coverage language disabled"
                    )
                ],
            }
        facts = {"criteria": state["criteria"], "note": state["note_redacted"]}
        try:
            text = str(
                model.invoke(
                    [
                        SystemMessage(
                            "TASK: COVERAGE\nSummarise medical necessity against the cited "
                            "policy only. Cite policies as [ID]. No patient identifiers."
                        ),
                        HumanMessage(json.dumps(facts)),
                    ]
                ).content
            )
        except ModelUnavailableError:
            return {
                "narrative": coverage_template(state),
                "exits": [exit_record("coverage_language", "degrade", "model down")],
            }
        return {"narrative": text}

    def cite_check(state: CL) -> dict[str, Any]:
        text = state.get("narrative")
        if text is None:
            return {}
        cited = set(CITE.findall(text))
        bad = cited - set(state["retrieved"]) or (not cited and state["criteria"]["policies"])
        if bad or redact(text) != text:
            return {
                "narrative": coverage_template(state),
                "exits": [
                    exit_record(
                        "coverage_language", "degrade", "uncited / unretrieved citation or PHI"
                    )
                ],
            }
        return {}

    g = StateGraph(CL)
    g.add_node("draft", draft)
    g.add_node("cite_check", cite_check)
    g.add_edge(START, "draft")
    g.add_edge("draft", "cite_check")
    g.add_edge("cite_check", END)
    return g.compile(name="coverage_language")


def build_graph(
    systems: Systems | None = None, llm: BaseChatModel | None = None, checkpointer: Any = None
):
    install()
    s = systems or seed_systems()
    gw = gateways(s)
    kb = builder()
    model = with_fallback(llm or get_llm(mock_responder=mock_responder))
    coverage_language = build_coverage_language(model, s.switches)

    # ------------------------------------------------------------------ intake
    def intake(state: PAState) -> Command:
        r = state["request"]
        if r.get("channel") == "member":
            log.info("member question member=%s q=%s", r["member_id"], r.get("question", ""))
            return Command(goto="member_reply", update={"trace": ["intake"]})
        raw = r["note"]
        # deliberately raw: the PhiFilter on the logger must redact it (tested)
        log.info(
            "pa request member=%s patient=%s cpt=%s note=%s",
            r["member_id"],
            r["patient_name"],
            r["cpt"],
            raw[:120],
        )
        flags, exits = [], []
        if looks_like_injection(raw):
            flags.append("clinical note contained instruction-like text (removed)")
            exits.append(
                exit_record(
                    "intake", "escalate", "injected text in note: flagged for clinician review"
                )
            )
        red = redact(raw, [r["patient_name"]])
        upd = {
            "note_redacted": red,
            "facts": crit.extract_facts(raw),
            "flags": flags,
            "exits": exits,
            "trace": ["intake"],
        }
        return Command(
            goto=[Send("eligibility", {**state, **upd}), Send("policy", {**state, **upd})],
            update=upd,
        )

    # ------------------------------------------------------------------ eligibility
    def eligibility(state: PAState) -> dict[str, Any]:
        r = state["request"]
        try:
            e = gw["reader"].call(
                "eligibility", "check_eligibility", member_id=r["member_id"], dos=r["dos"]
            )
        except (SystemOfRecordUnavailableError, KeyError, RemoteToolError) as exc:
            return {
                "eligibility": {"status": "unknown", "plan": r["plan"]},
                "trace": ["eligibility"],
                "exits": [exit_record("eligibility", "degrade", f"unknown: {exc}")],
            }
        status = "eligible" if e["eligible"] else "ineligible"
        exits = []
        if e["plan"] != r["plan"]:
            exits.append(exit_record("eligibility", "escalate", "plan on card != payer plan"))
            status = "unknown"
        return {
            "eligibility": {"status": status, "plan": e["plan"]},
            "exits": exits,
            "trace": ["eligibility"],
        }

    # ------------------------------------------------------------------ policy (RAG)
    def policy(state: PAState) -> dict[str, Any]:
        r = state["request"]
        try:
            b = kb.build(
                f"CPT {r['cpt']} medical necessity criteria conservative therapy "
                "advanced imaging referral",
                principal(r["plan"]),
                as_of=date.fromisoformat(r["dos"]),
                k=6,
                facts=[("clinical-note", state["note_redacted"])],
            )
        except RetrievalError as exc:
            return {
                "retrieved": [],
                "citations": [],
                "trace": ["policy"],
                "exits": [exit_record("policy", "degrade", f"policies unavailable: {exc}")],
            }
        return {
            "retrieved": sorted({c.split("::")[0] for c in b.chunk_ids}),
            "citations": b.chunk_ids,
            "trace": ["policy"],
        }

    # ------------------------------------------------------------------ criteria
    def criteria(state: PAState) -> Command:
        r, e = state["request"], state["eligibility"]
        if e["status"] == "ineligible":
            return Command(
                goto=END,
                update={
                    "criteria": {"status": "ineligible", "policies": [], "met": [], "unmet": []},
                    "answer": "Member is not eligible on the date of service; no packet drafted. "
                    "Verify coverage with the member.",
                    "trace": ["criteria"],
                    "exits": [exit_record("criteria", "escalate", "member not eligible on DOS")],
                },
            )
        c = crit.evaluate(r["cpt"], r["plan"], r["dos"][:4], state["facts"])
        exits = []
        missing = [d for d in c["policies"] if d not in state["retrieved"]]
        if missing or c["status"] == "unknown":
            c = {
                "status": "unknown",
                "policies": [],
                "met": [],
                "unmet": c["unmet"] or [f"policy not retrieved: {missing}"],
            }
            exits.append(exit_record("criteria", "degrade", "criteria not evaluable"))
        cites = [x for x in state["citations"] if x.split("::")[0] in c["policies"]]
        return Command(
            goto="coverage_language",
            update={"criteria": c, "citations": cites, "exits": exits, "trace": ["criteria"]},
        )

    # ------------------------------------------------------------------ coverage language
    def coverage_language_node(state: PAState) -> dict[str, Any]:
        out = coverage_language.invoke(
            {k: state[k] for k in ("criteria", "retrieved", "note_redacted")}
        )
        return {
            "narrative": out.get("narrative"),
            "exits": out.get("exits", []),
            "trace": ["coverage_language"],
        }

    # ------------------------------------------------------------------ draft (draft only)
    def draft_packet(state: PAState, config) -> Command:
        r = state["request"]
        packet = {
            "member_id": r["member_id"],
            "plan": r["plan"],
            "cpt": r["cpt"],
            "icd10": r["icd10"],
            "dos": r["dos"],
            "requesting_npi": r.get("npi", ""),
            "eligibility": state["eligibility"]["status"],
            "criteria": state["criteria"],
            "citations": state["citations"],
            "narrative": state.get("narrative"),
            "flags": state["flags"]
            + (
                ["eligibility unknown - verify before service"]
                if state["eligibility"]["status"] == "unknown"
                else []
            ),
        }
        try:
            d = gw["drafter"].call(
                "pa_portal",
                "save_draft",
                packet=packet,
                idempotency_key=f"pa:{config['configurable']['thread_id']}",
                dry_run=False,
            )
        except SystemOfRecordUnavailableError as exc:
            return Command(
                goto=END,
                update={
                    "packet": packet,
                    "trace": ["draft_packet"],
                    "answer": "The PA portal is unavailable; the packet is prepared but not saved. "
                    "Nothing was submitted.",
                    "exits": [exit_record("draft_packet", "degrade", f"portal down: {exc}")],
                },
            )
        return Command(
            goto="clinician_approval",
            update={"packet": packet, "draft_id": d["draft_id"], "trace": ["draft_packet"]},
        )

    # ------------------------------------------------------------------ clinician approval
    def clinician_approval(state: PAState) -> dict[str, Any]:
        d = interrupt(
            {"type": "clinician_signoff", "draft_id": state["draft_id"], "packet": state["packet"]}
        )
        who = d.get("clinician", "")
        if who not in CLINICIANS:
            return {
                "approval": {
                    "decision": "rejected",
                    "why": f"{who or 'caller'} is not a registered clinician",
                },
                "trace": ["clinician_approval"],
                "exits": [
                    exit_record(
                        "clinician_approval", "escalate", "sign-off by a non-clinician refused"
                    )
                ],
            }
        return {
            "approval": {"decision": d.get("decision", "reject"), "clinician": who},
            "trace": ["clinician_approval"],
        }

    # ------------------------------------------------------------------ submit
    def submit(state: PAState) -> dict[str, Any]:
        ap = state["approval"]
        if ap["decision"] != "approve":
            return {
                "submission": None,
                "trace": ["submit"],
                "answer": f"Draft {state['draft_id']} not submitted ({ap['decision']}).",
            }
        try:
            sub = gw["submitter"].call(
                "pa_portal",
                "submit",
                draft_id=state["draft_id"],
                signed_by=ap["clinician"],
                idempotency_key=f"submit:{state['draft_id']}",
                dry_run=False,
            )
        except SystemOfRecordUnavailableError as exc:
            return {
                "submission": None,
                "trace": ["submit"],
                "answer": f"Draft {state['draft_id']} is signed but the portal is down; "
                "it will be submitted on retry.",
                "exits": [exit_record("submit", "degrade", str(exc))],
            }
        return {
            "submission": sub,
            "trace": ["submit"],
            "answer": f"Submitted {sub['reference']} (signed by {ap['clinician']}).",
        }

    # ------------------------------------------------------------------ member channel
    def member_reply(state: PAState) -> dict[str, Any]:
        r, exits = state["request"], []
        if ASKS_ADVICE.search(r.get("question", "")):
            return {
                "answer": REFUSAL,
                "trace": ["member_reply"],
                "exits": [
                    exit_record(
                        "member_reply", "escalate", "medical advice requested: refused, nurse line"
                    )
                ],
            }
        try:
            reqs = gw["reader"].call("pa_portal", "get_status", member_id=r["member_id"])
        except SystemOfRecordUnavailableError:
            return {
                "answer": "We can't look up your requests right now; please try again "
                "later or call member services.",
                "trace": ["member_reply"],
                "exits": [exit_record("member_reply", "degrade", "portal down")],
            }
        facts = {"requests": reqs, "question": r.get("question", "")}
        try:
            text = str(
                model.invoke(
                    [
                        SystemMessage(
                            "TASK: MEMBER\nGive request status only. Never give medical advice."
                        ),
                        HumanMessage(json.dumps(facts)),
                    ]
                ).content
            )
        except ModelUnavailableError:
            text = member_template(facts)
            exits.append(exit_record("member_reply", "degrade", "model down: template"))
        if ADVICE.search(text):  # hard guardrail: advice never reaches a member
            text = member_template(facts) + " " + REFUSAL
            exits.append(exit_record("member_reply", "degrade", "guardrail: advice blocked"))
        return {"answer": text, "exits": exits, "trace": ["member_reply"]}

    g = StateGraph(PAState)
    g.add_node("intake", intake, destinations=("eligibility", "policy", "member_reply"))
    g.add_node("eligibility", eligibility)
    g.add_node("policy", policy)
    g.add_node("criteria", criteria, destinations=("coverage_language", END))
    g.add_node("coverage_language", coverage_language_node)
    g.add_node("draft_packet", draft_packet, destinations=("clinician_approval", END))
    g.add_node("clinician_approval", clinician_approval)
    g.add_node("submit", submit)
    g.add_node("member_reply", member_reply)
    g.add_edge(START, "intake")
    g.add_edge(["eligibility", "policy"], "criteria")
    g.add_edge("coverage_language", "draft_packet")
    g.add_edge("clinician_approval", "submit")
    g.add_edge("submit", END)
    g.add_edge("member_reply", END)
    return g.compile(checkpointer=checkpointer or MemorySaver(), name="prior_auth")
