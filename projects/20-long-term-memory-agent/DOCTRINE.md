# Doctrine card: Long-term memory banking assistant - remembers the customer, forgets on request

<!-- GENERATED from doctrine.yaml + evals/scores.json by `python -m shared.doctrine render`. Do not edit by hand. -->

> A retail-banking assistant that remembers a customer across sessions without becoming a liability. Short-term state is the thread checkpoint. Long-term memory lives in the LangGraph Store in three kinds, namespaced per authenticated user: semantic (profile facts), episodic (summaries of past conversations) and procedural (presentation preferences). A write policy decides what may be saved (consent, poisoning and injection checks, a preference allowlist, no credentials, identifier redaction, a confidence floor, conflict rules). Retrieval ranks by relevance, recency and confidence, drops expired items and quarantines anything instruction-like. Answers cite memories and a guard strips citations to memories that don't exist. Customers can make it forget one fact or everything, including every checkpointed thread, and an audit tombstone records the erasure without keeping the erased data.

| Field | Value |
|---|---|
| Owner | Jagadish Meduri |
| Industry | Banking (retail digital assistant) |
| Maturity | **Level 3**: memory reads and writes are autonomous inside a strict write policy; poisoning attempts escalate to review, erasure is immediate and audited, and every answer is limited to cited memories |
| Next rung | swap the in-memory Store and hashing embedder for PostgresStore with pgvector and native TTL sweeps, and add a customer-facing "what you remember about me" page with per-item delete |
| Graph | `memory_agent.graph:build_graph` |

## Plane dependencies

| Plane | Dependency |
|---|---|
| Experience | mobile / web banking chat; "forget ..." and consent commands in the conversation; an erasure receipt |
| Agent | LangGraph graph (intake -> recall -> respond -> remember | forget | consent) with a checkpointer for thread state and a Store for long-term memory |
| Knowledge | per-user long-term memory in the LangGraph Store (vector index for similarity + recency and confidence scoring, TTL per kind) |
| Data | LangGraph Store (memories, consent, thread registry, audit tombstones) and the checkpointer (thread state); no core-banking writes |

## Systems of record and semantic models

| System | Kind | Contract | Access |
|---|---|---|---|
| Long-term memory store (LangGraph BaseStore) | document_store | `put/get/search/delete on namespaces (memory, user_id, kind) | (consent, user_id) | (threads, user_id) | (audit, user_id)` | read_write |
| Thread checkpointer | document_store | `checkpoint per thread_id; delete_thread on erasure` | read_write |

## Knowledge: retrieval corpora and ACL

| Corpus | Owner | ACL | Temporal validity | Refresh SLA | Sensitivity |
|---|---|---|---|---|---|
| customer-memory | Jagadish Meduri (digital banking) | per authenticated user: namespace (memory, <user_id>, *) from the run config only | episodes expire after 90 days, profile facts after 365 days, preferences on change; recency half-life per kind | written in the turn it is learned; erased in the turn it is requested | confidential (customer PII, redacted identifiers, no credentials) |

The memory corpus is written by the agent itself, so the write policy is the ACL on what enters it; reads never cross user namespaces.

## MCP / A2A contracts


No MCP or A2A tools. The Store and checkpointer are LangGraph interfaces (InMemoryStore / InMemorySaver offline; PostgresStore / PostgresSaver in production). The assistant never moves money, so no system-of-record writes exist.

## Stop conditions

- no memory consent -> no long-term writes or reads (thread state only); withdrawing consent erases saved memories
- instruction-like or policy-override content is never stored and is flagged for review
- preferences may only set name, contact channel, language or answer style
- credentials (PIN, password, full card or SSN) are never stored; other identifiers are redacted
- candidates with confidence < 0.6 are not stored; inferred values never override user-stated ones
- replies may only cite memories that were retrieved for this user; any other citation is removed

## Failure playbook (five exits per node)

| Node | Success | Retry (backoff) | Compensate | Degrade | Escalate |
|---|---|---|---|---|---|
| `intake` | command parsed (chat / forget / forget everything / consent) and thread registered for erasure | n/a (deterministic) | n/a | n/a | n/a |
| `recall` | preferences + top memories by relevance x recency x confidence, expired items dropped | n/a (in-process store; production store client retries with backoff) | n/a (read only) | memory store down -> answer without memory, say nothing is on file | instruction-like stored record quarantined and flagged |
| `respond` | answer that cites only retrieved memories | fallback model deployment via breaker | n/a | model down -> holding reply with no memory claims; unsupported citations stripped | n/a |
| `remember` | candidates saved / updated / skipped by the write policy | fallback model deployment for extraction | n/a (writes are per-key upserts; history keeps the prior value) | extractor or store down -> nothing saved this turn, never a guessed memory | poisoning / injection attempt rejected and flagged in the audit namespace |
| `forget` | key or all memories erased (store + other threads), tombstone written | n/a | n/a (erasure is intentional and irreversible) | n/a | store down -> erasure request queued for an operator, customer told |
| `consent` | consent recorded; withdrawal erases saved memories | n/a | n/a | n/a | store down -> change not applied, customer asked to retry |

## Chaos scenarios (asserted in `tests/test_chaos.py`)

| Fault | Node | Expected exit | Invariant |
|---|---|---|---|
| `model` | `respond` | **degrade** | holding reply with no memory citations; stored memories unchanged |
| `retrieval` | `recall` | **degrade** | memory store down -> answer without memory and nothing recalled |
| `jailbreak` | `remember` | **escalate** | jailbreak text is never stored as a memory and the attempt is flagged |

## Evaluation

Golden set: `evals/golden.jsonl` · suite: `memory_agent.eval_suite:run_case` · run `python -m evals --project 20`

| Metric | Threshold | Current |
|---|---|---|
| task_success | >=0.9 | 1.00 |
| groundedness | >=1.0 | 1.00 |
| policy_violation_rate | <=0 | 0.00 |
| tool_error_rate | - | 0.00 |
| cost_per_task | <=0.002 | $0.00009 |

Cases: 18 · gate: **PASS**

## KPIs

| KPI | Target | How measured |
|---|---|---|
| Correct recall | >= 95% of remembered facts recalled correctly in later sessions | golden multi-session set + monthly sample of flagged conversations |
| Hallucinated memories | 0 | cited memory ids not present in the user's Store (guard exits + eval groundedness) |
| Cross-user leakage | 0 | isolation tests + reply scans for other users' stored values |
| Erasure completion | 100% within the request (store + threads) | tombstones vs remaining items per erased user |

## ROI sketch

Customers stop repeating who they are and how they want to be contacted, conversations pick up where they left off and handle time drops for the human agents who inherit the thread. The same controls reduce risk: consent-gated writes, no credentials in memory, poisoning rejected, and provable erasure keep the memory from becoming a privacy or fraud liability. Costs are one extra extraction call per turn, the Store and embedding infrastructure, and review time for flagged poisoning attempts.
