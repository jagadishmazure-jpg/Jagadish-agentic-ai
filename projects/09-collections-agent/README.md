# 09 · Collections Agent

> **Status:** planned (not built yet)

Finance teams chase overdue invoices with a sequence of reminders, payment-plan offers and escalations. The agent personalises outreach, negotiates within approved limits, records promises-to-pay, and enforces contact-frequency and tone rules.

**Graph pattern it teaches:** Long-running, multi-turn stateful workflow with persistent checkpoints (Postgres/SQLite saver), scheduled re-entry and compliance guardrails.

**Planned components:**

- Dunning state machine persisted across days via a durable checkpointer
- Negotiation node bounded by policy limits (discount, instalments)
- Compliance guardrails (contact windows, frequency caps, prohibited language)
- Mock billing / payment-link API with idempotency
- Human handoff for disputes and hardship cases
- Simulated customer personas for testing

Like every project in this repo, it will run offline with the shared mock LLM (`shared.llm.get_llm`) and optionally against Azure OpenAI / OpenAI via env vars.
