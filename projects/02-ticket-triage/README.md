# 02 · Support Ticket Triage

> **Status:** planned (not built yet)

Inbound support tickets arrive by email/chat in high volume. The agent classifies category, priority and sentiment, extracts entities (product, order id), deduplicates against open tickets, and routes to the right queue, sending low-confidence cases to a human.

**Graph pattern it teaches:** Classification + routing with structured output, confidence thresholds and a fan-out (Send API) for multi-label tickets.

**Planned components:**

- Pydantic schemas for category / priority / entities
- Classifier node with confidence score and human fallback below threshold
- Duplicate detector against a mock ticket store
- Parallel sub-classification via `Send` for multi-issue tickets
- Mock helpdesk API (Zendesk/ServiceNow-like) for queue assignment
- Batch evaluation with a confusion matrix

Like every project in this repo, it will run offline with the shared mock LLM (`shared.llm.get_llm`) and optionally against Azure OpenAI / OpenAI via env vars.
