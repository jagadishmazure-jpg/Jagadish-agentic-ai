# `ticket_triage/`: support-ticket router with a confidence gate

The importable package for project 02. It redacts PII from an inbound ticket, asks the model
for a strictly validated classification, repairs invalid output once, and then routes by
confidence: a queue handler, a clarifying question, or a human. Routed tickets are created in
the service desk through the ticketing MCP server.

| File | What it does |
|---|---|
| [`__init__.py`](__init__.py) | Package docstring. |
| [`demo.py`](demo.py) | CLI behind `run.py`: triages a set of sample tickets and prints the route; `--mermaid PATH`. |
| [`eval_suite.py`](eval_suite.py) | `run_case`, `chaos_scenario` and `CHAOS_CHECKS` for evals and chaos tests. |
| [`graph.py`](graph.py) | `build_graph()` and `TriageState`. Nodes: `redact_pii`, `classify`, `validate`, `repair`, `clarify`, `human_review` and one handler per intent queue. |
| [`llm.py`](llm.py) | Classification and repair prompts; `keyword_classify` and a deterministic `mock_responder`. |
| [`pii.py`](pii.py) | Regex plus checksum PII redaction (`redact`, `luhn_ok` for card numbers). Returns redacted text and a placeholder vault that never leaves the node. |
| [`schema.py`](schema.py) | `TicketClassification` (the strict schema the model must return), `TriageResult` and the routing / SLA tables. |
| [`sor.py`](sor.py) | Ticketing system of record behind MCP: `TicketingBackend` (in-memory service desk), `CreatedTicket` payload contract, `build_gateway()`. Triage only creates tickets, idempotent on the inbound ticket id, and only sends redacted text. |

## Graph

```
redact_pii -> classify -> validate --invalid (<=1)--> repair -> validate
                                   --invalid again--> human_review
                          valid --> confidence gate:
                              < 0.40 human_review | < 0.60 clarify | else intent queue handler
```

## Design notes

- PII is redacted **before** any model call; the vault stays inside the node.
- All model deployments down means the ticket goes to the human queue, never a guessed route.
- Suspected injected instructions in the ticket body escalate to a human.
- A ticketing outage parks the create request in an outbox for replay.

## Run

```bash
python projects/02-ticket-triage/run.py                    # demo (offline, mock LLM)
python projects/02-ticket-triage/run.py --mermaid projects/02-ticket-triage/graph.mmd  # also refresh the Mermaid diagram
pytest projects/02-ticket-triage                           # tests
python -m evals --project 02                # golden-set eval
CHAOS_FAULTS=model python projects/02-ticket-triage/run.py   # demo with every model deployment down
```

See the [project README](../README.md) for the business problem and design trade-offs, and [`DOCTRINE.md`](../DOCTRINE.md) for the five-exit table per node.
