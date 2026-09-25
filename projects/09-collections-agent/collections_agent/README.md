# `collections_agent/`: governed collections workflow

The importable package for project 09. For each past-due account, a deterministic policy gate
checks hardship, cease-and-desist, disputes, contact hours and frequency caps before anything
else happens. Only allowed accounts get a model-proposed payment plan, which is clamped to plan
policy, guarded for message content and then held for a human reviewer (separation of duties).
Each node calls tools through its own least-privilege identity, and every decision lands in a
SHA-256 hash-chained audit log with PII masked.

| File | What it does |
|---|---|
| [`__init__.py`](__init__.py) | Package docstring. |
| [`audit.py`](audit.py) | Tamper-evident `AuditLog` (hash chain, verification) with `mask` / `mask_text` PII masking on write. |
| [`demo.py`](demo.py) | CLI behind `run.py`; `--reject` makes the reviewer decline, `--mermaid PATH`. |
| [`eval_suite.py`](eval_suite.py) | `run`, `run_case`, `chaos_scenario` and `CHAOS_CHECKS`. |
| [`graph.py`](graph.py) | `build_graph()` and `CollectionsState`. Nodes: `load_account`, `policy_gate`, `hardship_referral`, `no_contact`, `defer`, `propose_plan`, `reviewer_approval` (interrupt), `execute_plan`, `send_outreach`, `rejected`, `finalize`. |
| [`llm.py`](llm.py) | Plan-proposal and message-drafting prompts with deterministic mocks. |
| [`policy.py`](policy.py) | Deterministic rules loosely modelled on FDCPA / Reg F style limits (illustrative, not legal advice): `contact_decision`, `next_allowed_time`, `check_plan` (clamps a proposed plan), `check_message`, `safe_template`. |
| [`registry.py`](registry.py) | Scoped tool registry: `ToolSpec`, `ToolRegistry`, `ScopedClient` bound to one identity; calls outside that identity's scopes raise `PermissionDenied` and are audited. With MCP enabled, permitted calls go through the identity's gateway. |
| [`sor.py`](sor.py) | Receivables CRM and payments ledger behind MCP with one `ToolGateway` per identity (allowlist derived from its scopes); `Account` payload contract, `write_args` (committed writes with idempotency keys). |
| [`systems.py`](systems.py) | Mock systems of record: accounts, contact history, payment plans, messaging. `seed_systems()`. |

## Graph

```
load_account (collections-reader) -> policy_gate
    hardship -> hardship_referral | no_contact -> no_contact | defer -> defer
    allowed  -> propose_plan (plan-proposer) -> reviewer_approval (interrupt)
                  approve -> execute_plan (plan-writer) -> send_outreach (outreach-sender,
                             contact rules re-checked at send time)
                  reject  -> rejected
every branch -> finalize (verify the audit hash chain)
```

## Failure handling

- Model down: policy-default plan and a safe template, still human-reviewed.
- CRM down at load: deferred to the next run (never contact on stale data).
- Payments down after approval: plan write queued for replay and no outreach sent.
- Registry scopes and gateway allowlists both enforce least privilege (defence in depth).

## Run

```bash
python projects/09-collections-agent/run.py                    # demo (offline, mock LLM)
python projects/09-collections-agent/run.py --mermaid projects/09-collections-agent/graph.mmd  # also refresh the Mermaid diagram
pytest projects/09-collections-agent                           # tests
python -m evals --project 09                # golden-set eval
CHAOS_FAULTS=model python projects/09-collections-agent/run.py   # demo with every model deployment down
```

See the [project README](../README.md) for the business problem and design trade-offs, and [`DOCTRINE.md`](../DOCTRINE.md) for the five-exit table per node.
