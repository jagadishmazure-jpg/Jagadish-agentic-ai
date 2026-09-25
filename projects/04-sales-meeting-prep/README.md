# 04 · Sales Meeting Prep

> **Status:** planned (not built yet)

Account executives spend an hour before every call gathering context. The agent pulls CRM history, recent news, open opportunities and support tickets in parallel, then produces a one-page brief with talking points and risks.

**Graph pattern it teaches:** Parallel fan-out / fan-in (map-reduce) research branches merged by a synthesizer node.

**Planned components:**

- Parallel research nodes: CRM, news, product usage, support history (mock tools)
- Reducer-based state merge for fan-in
- Synthesizer node producing a structured brief
- Source attribution per claim
- Caching layer to avoid re-fetching within a day
- Markdown/PDF export of the brief

Like every project in this repo, it will run offline with the shared mock LLM (`shared.llm.get_llm`) and optionally against Azure OpenAI / OpenAI via env vars.
