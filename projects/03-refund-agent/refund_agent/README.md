# `refund_agent/`: deterministic refund workflow with human approval

The importable package for project 03. Refund decisions are made by deterministic code over
order data; the model is used only to classify intent and to word the reply. Refunds under
$50 are issued automatically, larger ones pause at a LangGraph `interrupt()` for a human, and
money moves only through an idempotent payment tool, so a crash and replay never refunds twice.

| File | What it does |
|---|---|
| [`__init__.py`](__init__.py) | Package docstring and exports. |
| [`demo.py`](demo.py) | CLI behind `run.py`: a $24.99 auto-approved refund, a $349.00 refund that pauses for approval and is resumed, then a tour of the other branches. `--reject` makes the reviewer decline; `--mermaid PATH`. |
| [`eval_suite.py`](eval_suite.py) | `run`, `run_case`, `chaos_scenario` and `CHAOS_CHECKS`. |
| [`graph.py`](graph.py) | `build_graph(services, llm=...)`: the StateGraph with nodes `classify_intent`, `verify_identity`, `check_order`, `check_refund_policy`, `human_approval` (interrupt), `issue_refund`, `notify_rejection`, `fraud_review`, `deny`, `escalate`, `compose_reply`. Dependencies are injected so tests use fakes. |
| [`knowledge.py`](knowledge.py) | Refund policy as a knowledge product on `shared.context`, chunked by rule with ACL and validity; `policy_citations()` retrieves the text in force on the order's delivery date. |
| [`llm.py`](llm.py) | The two LLM uses: `classify_intent_ex` (degrades to a keyword classifier) and `write_reply_ex` (degrades to a vetted template, and a guard rejects replies that leak internals). `mock_responder`. |
| [`policy.py`](policy.py) | Deterministic rules with citable ids: `check_eligibility`, `fraud_flags`, `cite`. |
| [`services.py`](services.py) | In-memory mock services: `OrdersDB`, `CustomerDirectory`, `RefundAPI` (idempotent by key), `CRM`, append-only `AuditLog`, and `seed_services()` fixture data. |
| [`sor.py`](sor.py) | OMS, CRM and payments behind MCP (`OmsBackend`, `CrmBackend`, `PaymentsBackend`), the `Order` payload contract and `build_gateway()` with the refund agent's identity and allowlist. |
| [`state.py`](state.py) | `RefundRequest`, `FinalReply` and the typed `RefundState`. |

## Graph

```
classify_intent -> verify_identity -> check_order -> check_refund_policy -> decide
    decide: fraud -> fraud_review | ineligible -> deny | < $50 -> issue_refund
            | >= $50 -> human_approval (interrupt) -> issue_refund | notify_rejection
identity failure -> escalate. Every terminal node -> compose_reply -> END.
```

## Design notes

- **HITL**: `human_approval` calls `interrupt()` with the proposed refund; the graph is resumed
  with `Command(resume=...)` on the same thread id (see `demo.py` and the tests).
- **Idempotency**: `RefundAPI` dedupes on the idempotency key, so replay after a crash never
  double-pays (`test_idempotent_replay_after_crash_never_double_refunds`).
- Policy text is retrieved as of the delivery date, so an old order is judged by the rules that
  applied then.

## Run

```bash
python projects/03-refund-agent/run.py                    # demo (offline, mock LLM)
python projects/03-refund-agent/run.py --mermaid projects/03-refund-agent/graph.mmd  # also refresh the Mermaid diagram
pytest projects/03-refund-agent                           # tests
python -m evals --project 03                # golden-set eval
CHAOS_FAULTS=model python projects/03-refund-agent/run.py   # demo with every model deployment down
```

See the [project README](../README.md) for the business problem and design trade-offs, and [`DOCTRINE.md`](../DOCTRINE.md) for the five-exit table per node.
