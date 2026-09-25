# Agentic AI Portfolio

Ten production-style business agents built with **LangGraph** and **LangChain**, put together
by Jagadish Meduri over a 12-week prep for Staff-level agentic AI engineering interviews.
Each project picks one real business workflow and one graph pattern (routing, human-in-the-loop,
map-reduce, supervisor, and so on). Each one comes with typed state, mock enterprise services,
tests, and a README covering design trade-offs and interview talking points.

> **Offline by default.** Every project runs offline against a deterministic mock chat model.
> This covers tests, CI, and demos. To use a real model, set Azure OpenAI or OpenAI env vars
> (see [`.env.example`](.env.example)) and the shared factory in [`shared/llm.py`](shared/llm.py)
> picks it up automatically. You don't need to change any code.

## Projects

| #  | Project | Business use case | Graph pattern | Status |
|----|---------|-------------------|---------------|--------|
| 01 | [policy-qa-rag](projects/01-policy-qa-rag) | Cited answers to HR/IT/expense policy questions | Corrective RAG: rewrite → retrieve → grade → retry → grounded answer | ✅ Built |
| 02 | [ticket-triage](projects/02-ticket-triage) | Classify and route support tickets | Structured-output routing, `Send` fan-out | 📝 Planned |
| 03 | [refund-agent](projects/03-refund-agent) | Customer refunds with policy checks and approvals | Deterministic workflow + HITL `interrupt()` + idempotency | ✅ Built |
| 04 | [sales-meeting-prep](projects/04-sales-meeting-prep) | Pre-call account brief for AEs | Parallel fan-out / fan-in | 📝 Planned |
| 05 | [invoice-po-matching](projects/05-invoice-po-matching) | AP 3-way match and exception handling | Pipeline + exception subgraph + HITL | 📝 Planned |
| 06 | [incident-investigator](projects/06-incident-investigator) | On-call root-cause investigation | Bounded ReAct / plan-execute-reflect | 📝 Planned |
| 07 | [rfp-response](projects/07-rfp-response) | Draft RFP / security questionnaire answers | Plan-and-execute with subgraphs | 📝 Planned |
| 08 | [contract-review](projects/08-contract-review) | Playbook-based contract risk review | Critic / reviser loop with citations | 📝 Planned |
| 09 | [collections-agent](projects/09-collections-agent) | Overdue-invoice outreach and negotiation | Long-running durable workflow + guardrails | 📝 Planned |
| 10 | [supply-chain-multi-agent](projects/10-supply-chain-multi-agent) | Replenishment: forecast, stock, sourcing, approved PO | Supervisor multi-agent + parallel `Send` + critic loop + HITL | ✅ Built |

## Repo layout

```
shared/            # LLM factory (mock | Azure OpenAI | OpenAI) and shared utilities
projects/NN-name/  # one folder per project: README, package, tests, run.py
.github/workflows/ # CI: ruff + pytest (offline)
```

## Setup

Requires Python 3.11+. The recommended path uses [uv](https://docs.astral.sh/uv/):

```bash
uv sync --all-extras --group dev   # creates .venv from uv.lock
source .venv/bin/activate
```

If you only have pip:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[openai]" pytest ruff
```

## Run tests and lint

```bash
ruff check . && ruff format --check .
pytest                     # all projects, offline, mock LLM
```

## Run a demo

```bash
python projects/03-refund-agent/run.py
python projects/10-supply-chain-multi-agent/run.py
python projects/01-policy-qa-rag/run.py
```

## Using a real LLM (optional)

```bash
cp .env.example .env       # fill in Azure OpenAI or OpenAI values, then export them
export $(grep -v '^#' .env | xargs)
python projects/03-refund-agent/run.py
```

Provider resolution works like this: `LLM_PROVIDER` (mock|azure|openai) wins if set. Otherwise
Azure is used when `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, and `AZURE_OPENAI_DEPLOYMENT`
are all present. Failing that, OpenAI is used when `OPENAI_API_KEY` is present. If none of these
apply, the mock model is used.

## License

[MIT](LICENSE) © 2026 Jagadish Meduri
