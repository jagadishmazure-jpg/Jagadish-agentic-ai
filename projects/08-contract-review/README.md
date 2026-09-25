# 08 · Contract Review

> **Status:** planned (not built yet)

Legal and procurement review vendor contracts against a playbook (liability caps, indemnity, termination, data protection). The agent extracts clauses, compares them to the playbook, scores risk and proposes redlines, leaving final decisions to a lawyer.

**Graph pattern it teaches:** Checklist-driven extraction and evaluation with a critic/reviser loop and clause-level citations.

**Planned components:**

- Clause extraction into typed schemas
- Playbook rules engine with fallback positions
- Risk scorer + critic/reviser loop for proposed redlines
- Clause-level citations back to the source text
- Lawyer approval via `interrupt()`
- Redline summary export

Like every project in this repo, it will run offline with the shared mock LLM (`shared.llm.get_llm`) and optionally against Azure OpenAI / OpenAI via env vars.
