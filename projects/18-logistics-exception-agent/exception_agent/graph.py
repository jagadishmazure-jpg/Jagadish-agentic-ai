"""Logistics exception graph.

intake (TMS shipment via MCP, tenant-scoped) routes by request kind:
* track  -> track: answer only from TMS scan events; on a scan gap refuse to interpolate
* slip   -> [evidence (scan freshness + event confidence) || whatif (A2A capacity agent)] ->
            comms (proactive notice drafted only on high-confidence, current events)
* claim  -> ocr (Document-Intelligence-style fields; low confidence or TMS mismatch -> queue)
            -> claim (carrier claim rules as-of ship date; window check; claim draft)
-> respond
"""

from __future__ import annotations

import json
import operator
import re
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Annotated, Any, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Send

from exception_agent import capacity
from exception_agent.knowledge import builder, principal
from exception_agent.ocr import analyze, low_confidence
from exception_agent.sor import gateways
from exception_agent.systems import LOCATIONS, Systems, seed_systems
from shared.a2a import A2AClient, A2AError, A2AUnavailableError
from shared.context import RetrievalError, looks_like_injection, sanitize
from shared.llm import get_llm
from shared.observability import install
from shared.resilience import ModelUnavailableError, exit_record, with_fallback
from shared.tools import SystemOfRecordUnavailableError

SCAN_GAP_H = 6.0
MIN_EVENT_CONFIDENCE = 0.9
REMOVED = "[removed: suspected injected instruction]"
CITE = re.compile(r"\[(EV-\d{4}-\d+)\]")
SPECULATION = re.compile(
    r"\b(probably|likely|should be (?:near|at)|estimated location|"
    r"due to|because of|weather|strike|by now)\b",
    re.I,
)
STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")


def mentioned_locations(text: str) -> set[str]:
    return {loc for loc in LOCATIONS if loc.split(" ")[0] in text}


def track_template(f: dict[str, Any]) -> str:
    last = f["events"][-1]
    eta = f["shipment"].get("tms_eta") or "not available from the carrier yet"
    return (
        f"Latest carrier scan: {last['code'].replace('_', ' ')} at {last['location']} on "
        f"{last['ts']} [{last['event_id']}]. TMS ETA: {eta}."
    )


def notice_template(f: dict[str, Any]) -> str:
    eta = f["tms_eta"] or "we will confirm a new delivery time as soon as the carrier does"
    return (
        f"Hello {f['customer']}, your shipment {f['shipment_id']} missed its planned "
        f"{f['milestone'].replace('_', ' ')} milestone and will not arrive by "
        f"{f['promised']}. New ETA: {eta}. We are monitoring it and will update you."
    )


def mock_responder(msgs: Sequence[BaseMessage]) -> str:
    s = str(msgs[0].content)
    f = json.loads(str(msgs[-1].content))
    if "TASK: TRACK" in s:
        return track_template(f)
    if "TASK: NOTICE" in s:
        return notice_template(f)
    return ""


def eager_responder(msgs: Sequence[BaseMessage]) -> str:
    """A 'helpful' model that interpolates location and speculates on cause."""
    s = str(msgs[0].content)
    if "TASK: TRACK" in s:
        return "Your freight is probably near Pittsburgh PA by now [EV-1001-3]."
    if "TASK: NOTICE" in s:
        return "Your shipment is late due to weather near Buffalo NY; expect it 2026-09-26T09:00."
    return ""


class ExState(TypedDict, total=False):
    request: dict[str, Any]
    shipment: dict[str, Any]
    events: list[dict[str, Any]]
    gap_h: float
    evidence: dict[str, Any]
    whatif: dict[str, Any] | None
    ocr: dict[str, Any]
    claim: dict[str, Any] | None
    notice: dict[str, Any] | None
    answer: str
    outcome: str
    exits: Annotated[list, operator.add]
    trace: Annotated[list, operator.add]


def build_graph(
    systems: Systems | None = None,
    llm: BaseChatModel | None = None,
    checkpointer: Any = None,
    capacity_client: A2AClient | None = None,
):
    install()
    s = systems or seed_systems()
    gw = gateways(s)
    kb = builder()
    model = with_fallback(llm or get_llm(mock_responder=mock_responder))
    cap = capacity_client or capacity.client()

    def scans(shipment_id: str) -> tuple[list[dict[str, Any]], float, bool]:
        evs = sorted(
            gw["reader"].call("tms", "get_scan_events", shipment_id=shipment_id)["events"],
            key=lambda e: e["ts"],
        )
        poisoned = any(REMOVED in e["remark"] or looks_like_injection(e["remark"]) for e in evs)
        for e in evs:
            e["remark"] = sanitize(e["remark"]).text.replace(REMOVED, "").strip()
        gap = (
            (s.now - datetime.fromisoformat(evs[-1]["ts"])).total_seconds() / 3600
            if evs
            else float("inf")
        )
        return evs, round(gap, 1), poisoned

    def intake(state: ExState) -> Command:
        r = state["request"]
        try:
            sh = gw["reader"].call(
                "tms", "get_shipment", shipment_id=r["shipment_id"], tenant=r["tenant"]
            )
        except KeyError:
            return Command(
                goto="respond",
                update={
                    "outcome": "not_found",
                    "trace": ["intake"],
                    "answer": f"No shipment {r['shipment_id']} found for your account.",
                },
            )
        except SystemOfRecordUnavailableError as exc:
            return Command(
                goto="respond",
                update={
                    "outcome": "tms_unavailable",
                    "trace": ["intake"],
                    "answer": "Shipment data is unavailable right now; I will not guess.",
                    "exits": [exit_record("intake", "degrade", f"TMS down: {exc}")],
                },
            )
        upd: dict[str, Any] = {"shipment": sh, "trace": ["intake"], "exits": []}
        if looks_like_injection(r.get("question", "")):
            upd["exits"] = [exit_record("intake", "degrade", "instruction-like text neutralised")]
        if r["kind"] == "slip":
            st = {**state, **upd}
            return Command(goto=[Send("evidence", st), Send("whatif", st)], update=upd)
        return Command(goto="track" if r["kind"] == "track" else "ocr", update=upd)

    def track(state: ExState) -> dict[str, Any]:
        sh = state["shipment"]
        try:
            evs, gap, poisoned = scans(sh["shipment_id"])
        except SystemOfRecordUnavailableError as exc:
            return {
                "outcome": "tms_unavailable",
                "trace": ["track"],
                "answer": "Tracking events are unavailable right now; I won't guess.",
                "exits": [exit_record("track", "degrade", f"TMS events down: {exc}")],
            }
        exits = (
            [exit_record("track", "degrade", "injected scan remark neutralised")]
            if poisoned
            else []
        )
        f = {"shipment": sh, "events": evs, "now": s.now.isoformat()}
        if not evs:
            return {
                "events": evs,
                "outcome": "no_scans",
                "trace": ["track"],
                "exits": exits,
                "answer": "The carrier has not reported any scans for this shipment yet.",
            }
        if sh["status"] != "delivered" and gap > SCAN_GAP_H:  # never interpolate
            last = evs[-1]
            return {
                "events": evs,
                "gap_h": gap,
                "outcome": "scan_gap",
                "trace": ["track"],
                "answer": (
                    f"The last confirmed scan was {last['code'].replace('_', ' ')} at "
                    f"{last['location']} on {last['ts']} [{last['event_id']}]. There "
                    f"have been no scans for {gap:.0f} hours, so I can't tell you where "
                    "the shipment is now. I've asked the carrier desk to trace it."
                ),
                "exits": [
                    *exits,
                    exit_record(
                        "track",
                        "escalate",
                        f"scan gap {gap:.0f} h: location not interpolated; carrier trace requested",
                    ),
                ],
            }
        try:
            text = str(
                model.invoke(
                    [
                        SystemMessage(
                            "TASK: TRACK\nAnswer only from these TMS scan events; cite "
                            "[EV-..]; never estimate a location."
                        ),
                        HumanMessage(json.dumps(f)),
                    ]
                ).content
            )
        except ModelUnavailableError:
            text = track_template(f)
            exits.append(exit_record("track", "degrade", "model down: template"))
        ids = {e["event_id"] for e in evs}
        locs = {e["location"] for e in evs}
        if (
            set(CITE.findall(text)) - ids
            or mentioned_locations(text) - locs
            or SPECULATION.search(text)
            or not CITE.search(text)
        ):
            text = track_template(f)
            exits.append(
                exit_record("track", "degrade", "grounding guard: answer not from TMS events")
            )
        return {
            "events": evs,
            "gap_h": gap,
            "answer": text,
            "outcome": "tracked",
            "trace": ["track"],
            "exits": exits,
        }

    def delay_hours(state: ExState) -> float:
        ev = state["request"]["event"]
        planned = datetime.fromisoformat(ev["planned_at"])
        actual = datetime.fromisoformat(ev["actual_at"]) if ev.get("actual_at") else s.now
        return round(max(0.0, (actual - planned).total_seconds() / 3600), 1)

    def evidence(state: ExState) -> dict[str, Any]:
        ev = state["request"]["event"]
        try:
            evs, gap, _ = scans(state["shipment"]["shipment_id"])
        except SystemOfRecordUnavailableError as exc:
            return {
                "evidence": {"confidence_ok": False, "reason": "TMS events unavailable"},
                "trace": ["evidence"],
                "exits": [exit_record("evidence", "degrade", f"TMS events down: {exc}")],
            }
        reasons = []
        if ev["source"] == "inferred" or ev["confidence"] < MIN_EVENT_CONFIDENCE:
            reasons.append(f"event confidence {ev['confidence']} ({ev['source']})")
        if gap > SCAN_GAP_H:
            reasons.append(f"no scans for {gap:.0f} h")
        return {
            "events": evs,
            "gap_h": gap,
            "trace": ["evidence"],
            "evidence": {
                "confidence_ok": not reasons,
                "reason": "; ".join(reasons) or "confirmed",
                "delay_h": delay_hours(state),
            },
        }

    def whatif(state: ExState) -> dict[str, Any]:
        sh = state["shipment"]
        try:
            t = cap.send(
                "network_whatif",
                {
                    "shipment_id": sh["shipment_id"],
                    "lane": sh["lane"],
                    "delay_hours": delay_hours(state),
                },
                tenant=state["request"]["tenant"],
            )
            return {"whatif": t.artifacts[0].data(), "trace": ["whatif"]}
        except A2AUnavailableError as exc:
            return {
                "whatif": None,
                "trace": ["whatif"],
                "exits": [exit_record("whatif", "degrade", f"capacity agent down: {exc}")],
            }
        except A2AError as exc:
            return {
                "whatif": None,
                "trace": ["whatif"],
                "exits": [exit_record("whatif", "escalate", f"capacity agent refused: {exc}")],
            }

    def comms(state: ExState) -> dict[str, Any]:
        ev, sh, e = state["request"]["event"], state["shipment"], state["evidence"]
        if not e["confidence_ok"]:
            return {
                "notice": None,
                "outcome": "ops_review",
                "trace": ["comms"],
                "answer": f"No customer notice drafted ({e['reason']}); routed to the "
                "exception desk to confirm with the carrier.",
            }
        f = {
            "customer": sh["customer"],
            "shipment_id": sh["shipment_id"],
            "milestone": ev["milestone"],
            "promised": sh["promised"],
            "tms_eta": sh["tms_eta"],
        }
        exits = []
        try:
            kb.build(
                "proactive delay notice policy confirmed event",
                principal(sh["tenant"]),
                as_of=s.now.date(),
                k=2,
                kinds=["policy"],
            )
            text = str(
                model.invoke(
                    [
                        SystemMessage(
                            "TASK: NOTICE\nDraft a proactive delay notice. No cause, no "
                            "location, ETA only from the TMS."
                        ),
                        HumanMessage(json.dumps(f)),
                    ]
                ).content
            )
        except RetrievalError:
            return {
                "notice": None,
                "outcome": "ops_review",
                "trace": ["comms"],
                "answer": "Communication policy unavailable; no notice drafted.",
                "exits": [exit_record("comms", "degrade", "policy retrieval down")],
            }
        except ModelUnavailableError:
            text = notice_template(f)
            exits.append(exit_record("comms", "degrade", "model down: template notice"))
        stamps = set(STAMP.findall(text)) - {sh["promised"], sh["tms_eta"]}
        if SPECULATION.search(text) or mentioned_locations(text) or stamps:
            text = notice_template(f)
            exits.append(
                exit_record(
                    "comms", "degrade", "notice guard: speculation, location or ETA not from TMS"
                )
            )
        try:
            ref = gw["comms"].call(
                "comms",
                "draft_notice",
                notice={
                    "shipment_id": sh["shipment_id"],
                    "customer": sh["customer"],
                    "text": text,
                    "cites": [
                        "COMMS-PROACTIVE-2026",
                        *[x["event_id"] for x in state["events"][-1:]],
                    ],
                },
                idempotency_key=f"notice:{sh['shipment_id']}:{ev['milestone']}",
                dry_run=False,
            )
        except SystemOfRecordUnavailableError as exc:
            return {
                "notice": None,
                "outcome": "ops_review",
                "trace": ["comms"],
                "answer": "Comms system unavailable; exception desk will notify.",
                "exits": [*exits, exit_record("comms", "degrade", f"comms down: {exc}")],
            }
        return {
            "notice": {**ref, "text": text},
            "outcome": "notice_drafted",
            "trace": ["comms"],
            "exits": exits,
            "answer": text,
        }

    def ocr(state: ExState) -> Command:
        sh = state["shipment"]
        o = analyze(state["request"]["documents"])
        exits = []
        desc = o["fields"].get("description", {}).get("value", "")
        if looks_like_injection(desc):
            o["fields"]["description"]["value"] = sanitize(desc).text
            exits.append(
                exit_record("ocr", "degrade", "instruction-like text in claim docs neutralised")
            )
        reasons = (
            [f"low OCR confidence: {', '.join(low)}"]
            if (low := low_confidence(o["fields"]))
            else []
        )
        try:
            evs, _, _ = scans(sh["shipment_id"])
            if not any("exception" in e["remark"].lower() for e in evs if e["code"] == "delivered"):
                reasons.append("no POD exception recorded in TMS delivery event")
        except SystemOfRecordUnavailableError:
            reasons.append("TMS delivery event unavailable for cross-check")
        if not reasons:
            return Command(goto="claim", update={"ocr": o, "trace": ["ocr"], "exits": exits})
        q = gw["claims"].call(
            "claims",
            "queue_review",
            item={"shipment_id": sh["shipment_id"], "reasons": reasons, "ocr_model": o["model_id"]},
            idempotency_key=f"review:{sh['shipment_id']}",
            dry_run=False,
        )
        return Command(
            goto="respond",
            update={
                "ocr": o,
                "outcome": "claim_queued",
                "claim": None,
                "trace": ["ocr"],
                "answer": f"Claim packet queued for a claims specialist ({q['queue_ref']}): "
                f"{'; '.join(reasons)}.",
                "exits": [*exits, exit_record("ocr", "escalate", "; ".join(reasons))],
            },
        )

    def claim(state: ExState) -> dict[str, Any]:
        sh, fl = state["shipment"], state["ocr"]["fields"]
        carrier = sh["carrier"]

        def queue(reason: str, exit_: tuple[str, str] | None = None) -> dict[str, Any]:
            q = gw["claims"].call(
                "claims",
                "queue_review",
                item={"shipment_id": sh["shipment_id"], "reasons": [reason]},
                idempotency_key=f"review:{sh['shipment_id']}",
                dry_run=False,
            )
            return {
                "claim": None,
                "outcome": "claim_queued",
                "trace": ["claim"],
                "answer": f"Claim packet queued for review ({q['queue_ref']}): {reason}.",
                "exits": [exit_record("claim", *exit_)] if exit_ else [],
            }

        try:
            b = kb.build(
                f"freight damage claim carrier {carrier} file within days delivery BOL POD",
                principal(sh["tenant"]),
                as_of=date.fromisoformat(sh["ship_date"]),
                k=4,
                kinds=["claim_rules"],
            )
        except RetrievalError as exc:
            return queue("carrier claim rules unavailable", ("degrade", f"retrieval down: {exc}"))
        rule = next((h for h in b.hits if carrier in h.chunk.text), None)
        if rule is None:
            return queue(f"no claim rules for {carrier}", ("escalate", "no carrier rules"))
        doc_id = rule.chunk.doc_id
        days = int(re.search(r"within (\d+) days", rule.chunk.text).group(1))
        delivered = date.fromisoformat(fl["delivery_date"]["value"])
        deadline = delivered + timedelta(days=days)
        if s.now.date() > deadline:
            return queue(
                f"filing window passed ({days} days from delivery, deadline {deadline}) [{doc_id}]",
                ("escalate", "filing window passed"),
            )
        ref = gw["claims"].call(
            "claims",
            "create_claim_draft",
            claim={
                "shipment_id": sh["shipment_id"],
                "carrier": carrier,
                "bol": fl["bol"]["value"],
                "amount": fl["amount"]["value"],
                "pod_exception": fl["pod_exception"]["value"],
                "deadline": deadline.isoformat(),
                "rule": doc_id,
            },
            idempotency_key=f"claim:{sh['shipment_id']}",
            dry_run=False,
        )
        return {
            "claim": {**ref, "rule": doc_id, "deadline": deadline.isoformat()},
            "outcome": "claim_drafted",
            "trace": ["claim"],
            "answer": f"Carrier claim draft {ref['claim_ref']} created for {carrier}; file by "
            f"{deadline} per [{doc_id}].",
        }

    def respond(state: ExState) -> dict[str, Any]:
        ans = state.get("answer", "")
        w = state.get("whatif")
        if state["request"]["kind"] == "slip" and w:
            ok = [o for o in w["options"] if o["capacity_ok"]]
            ans += (
                " Ops what-if: "
                + (
                    "; ".join(
                        f"{o['mode']} via {o['carrier']} (+{o['eta_gain_h']} h, "
                        f"{'recovers' if o['recovers_delay'] else 'partial'})"
                        for o in ok
                    )
                    or "no reroute with capacity"
                )
                + f" (lane load {w['lane_load_pct']}%)."
            )
        return {"answer": ans.strip(), "trace": ["respond"]}

    g = StateGraph(ExState)
    g.add_node("intake", intake, destinations=("track", "evidence", "whatif", "ocr", "respond"))
    g.add_node("track", track)
    g.add_node("evidence", evidence)
    g.add_node("whatif", whatif)
    g.add_node("comms", comms)
    g.add_node("ocr", ocr, destinations=("claim", "respond"))
    g.add_node("claim", claim)
    g.add_node("respond", respond)
    g.add_edge(START, "intake")
    g.add_edge(["evidence", "whatif"], "comms")
    g.add_edge("track", "respond")
    g.add_edge("comms", "respond")
    g.add_edge("claim", "respond")
    g.add_edge("respond", END)
    return g.compile(checkpointer=checkpointer or MemorySaver(), name="exception_agent")
