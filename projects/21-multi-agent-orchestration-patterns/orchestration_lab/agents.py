"""The worker agents every pattern shares.

Each worker is ``fn(harness, state, meter, **kw) -> (ws_update, info)`` and runs inside
``Harness.turn`` (metering, tracing, fault plan). Workers are pattern-agnostic: the pattern
decides who runs when, the worker only reads the workspace and adds its contribution.

``peers`` (swarm only) asks the worker's model call to also name the next agent
(``info["handoff"]``); there is no extra model call for routing in a swarm.
"""

from __future__ import annotations

from typing import Any

from orchestration_lab import domain, knowledge, routing
from orchestration_lab.harness import CODE_MS, Harness, Meter, MissingInputError
from orchestration_lab.state import merge_ws
from shared.resilience import exit_record

Update = tuple[dict[str, Any], dict[str, Any]]


def _with_handoff(
    payload: dict[str, Any], ws: dict[str, Any], update: dict[str, Any], peers: list[str] | None
) -> dict[str, Any]:
    if peers:
        payload = {**payload, "peers": peers, "status": routing.status(merge_ws(ws, update))}
    return payload


def _info(resp: dict[str, Any] | None, peers: list[str] | None, ws_after: dict[str, Any], **kw):
    info: dict[str, Any] = dict(kw)
    if peers:
        proposed = (resp or {}).get("handoff_to")
        if proposed is None:  # model down / silent: deterministic next step
            nxt = routing.next_step(routing.status(ws_after))
            proposed = "END" if nxt == "FINISH" else nxt
        info["handoff"] = proposed
    return info


def read_file(h: Harness, gw: str, loan_id: str, m: Meter) -> tuple[dict[str, Any], int]:
    """Loan file + appraisal + credit summary through the agent's scoped MCP gateway."""
    lf = h.tool(gw, "loan_system", "get_loan_file", m, loan_id=loan_id)
    injections = h.gw[gw].last("loan_system.get_loan_file").injections
    ap = h.tool(gw, "loan_system", "get_appraisal", m, loan_id=loan_id)
    cr = h.tool(gw, "credit_bureau", "get_credit_summary", m, loan_id=loan_id)
    facts = {**{k: lf[k] for k in lf if k != "loan_id"}, "value": ap["value"], "fico": cr["fico"]}
    return facts, injections


def researcher(h: Harness, state: dict[str, Any], m: Meter, peers=None, task="facts") -> Update:
    ws, loan_id = state.get("ws", {}), state["case"]["loan_id"]
    if task == "analysis":  # secondary capability: the ratio calculator (magentic / blackboard)
        return _analysis(h, state, m, peers, by="researcher")
    facts, injections = read_file(h, "researcher", loan_id, m)
    update = {"facts": facts}
    payload = _with_handoff({"loan_file": {"loan_id": loan_id, **facts}}, ws, update, peers)
    resp = h.ask("researcher", payload, m)
    exits = (
        [exit_record(h.pattern, "degrade", "injected text in loan file neutralised by gateway")]
        if injections
        else []
    )
    return update, _info(resp, peers, merge_ws(ws, update), exits=exits, note="facts gathered")


def _analysis(h: Harness, state: dict[str, Any], m: Meter, peers, by: str) -> Update:
    ws = state.get("ws", {})
    facts = ws.get("facts")
    fetched = False
    if not facts:  # concurrent pattern: the analyst reads the file itself (duplicate reads)
        facts, _ = read_file(h, "analyst", state["case"]["loan_id"], m)
        fetched = True
    r = domain.ratios(facts)
    comp = domain.RULES["CP-COMP-2026"]
    candidates = domain.compensating_factors(facts, r, comp)
    payload = {"ratios": r, "candidate_factors": candidates}
    analysis = {"ratios": r, "factors": candidates, "by": by, "self_fetched": fetched}
    update: dict[str, Any] = {"analysis": analysis}
    resp = h.ask("analyst", _with_handoff(payload, ws, update, peers), m)
    if resp and isinstance(resp.get("factors"), list):  # model may only narrow, never invent
        analysis["factors"] = [f for f in resp["factors"] if f in candidates]
    return update, _info(resp, peers, merge_ws(ws, update), note=f"ratios by {by}")


def analyst(h: Harness, state: dict[str, Any], m: Meter, peers=None) -> Update:
    return _analysis(h, state, m, peers, by="analyst")


def policy(h: Harness, state: dict[str, Any], m: Meter, peers=None) -> Update:
    ws, case = state.get("ws", {}), state["case"]
    as_of = domain.as_of(case)
    evidence: list[dict[str, str]] = []
    for topic in domain.TOPICS:
        bundle = h.retrieve(knowledge.QUERIES[topic], as_of, m)
        for hit in bundle.hits:
            doc = hit.chunk.doc_id
            if domain.topic_of(doc) == topic and doc not in {e["id"] for e in evidence}:
                evidence.append({"id": doc, "text": hit.chunk.text})
                break
    ids = {e["id"] for e in evidence}
    code_map = {domain.topic_of(i): i for i in ids}
    resp = h.ask("policy", {"evidence": evidence, "as_of": str(as_of)}, m)
    proposed = (resp or {}).get("rules") or {}
    exits = []
    valid = {t: d for t, d in proposed.items() if d in ids and domain.topic_of(d) == t}
    if set(valid) != set(domain.TOPICS):
        if resp is not None:
            exits.append(exit_record(h.pattern, "degrade", "policy mapping invalid; code mapping"))
        valid = code_map
    missing = [t for t in domain.TOPICS if t not in valid]
    if missing:
        raise MissingInputError(f"no policy evidence for {missing}")
    update = {"rules": valid, "sources": sorted(ids)}
    info = _info(resp, peers, merge_ws(ws, update), exits=exits, note=f"as of {as_of}")
    if peers:  # policy's model call above had no status; decide the handoff deterministically
        nxt = routing.next_step(routing.status(merge_ws(ws, update)))
        info["handoff"] = "END" if nxt == "FINISH" else nxt
    return update, info


def drafter(h: Harness, state: dict[str, Any], m: Meter, peers=None) -> Update:
    ws, case = state.get("ws", {}), state["case"]
    missing = [k for k in routing.PREREQS["drafter"] if not ws.get(k)]
    if missing:
        raise MissingInputError(f"drafter missing {missing}")
    prev = ws.get("draft")
    revision = (prev["revision"] + 1) if prev else 1
    feedback = list(ws["review"]["issues"]) if ws.get("review") else []
    payload = {
        "loan_id": case["loan_id"],
        "facts": ws["facts"],
        "ratios": ws["analysis"]["ratios"],
        "rules": ws["rules"],
        "feedback": feedback,
    }
    placeholder = {"draft": {"revision": revision}}
    resp = h.ask("drafter", _with_handoff(payload, ws, placeholder, peers), m)
    if not resp or resp.get("decision") not in domain.DECISIONS or not resp.get("memo"):
        d = domain.decide(ws["facts"], ws["rules"]).as_dict()  # deterministic memo
        resp = {**(resp or {}), **d}
        resp["memo"] = domain.render_memo(case["loan_id"], ws["facts"], d, ws["rules"])
    draft = {
        "decision": resp["decision"],
        "conditions": list(resp.get("conditions") or []),
        "citations": list(resp.get("citations") or []),
        "memo": resp["memo"],
        "revision": revision,
    }
    update = {"draft": draft}
    return update, _info(resp, peers, merge_ws(ws, update), note=f"draft r{revision}")


def reviewer(h: Harness, state: dict[str, Any], m: Meter, peers=None) -> Update:
    """Deterministic critic: recomputes the decision from facts + rules and checks the draft
    (decision, every condition, citations, numbers). No model call."""
    ws = state.get("ws", {})
    draft = ws.get("draft")
    if not draft:
        raise MissingInputError("reviewer has no draft")
    m.ms += CODE_MS
    expected = domain.decide(ws["facts"], ws["rules"])
    issues: list[str] = []
    if draft["decision"] != expected.decision:
        issues.append(f"decision should be {expected.decision}")
    for c in expected.conditions:
        if c not in draft["conditions"]:
            issues.append(f"missing condition: {c}")
    for c in draft["conditions"]:
        if c not in expected.conditions:
            issues.append(f"unsupported condition: {c}")
    cited = set(domain.CITE.findall(draft["memo"])) | set(draft["citations"])
    for c in expected.citations:
        if c not in cited:
            issues.append(f"missing citation: {c}")
    if bad := sorted(c for c in cited if c not in ws.get("sources", [])):
        issues.append(f"citations not in retrieved evidence: {bad}")
    if not domain.numbers_match(draft["memo"], ws["facts"]):
        issues.append("memo numbers do not match the computed ratios")
    if h.faults.loop:
        issues = ["memo lacks a borrower-level narrative"]  # never satisfied, same every time
    review = {"passed": not issues, "issues": issues, "revision": draft["revision"]}
    update = {"review": review}
    info: dict[str, Any] = {"note": "PASS" if not issues else f"FAIL {issues}"}
    if peers:
        info["handoff"] = "END" if not issues else "drafter"
    return update, info


WORKERS = {
    "researcher": researcher,
    "analyst": analyst,
    "policy": policy,
    "drafter": drafter,
    "reviewer": reviewer,
}
