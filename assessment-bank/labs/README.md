# `labs`

Pytest files the grader copies next to a submitted `solution.py`. The portfolio test run does not collect them: the names do not match `test_*.py` or `*_test.py`.

| File | What it does |
|---|---|
| [`foundations_tokens.py`](foundations_tokens.py) | `estimate_tokens`. |
| [`frameworks_route.py`](frameworks_route.py) | `route` a ticket to billing, tech or general. |
| [`llm_json.py`](llm_json.py) | `parse_choice` from a JSON object in prose. |
| [`rag_citations.py`](rag_citations.py) | `sentences_are_cited`. |
| [`agentic_stop.py`](agentic_stop.py) | `should_stop` at a step budget. |
| [`trust_redact.py`](trust_redact.py) | `redact_emails`. |
| [`customization_choice.py`](customization_choice.py) | `choose` prompt or finetune from a labelled-set size. |
| [`production_health.py`](production_health.py) | `health` returns `{"status": "ok"}`. |
