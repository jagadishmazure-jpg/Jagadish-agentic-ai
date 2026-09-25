# `memory_agent/`: long-term memory with a write policy

The importable package for project 20. A LangGraph banking assistant keeps the current
conversation in a checkpointer and long-term memories in a LangGraph Store, namespaced per
authenticated user and split into semantic (profile), episodic (conversation summaries) and
procedural (presentation preferences) memory. Every candidate memory passes a write policy;
recall ranks by relevance, recency and confidence; answers may only cite retrieved memories;
and customers can make it forget one fact or everything.

| File | What it does |
|---|---|
| [`__init__.py`](__init__.py) | Package docstring only. |
| [`demo.py`](demo.py) | CLI behind `run.py`: two sessions a week apart, an update and a hedged guess, a poisoning attempt, a second customer, forget one fact, forget everything; `--mermaid PATH`. |
| [`eval_suite.py`](eval_suite.py) | `FakeClock`, `replay` (multi-session scripts with elapsed days), `run_case` (contains / not_contains / stored / not_stored, groundedness of citations, violations: cross-user leak, raw identifier or credential stored, poisoned memory stored), `chaos_scenario` and `CHAOS_CHECKS`. |
| [`graph.py`](graph.py) | `build_graph()` and `ChatState`. Nodes: `intake`, `recall`, `respond`, `remember`, `forget`, `consent`. Also the citation guard, `erase_user` (Store, consent, other threads' checkpoints and the live thread) and the `MemoryAgent` facade (`chat`, `forget_user`). |
| [`llm.py`](llm.py) | `EXTRACT_SYSTEM` and `ANSWER_SYSTEM` prompts and the deterministic `mock_responder`: a deliberately naive extractor (JSON candidates) and an answerer that cites `[mem:<key>]` or says it doesn't have that on file. |
| [`memory.py`](memory.py) | `make_store()` (InMemoryStore with a vector index) and `MemoryStore`: `search` (0.6 similarity + 0.25 recency + 0.15 confidence, per-kind half-life, TTL filter), `upsert` with bounded history, `forget` with a content-free tombstone, `sweep`, `consent` and `audit`. Raises `MemoryUnavailableError` under the `retrieval` fault. |
| [`policy.py`](policy.py) | `decide()`: consent → poisoning / injection (flagged) → procedural allowlist → unknown keys → credentials rejected → identifiers redacted → confidence floor → conflict rules. |
| [`schema.py`](schema.py) | Memory kinds, the key catalogue with descriptions, TTLs (profile 365 days, episode 90, preference none), half-lives, `MIN_CONFIDENCE`, `MemoryRecord` and `Candidate`. |

## Graph

```
intake (register thread, parse command)
  chat          -> recall (preferences + top memories; quarantine poisoned) -> respond (cite; guard)
                -> remember (extract -> write policy)
  forget X      -> forget (one key; tombstone)
  forget all    -> forget (store + every thread; tombstone)
  consent on/off-> consent (off erases memories)
```

## Design notes

- The Store namespace is built from the run config's `user_id`, never from message text.
- Tombstones and poisoning flags are keyed with a random suffix, so two events in the same
  millisecond never overwrite each other.
- When a poisoning attempt is refused, the turn's reply is amended in place to tell the
  customer it was not saved.

## Run

```bash
python projects/20-long-term-memory-agent/run.py                    # demo (offline, mock LLM)
python projects/20-long-term-memory-agent/run.py --mermaid projects/20-long-term-memory-agent/graph.mmd  # also refresh the Mermaid diagram
pytest projects/20-long-term-memory-agent                           # tests
python -m evals --project 20                # golden-set eval
CHAOS_FAULTS=retrieval python projects/20-long-term-memory-agent/run.py   # demo with the memory store down
```

See the [project README](../README.md) for the business problem and design trade-offs, and [`DOCTRINE.md`](../DOCTRINE.md) for the five-exit table per node.
