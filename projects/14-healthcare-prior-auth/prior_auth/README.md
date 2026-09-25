# `prior_auth/`: draft-only prior authorization with clinician sign-off

The importable package for project 14. For provider offices, it redacts PHI from the clinical
note, checks eligibility over MCP in parallel with plan-specific, plan-year medical policy
retrieval, evaluates criteria deterministically, words coverage language in a subgraph behind a
kill switch and saves a **draft** packet. Only a registered clinician's sign-off releases the
submission. A separate member channel answers status questions only and refuses medical advice.

| File | What it does |
|---|---|
| [`__init__.py`](__init__.py) | Empty package marker. |
| [`criteria.py`](criteria.py) | `extract_facts` from the redacted note and `evaluate` criteria per (CPT, plan year); each criterion names its policy document and is evaluated only if that policy was retrieved. |
| [`demo.py`](demo.py) | CLI behind `run.py`: Gold PPO lumbar MRI signed and submitted, the same note with a 2025 date of service (6-week rule not met), a Silver HMO referral rule only its plan can see, the member channel refusing advice, and the coverage-language kill switch; `--mermaid PATH`. |
| [`eval_suite.py`](eval_suite.py) | `run`, `run_case`, `request`, `chaos_scenario`, `CHAOS_CHECKS` and `advice_responder` (a model that would give medical advice, used to prove the guardrail). |
| [`graph.py`](graph.py) | `build_graph()`, `build_coverage_language()` (subgraph behind a kill switch) and `PAState`. Nodes: `intake`, `eligibility`, `policy`, `criteria`, `coverage_language`, `draft_packet`, `clinician_approval` (interrupt), `submit`, `member_reply`. |
| [`knowledge.py`](knowledge.py) | Plan medical policies on `shared.context`: plan-year validity (as of the date of service), `plan:<id>` ACL groups so one plan never sees another's rules, UM medical-director guidance restricted to that role. |
| [`phi.py`](phi.py) | `redact()` (names from the member record, MRN, DOB, plus shared SSN/phone/email/card rules) and `PhiFilter` / `install_log_filter()`, a logging filter that redacts PHI even if raw values are logged. |
| [`sor.py`](sor.py) | MCP servers (eligibility, PA portal) and three identities: `mi-pa-reader`, `mi-pa-drafter` (can only save drafts) and `mi-pa-submitter` (used only after sign-off; the portal also rejects unsigned submissions). |
| [`systems.py`](systems.py) | Mock eligibility, PA portal (drafts, signed submission), clinical notes, clinician registry and runtime kill switches (`Switches`); `seed_systems()`. |

## Graph

```
provider: intake (PHI redaction, facts, injection flag)
  -> [eligibility (MCP; failure -> "unknown") || policy (ACL + plan-year RAG)] -> criteria
  -> coverage_language (subgraph, kill switch) -> draft_packet -> clinician_approval (interrupt) -> submit
member:   intake -> member_reply (status only; no medical advice)
```

## Design notes

- An eligibility failure is reported as "unknown", never as "eligible".
- Dual enforcement of sign-off: the graph interrupts, and the portal itself refuses a
  submission without a registered clinician signature.
- The kill switch disables only the coverage-language subgraph; a template takes over.

## Run

```bash
python projects/14-healthcare-prior-auth/run.py                    # demo (offline, mock LLM)
python projects/14-healthcare-prior-auth/run.py --mermaid projects/14-healthcare-prior-auth/graph.mmd  # also refresh the Mermaid diagram
pytest projects/14-healthcare-prior-auth                           # tests
python -m evals --project 14                # golden-set eval
CHAOS_FAULTS=model python projects/14-healthcare-prior-auth/run.py   # demo with every model deployment down
```

See the [project README](../README.md) for the business problem and design trade-offs, and [`DOCTRINE.md`](../DOCTRINE.md) for the five-exit table per node.
