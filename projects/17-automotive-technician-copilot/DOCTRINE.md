# Doctrine card: Automotive technician copilot - current TSB wins, captioned wiring diagrams, warranty HITL

<!-- GENERATED from doctrine.yaml + evals/scores.json by `python -m shared.doctrine render`. Do not edit by hand. -->

> A service-bay copilot for technicians. The VIN is decoded over MCP. Technical service bulletins are retrieved as of the repair date and filtered by model, year range, engine and build date. Superseded bulletins are dropped, so the current TSB always wins even if an old bulletin was never formally retired. Wiring diagrams are retrieved through caption text and image IDs, which stand in for a vision model. A safety check rejects any torque value, part number or citation that is not in a current, applicable bulletin (the wrong-version test). Parts availability (ATP) is read via MCP and follows part supersession. Warranty coverage is a deterministic tool, and every covered claim goes to a warranty administrator. Claims are never auto-approved.

| Field | Value |
|---|---|
| Owner | Jagadish Meduri |
| Industry | Automotive (dealer service, OEM warranty) |
| Maturity | **Level 3**: the copilot drafts guidance and prepares claims; a technician does the work and a warranty administrator approves every claim |
| Next rung | add a real vision model over diagram images with caption-agreement checks, and auto-approve low-value claims once audit agreement is proven |
| Graph | `tech_copilot.graph:build_graph` |

## Plane dependencies

| Plane | Dependency |
|---|---|
| Experience | technician tablet in the service bay; warranty administrator approval queue |
| Agent | LangGraph graph (intake -> [tsb || diagrams] -> procedure -> parts -> warranty -> warranty_approval -> finalize); safety check in procedure |
| Knowledge | TSB corpus (issue/retire dates, supersession, applicability registry) and wiring-diagram captions keyed by image ID, on the shared ContextBuilder |
| Data | vehicle (VIN decode), parts ATP and warranty via MCP; reader and warranty-writer identities |

## Systems of record and semantic models

| System | Kind | Contract | Access |
|---|---|---|---|
| Vehicle master | mcp | `vehicle.decode_vin(vin) -> model, year, engine, build_date, mileage` | read |
| Parts / DMS | mcp | `parts.check_atp(part_number, dealer) -> on_hand, eta_days, superseded_by` | read |
| Warranty system | mcp | `warranty.check_coverage(vin, op_code, repair_date); warranty.submit_claim(claim, idempotency_key, dry_run)` | read_write |

## Knowledge: retrieval corpora and ACL

| Corpus | Owner | ACL | Temporal validity | Refresh SLA | Sensitivity |
|---|---|---|---|---|---|
| tsb | Jagadish Meduri (OEM technical service) | technician | valid from the issue date, until the retire date or until superseded by a bulletin valid on the repair date | on bulletin publication | internal |
| wiring-diagrams | Jagadish Meduri (OEM service information) | technician | by model year range (harness revision) | on harness revision | internal |

Applicability (model, years, engine, build date) and supersession are structured metadata checked in code, not left to similarity.

## MCP / A2A contracts

- MCP `vehicle.decode_vin(vin)`
- MCP `parts.check_atp(part_number, dealer)`
- MCP `warranty.check_coverage(vin, op_code, repair_date)`
- MCP `warranty.submit_claim(claim, idempotency_key, dry_run)`

An OEM field-quality agent could consume repeat-repair patterns over the shared A2A contract.

**Tool identities (gateway allowlists):**

| Identity | Allowed tools |
|---|---|
| `mi-tech-reader` | `vehicle.decode_vin`, `parts.check_atp`, `warranty.check_coverage` |
| `mi-warranty-writer` | `warranty.submit_claim` |

## Stop conditions

- unknown VIN -> no bulletin guidance
- no current applicable TSB -> standard diagnostic flow, no specs
- any torque value, part number or citation not in a current applicable TSB -> guidance replaced by bulletin text
- covered repair -> warranty administrator decision; agents and technicians cannot approve
- coverage unknown -> no claim

## Failure playbook (five exits per node)

| Node | Success | Retry (backoff) | Compensate | Degrade | Escalate |
|---|---|---|---|---|---|
| `intake` | VIN decoded, concern sanitised | gateway backoff | n/a (read-only) | instruction-like concern text neutralised | VIN not decodable -> no guidance, service advisor |
| `tsb` | applicable, current bulletins as of the repair date | n/a (idempotent search) | n/a | bulletin index down -> no bulletin, standard diagnosis | n/a |
| `diagrams` | applicable diagram (harness revision by year) retrieved by caption | n/a (idempotent search) | n/a | diagram index down -> guidance without diagrams | n/a |
| `procedure` | model guidance passing the spec and citation safety check | fallback deployment | n/a | model down or safety failure -> verbatim bulletin text | n/a |
| `parts` | ATP for bulletin parts, following part supersession | gateway backoff | n/a (read-only) | parts system down -> ATP unknown, check with the parts counter | n/a |
| `warranty` | coverage decision from the warranty tool | gateway backoff | n/a (read-only) | warranty down -> coverage unknown, no claim | n/a |
| `warranty_approval` | administrator approves or rejects | n/a | n/a | n/a | non-administrator approver -> refused, no claim |
| `finalize` | claim submitted (idempotency key claim:<ro>) only after approval | gateway backoff with the same key | withdraw claim in the warranty system | warranty down at submit -> claim pending | n/a |

## Chaos scenarios (asserted in `tests/test_chaos.py`)

| Fault | Node | Expected exit | Invariant |
|---|---|---|---|
| `model` | `procedure` | **degrade** | verbatim current bulletin (32 Nm), never the superseded spec |
| `retrieval` | `tsb` | **degrade** | no specs, no bulletin citations, no claim |
| `sor:parts` | `parts` | **degrade** | ATP unknown; guidance unaffected |
| `sor:warranty` | `warranty` | **degrade** | coverage unknown; no claim |
| `jailbreak` | `intake` | **degrade** | injected concern text neutralised; current bulletin still found |

## Evaluation

Golden set: `evals/golden.jsonl` · suite: `tech_copilot.eval_suite:run_case` · run `python -m evals --project 17`

| Metric | Threshold | Current |
|---|---|---|
| task_success | >=0.95 | 1.00 |
| groundedness | >=0.95 | 1.00 |
| policy_violation_rate | <=0 | 0.00 |
| tool_error_rate | - | 0.07 |
| cost_per_task | <=0.002 | $0.00006 |

Cases: 17 · gate: **PASS**

## KPIs

| KPI | Target | How measured |
|---|---|---|
| Wrong-version guidance | 0 superseded torque specs or part numbers shown | safety check + golden wrong-version case |
| Diagnostic time to first fix | -20% on TSB-covered concerns | repair order clock times, before vs after |
| Warranty claim rejection rate | down vs baseline | OEM claim rejections for wrong op code or parts |
| Auto-approved claims | 0 | claims without an administrator approver |

## ROI sketch

Technicians lose time searching bulletins and diagrams, and a superseded spec means a comeback or a safety issue. A copilot that shows only the current bulletin with the right harness revision cuts diagnosis time and comebacks. Checking parts ATP up front avoids vehicles waiting on lifts. Warranty claims prepared with the correct op code and parts reduce OEM rejections. Warranty spend stays under human control because every claim needs an administrator. Costs are bulletin and diagram ingestion, DMS/parts/warranty integration and model usage.
