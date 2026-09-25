# 10 · Supply-Chain Multi-Agent

> **Status:** planned (not built yet)

When a supplier delay or demand spike hits, planners must coordinate inventory, procurement and logistics decisions. A supervisor agent delegates to specialist agents (inventory, sourcing, logistics), reconciles their proposals and presents a mitigation plan for approval.

**Graph pattern it teaches:** Multi-agent supervisor / hierarchical teams with handoffs (Command(goto=...)) and shared vs private state.

**Planned components:**

- Supervisor node routing with `Command(goto=...)` handoffs
- Specialist agents: inventory analyst, sourcing, logistics (each a subgraph)
- Mock ERP / WMS / carrier-rate tools
- Scenario simulator for disruptions
- Plan approval via `interrupt()` before POs are placed
- Tracing and cost/latency budget per agent

Like every project in this repo, it will run offline with the shared mock LLM (`shared.llm.get_llm`) and optionally against Azure OpenAI / OpenAI via env vars.
