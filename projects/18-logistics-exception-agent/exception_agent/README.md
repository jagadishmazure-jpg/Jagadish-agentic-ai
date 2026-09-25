# `exception_agent/`: event-driven logistics exceptions

The importable package for project 18. A consumer on a partitioned milestone stream (an Event
Hubs stand-in with checkpoints) validates events, dead-letters malformed ones and runs the
exception graph once per slipped (shipment, milestone), even across a crash and replay. The
graph answers tracking questions only from TMS scan events and refuses to interpolate across a
scan gap, drafts proactive notices only for high-confidence, current events (with a capacity
what-if from an A2A peer agent), and prepares carrier claims from OCR'd documents using the
claim rules in force on the ship date.

| File | What it does |
|---|---|
| [`__init__.py`](__init__.py) | Empty package marker. |
| [`capacity.py`](capacity.py) | Demand/capacity peer agent on the shared A2A contract: agent card, `network_whatif` skill (lane demand reuses project 10's forecasting; alternatives flagged `capacity_ok`), a registration/tenant `guard`, `app()` and `client()`. |
| [`demo.py`](demo.py) | CLI behind `run.py`: stream consumer with a duplicate, an on-time and a malformed event plus crash/restart, tracking with fresh scans versus a scan gap, an inferred slip that goes to the exception desk, and clean versus smudged claim documents; `--mermaid PATH`. |
| [`eval_suite.py`](eval_suite.py) | `run`, `run_case`, `slip_event`, `request`, `systems_for`, `violations`, `chaos_scenario` and `CHAOS_CHECKS`. |
| [`events.py`](events.py) | Stream stand-in: `EventHub` (stable-hash partitioning by shipment id), `CheckpointStore`, `Consumer` (at-least-once from the last checkpoint), `MilestoneEvent`, `slipped()` and `MilestoneTrigger` (validate, dead-letter, dedupe per shipment and milestone). |
| [`graph.py`](graph.py) | `build_graph()` and `ExState`. Nodes: `intake`, `track`, `evidence`, `whatif`, `comms`, `ocr`, `claim`, `respond`. Also `eager_responder`, a model that interpolates location and speculates, used to prove the guard. |
| [`knowledge.py`](knowledge.py) | Carrier claim rules by tariff edition (temporal, per tenant contract) and the proactive-communication policy on `shared.context`. Tracking facts are never retrieved from here. |
| [`ocr.py`](ocr.py) | OCR mock for BOL, POD and damage reports: `analyze()` (typed 0.98, handwritten 0.78, smudged 0.45) and `low_confidence()`. |
| [`sor.py`](sor.py) | MCP servers (TMS, comms, claims) and gateways (reader, comms writer, claims writer). |
| [`systems.py`](systems.py) | Mock TMS (shipments and scan events), customer comms outbox and carrier claims; `seed_systems()`. |

## Graph

```
intake (TMS shipment via MCP, tenant-scoped) routes by kind:
  track -> track (scan events only; refuse to interpolate on a gap)
  slip  -> [evidence (freshness + event confidence) || whatif (A2A capacity agent)] -> comms
  claim -> ocr (low confidence or TMS mismatch -> queue) -> claim (rules as-of ship date; window check)
-> respond
```

## Design notes

- The dedupe set is checkpointed with the stream position, so a crash and replay triggers the
  graph once per milestone.
- Notices are idempotent per milestone; a capacity-agent refusal escalates the what-if but the
  notice still goes out.

## Run

```bash
python projects/18-logistics-exception-agent/run.py                    # demo (offline, mock LLM)
python projects/18-logistics-exception-agent/run.py --mermaid projects/18-logistics-exception-agent/graph.mmd  # also refresh the Mermaid diagram
pytest projects/18-logistics-exception-agent                           # tests
python -m evals --project 18                # golden-set eval
CHAOS_FAULTS=model python projects/18-logistics-exception-agent/run.py   # demo with every model deployment down
```

See the [project README](../README.md) for the business problem and design trade-offs, and [`DOCTRINE.md`](../DOCTRINE.md) for the five-exit table per node.
