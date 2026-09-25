"""Investigation tools. Read tools are free to call; the single write tool
(propose_rollback) pauses the graph with interrupt() until a human approves.

Every tool result carries an evidence id (``EV-<tool>-<hash>``) that the final report
must cite, so claims are traceable to observations.

Doctrine wiring: logs / metrics / deploys / rollback are ops MCP tools called through the
ToolGateway (identity, allowlist, schema, sanitised payloads); runbooks come from the shared
context builder. A failed or degraded observation is still returned as a tool message (the
agent sees the gap) and flagged in the artifact so the report can take the declared exit.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from langchain_core.tools import BaseTool, tool
from langgraph.types import interrupt

from incident_agent.knowledge import builder as runbook_builder
from incident_agent.knowledge import lookup
from incident_agent.sor import build_gateway
from incident_agent.systems import Systems
from shared.context import RetrievalError
from shared.tools import SystemOfRecordUnavailableError, ToolGateway

NEUTRALISED = "[removed: suspected injected instruction]"

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


def make_tools(systems: Systems, gw: ToolGateway | None = None, kb: Any = None) -> list[BaseTool]:
    gw = gw or build_gateway(systems)
    kb = kb or runbook_builder()

    def observed(
        name: str, args: dict[str, Any], text: str, degraded: str | None = None
    ) -> tuple[str, dict]:
        systems.tool_calls.append(name)
        ev = evidence_id(name, args)
        art = {"evidence_id": ev, "tool": name, "args": args}
        if degraded:
            art["degraded"] = degraded
        elif NEUTRALISED in text:
            art["injection"] = True
        return f"[{ev}] {text}", art

    def ops(tool: str, **args: Any) -> tuple[Any, str | None]:
        try:
            return gw.call("ops", tool, **args), None
        except SystemOfRecordUnavailableError as exc:
            return None, f"ops.{tool} unavailable: {exc}"

    @tool(response_format="content_and_artifact")
    def query_logs(service: str, pattern: str = "ERROR", minutes: int = 60) -> tuple[str, dict]:
        """Search recent logs of a service for lines matching a level/pattern."""
        args = {"service": service, "pattern": pattern, "minutes": minutes}
        out, err = ops("query_logs", **args)
        if err:
            return observed("query_logs", args, f"TELEMETRY UNAVAILABLE: {err}", err)
        return observed("query_logs", args, "\n".join(out["lines"]) or "no matches")

    @tool(response_format="content_and_artifact")
    def get_metrics(service: str, metric: str, minutes: int = 60) -> tuple[str, dict]:
        """Get a metric (error_rate, latency_p99) for a service: baseline vs current."""
        args = {"service": service, "metric": metric, "minutes": minutes}
        m, err = ops("get_metrics", **args)
        if err:
            return observed("get_metrics", args, f"TELEMETRY UNAVAILABLE: {err}", err)
        text = (
            (
                f"{service} {metric}: baseline {m['baseline']}{m['unit']} -> current "
                f"{m['current']}{m['unit']} (changed at {m['change_at']})"
            )
            if m
            else "no data"
        )
        return observed("get_metrics", args, text)

    @tool(response_format="content_and_artifact")
    def recent_deploys(service: str, hours: int = 24) -> tuple[str, dict]:
        """List deployments of a service in the last N hours (newest first)."""
        args = {"service": service, "hours": hours}
        out, err = ops("recent_deploys", **args)
        if err:
            return observed("recent_deploys", args, f"TELEMETRY UNAVAILABLE: {err}", err)
        d = out["deploys"]
        text = "; ".join(f"{x['version']} at {x['at']} by {x['by']}: {x['change']}" for x in d)
        return observed("recent_deploys", args, text or "no deploys in window")

    @tool(response_format="content_and_artifact")
    def runbook_lookup(symptom: str) -> tuple[str, dict]:
        """Find the runbook entry for a symptom (e.g. 'connection pool exhausted')."""
        try:
            hit = lookup(kb, symptom)
        except RetrievalError as exc:
            msg = f"runbook search unavailable ({exc}); no write actions without a runbook"
            return observed("runbook_lookup", {"symptom": symptom}, msg, msg)
        return observed(
            "runbook_lookup", {"symptom": symptom}, hit[1] if hit else "no runbook found"
        )

    @tool(response_format="content_and_artifact")
    def propose_rollback(service: str, to_version: str, reason: str) -> tuple[str, dict]:
        """WRITE ACTION: propose rolling a service back. Requires human approval."""
        # Nothing happens before this line: on resume the tool re-runs from the top.
        decision = interrupt(
            {"action": "rollback", "service": service, "to_version": to_version, "reason": reason}
        )
        args = {"service": service, "to_version": to_version}
        if isinstance(decision, dict) and decision.get("approved"):
            r, err = ops(
                "rollback_deploy",
                service=service,
                to_version=to_version,
                idempotency_key=f"rollback:{service}:{to_version}",
                dry_run=False,
            )
            if err:
                text = f"APPROVED but NOT EXECUTED: {err}. Hand the rollback to on-call."
                return observed("propose_rollback", args, text, err)
            text = (
                f"APPROVED by {decision.get('approver', 'on-call')}: rolled back {service} "
                f"{r['from']} -> {r['to']}"
            )
        else:
            note = decision.get("note", "") if isinstance(decision, dict) else ""
            text = f"REJECTED by on-call: {note or 'no reason given'}. Do not retry the rollback."
        return observed("propose_rollback", args, text)

    return [query_logs, get_metrics, recent_deploys, runbook_lookup, propose_rollback]
