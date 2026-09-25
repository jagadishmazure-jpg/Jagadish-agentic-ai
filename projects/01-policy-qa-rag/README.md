# 01 · Policy Q&A (RAG)

> **Status:** planned (not built yet)

Employees ask HR, IT and expense-policy questions and need answers they can trust. The agent answers only from indexed policy documents, cites the exact section, and says "I don't know" instead of guessing when retrieval is weak.

**Graph pattern it teaches:** Retrieve → grade → generate with a corrective loop (self-RAG / CRAG): conditional edges that re-retrieve or refuse when evidence is weak.

**Planned components:**

- Document loader + chunker for markdown/PDF policies with section metadata
- In-memory vector store (offline embeddings stub; Azure AI Search / pgvector optional)
- Retrieval grader and hallucination/groundedness checker nodes
- Query rewriter for a single corrective re-retrieval loop
- Structured answer: {answer, citations[], confidence, refused}
- Golden-set eval (faithfulness, citation accuracy) in pytest

Like every project in this repo, it will run offline with the shared mock LLM (`shared.llm.get_llm`) and optionally against Azure OpenAI / OpenAI via env vars.
