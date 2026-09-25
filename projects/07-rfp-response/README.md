# 07 · RFP Response Drafter

> **Status:** planned (not built yet)

Pre-sales teams answer long RFP/security questionnaires repeatedly. The agent splits the document into questions, retrieves prior approved answers, drafts responses, flags questions needing SME input, and assembles a reviewable document.

**Graph pattern it teaches:** Plan-and-execute with subgraphs: decompose an RFP into questions, draft each in parallel, then review and assemble.

**Planned components:**

- RFP parser that extracts a question list
- Answer library retriever (prior approved responses)
- Per-question drafting subgraph run via `Send`
- Reviewer node scoring completeness and compliance
- SME escalation queue via `interrupt()`
- DOCX/Markdown assembler

Like every project in this repo, it will run offline with the shared mock LLM (`shared.llm.get_llm`) and optionally against Azure OpenAI / OpenAI via env vars.
