"""Investigation tools. Read tools are free to call; the single write tool
(propose_rollback) pauses the graph with interrupt() until a human approves.

Every tool result carries an evidence id (``EV-<tool>-<hash>``) that the final report
must cite, so claims are traceable to observations.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from langchain_core.tools import BaseTool, tool
from langgraph.types import interrupt

from incident_agent.systems import DEPLOYS, LOGS, METRICS, RUNBOOKS, Systems

TOOL_COST = {  # abstract cost units (think: $ / quota of the backing API)
    "query_logs": 3,
    "get_metrics": 2,
    "recent_deploys": 1,
    "runbook_lookup": 1,
    "propose_rollback": 5,
}


def evidence_id(tool_name: str, args: dict[str, Any]) -> str:
    h = hashlib.sha1(json.dumps(args, sort_keys=True).encode()).hexdigest()[:6]
    return f"EV-{tool_name.split('_')[-1]}-{h}"


def make_tools(systems: Systems) -> list[BaseTool]:
    def observed(name: str, args: dict[str, Any], text: str) -> tuple[str, dict]:
        systems.tool_calls.append(name)
        ev = evidence_id(name, args)
        return f"[{ev}] {text}", {"evidence_id": ev, "tool": name, "args": args}

    @tool(response_format="content_and_artifact")
    def query_logs(service: str, pattern: str = "ERROR", minutes: int = 60) -> tuple[str, dict]:
        """Search recent logs of a service for lines matching a level/pattern."""
        lines = [
            f"{t} {lvl} {msg}"
            for t, lvl, msg in LOGS.get(service, [])
            if pattern.upper() in lvl or pattern.lower() in msg.lower()
        ]
        return observed(
            "query_logs",
            {"service": service, "pattern": pattern, "minutes": minutes},
            "\n".join(lines) or "no matches",
        )

    @tool(response_format="content_and_artifact")
    def get_metrics(service: str, metric: str, minutes: int = 60) -> tuple[str, dict]:
        """Get a metric (error_rate, latency_p99) for a service: baseline vs current."""
        m = METRICS.get((service, metric))
        text = (
            (
                f"{service} {metric}: baseline {m['baseline']}{m['unit']} -> current "
                f"{m['current']}{m['unit']} (changed at {m['change_at']})"
            )
            if m
            else "no data"
        )
        return observed(
            "get_metrics", {"service": service, "metric": metric, "minutes": minutes}, text
        )

    @tool(response_format="content_and_artifact")
    def recent_deploys(service: str, hours: int = 24) -> tuple[str, dict]:
        """List deployments of a service in the last N hours (newest first)."""
        d = DEPLOYS.get(service, [])
        text = "; ".join(f"{x['version']} at {x['at']} by {x['by']}: {x['change']}" for x in d)
        return observed(
            "recent_deploys", {"service": service, "hours": hours}, text or "no deploys in window"
        )

    @tool(response_format="content_and_artifact")
    def runbook_lookup(symptom: str) -> tuple[str, dict]:
        """Find the runbook entry for a symptom (e.g. 'connection pool exhausted')."""
        hit = next((v for k, v in RUNBOOKS.items() if k in symptom.lower()), "no runbook found")
        return observed("runbook_lookup", {"symptom": symptom}, hit)

    @tool(response_format="content_and_artifact")
    def propose_rollback(service: str, to_version: str, reason: str) -> tuple[str, dict]:
        """WRITE ACTION: propose rolling a service back. Requires human approval."""
        # Nothing happens before this line: on resume the tool re-runs from the top.
        decision = interrupt(
            {"action": "rollback", "service": service, "to_version": to_version, "reason": reason}
        )
        args = {"service": service, "to_version": to_version}
        if isinstance(decision, dict) and decision.get("approved"):
            r = systems.deploys.rollback(
                service, to_version, idempotency_key=f"rollback:{service}:{to_version}"
            )
            text = (
                f"APPROVED by {decision.get('approver', 'on-call')}: rolled back {service} "
                f"{r['from']} -> {r['to']}"
            )
        else:
            note = decision.get("note", "") if isinstance(decision, dict) else ""
            text = f"REJECTED by on-call: {note or 'no reason given'}. Do not retry the rollback."
        return observed("propose_rollback", args, text)

    return [query_logs, get_metrics, recent_deploys, runbook_lookup, propose_rollback]
