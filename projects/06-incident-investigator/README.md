# 06 · Incident Investigator

> **Status:** planned (not built yet)

On-call engineers lose time correlating alerts, logs, deploys and metrics during an incident. The agent forms hypotheses, queries observability tools, and produces a timeline and probable root cause with evidence, never taking remediation actions without approval.

**Graph pattern it teaches:** ReAct-style tool-using agent bounded by a step budget, with a planner → executor → reflector loop.

**Planned components:**

- Mock tools: log search, metrics query, deploy history, runbook lookup
- Planner / executor / reflector nodes with a max-iterations guard
- Evidence-linked hypothesis tracking in state
- Read-only by default; remediation gated behind `interrupt()`
- Postmortem draft generator
- Trajectory evaluation (tool-call correctness) in tests

Like every project in this repo, it will run offline with the shared mock LLM (`shared.llm.get_llm`) and optionally against Azure OpenAI / OpenAI via env vars.
