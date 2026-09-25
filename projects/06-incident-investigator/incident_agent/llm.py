"""Investigator system prompt and a deterministic ReAct policy used as the offline mock."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

SYSTEM = """You are an SRE incident investigator. Investigate the alert with your tools:
check metrics and recent deploys, read error logs, and consult the runbook for the symptom.
Only propose a rollback when the runbook allows it and a deploy correlates with the onset.
Finish with ONLY a JSON object:
{"root_cause": str, "summary": str, "confidence": 0-1, "evidence": ["EV-..."],
 "timeline": [str], "mitigation": str}
Every claim must be supported by evidence ids from tool results ([EV-...])."""


def _calls(*calls: tuple[str, dict]) -> AIMessage:
    return AIMessage(
        "", tool_calls=[{"name": n, "args": a, "id": f"c{i}_{n}"} for i, (n, a) in enumerate(calls)]
    )


def mock_investigator(messages: Sequence[BaseMessage]) -> AIMessage:
    alert = json.loads(str(next(m for m in messages if isinstance(m, HumanMessage)).content))
    svc = alert["service"]
    tools = {m.name: m for m in messages if isinstance(m, ToolMessage)}
    ev = [
        m.artifact["evidence_id"]
        for m in messages
        if isinstance(m, ToolMessage) and isinstance(m.artifact, dict)
    ]
    if not tools:
        return _calls(
            ("get_metrics", {"service": svc, "metric": "error_rate"}),
            ("get_metrics", {"service": svc, "metric": "latency_p99"}),
            ("recent_deploys", {"service": svc}),
        )
    if "query_logs" not in tools:
        return _calls(("query_logs", {"service": svc, "pattern": "ERROR"}))
    logs = str(tools["query_logs"].content).lower()
    if "telemetry unavailable" in logs:
        return _undetermined(svc, ev, "telemetry (logs/metrics/deploys) unavailable")
    symptom = (
        "connection pool exhausted"
        if "pool exhausted" in logs
        else "elasticsearch timeout"
        if "elasticsearch" in logs
        else logs[:60]
    )
    if "runbook_lookup" not in tools:
        return _calls(("runbook_lookup", {"symptom": symptom}))
    runbook = str(tools["runbook_lookup"].content)
    if "runbook search unavailable" in runbook:
        return _undetermined(svc, ev, "runbook search unavailable; no write action taken")
    versions = re.findall(r"(v\d+\.\d+\.\d+) at", str(tools["recent_deploys"].content))
    wants_rollback = "roll back to the previous version" in runbook and len(versions) >= 2
    if wants_rollback and "propose_rollback" not in tools:
        return _calls(
            (
                "propose_rollback",
                {
                    "service": svc,
                    "to_version": versions[1],
                    "reason": f"{symptom} began right after {versions[0]}; runbook allows rollback",
                },
            )
        )
    if wants_rollback:
        outcome = str(tools["propose_rollback"].content).split("] ", 1)[-1]
        report = {
            "root_cause": f"Deploy {versions[0]} raised worker threads 32->128 while the DB "
            "pool stayed at 20, exhausting DB connections",
            "summary": f"{svc} 5xx spike (0.4% -> 18.5%) began 1 min after {versions[0]}.",
            "confidence": 0.85,
            "evidence": ev,
            "timeline": [
                f"14:02 deploy {versions[0]}",
                "14:03 pool exhaustion errors",
                "14:03 error rate 18.5%",
            ],
            "mitigation": outcome,
        }
    else:
        report = {
            "root_cause": "Upstream Elasticsearch cluster es-prod-2 timing out",
            "summary": f"{svc} p99 latency 180ms -> 5200ms from 09:12; no deploy in window.",
            "confidence": 0.75,
            "evidence": ev,
            "timeline": ["09:12 ES timeouts begin", "09:12 circuit breaker half-open"],
            "mitigation": "No rollback (upstream issue). Page search-platform on-call per "
            "RB-SEARCH-02.",
        }
    return AIMessage(json.dumps(report))


def _undetermined(svc: str, ev: list[str], why: str) -> AIMessage:
    return AIMessage(
        json.dumps(
            {
                "root_cause": f"Undetermined: {why}",
                "summary": f"{svc} alert could not be fully investigated: {why}.",
                "confidence": 0.1,
                "evidence": ev,
                "timeline": [],
                "mitigation": "Escalated to on-call with the evidence gathered so far.",
            }
        )
    )
