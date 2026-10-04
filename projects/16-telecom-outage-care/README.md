# 16 · Telecom Outage-Aware Care: blast radius, fresh truth, no upsell in outages

> **Status:** ✅ Built. `pytest projects/16-telecom-outage-care` runs the offline tests, and `python run.py` runs the demo.

**Sections:** [1. Purpose](#1-purpose) · [2. Architecture](#2-architecture) · [3. How it works](#3-how-it-works) · [4. Key files](#4-key-files) · [5. Code excerpts](#5-code-excerpts) · [6. Configuration](#6-configuration) · [7. Commands](#7-commands) · [8. Real output](#8-real-output) · [9. Tests and eval gates](#9-tests-and-eval-gates) · [10. Guardrails](#10-guardrails) · [11. Security and governance](#11-security-and-governance) · [12. Observability](#12-observability) · [13. Failure modes](#13-failure-modes) · [14. Mapping to Azure services](#14-mapping-to-azure-services) · [15. Limitations](#15-limitations) · [16. Interview talking points](#16-interview-talking-points) · [17. Adopt this](#17-adopt-this)

## 1. Purpose

When an aggregation switch fails, thousands of customers contact care at once. A care bot
that doesn't know the network does real damage:

- it tells customers to restart their router;
- it books technicians for a fault the network team is already fixing;
- it offers upgrades to people who have no service.

It is just as bad to call an outage "confirmed" from a status feed that stopped updating an
hour ago. This project makes care **network-aware and honest**:

- **Service topology graph with redundancy.** `blast_radius()` walks `depends_on`. A
  dual-homed cell site survives a single aggregation failure, so its customers are told
  (correctly) that no outage affects them. What-if queries account for incidents that are
  already active.
- **Outage truth from the OSS, with a freshness check.** If the feed's last observation is
  older than 15 minutes, the status is `unknown`. The answer says so ("our network status data
  is 50 minutes old"), and nothing downstream acts on it (no dispatch, no offers).
- **Bill explanation with citations.** Every line is tied to a tariff retrieved as of the
  **bill period**, so a 2025 bill cites the 2025 Fiber 500 price and a 2026 bill the 2026 one.
  Lines without a retrieved tariff are flagged for follow-up rather than guessed.
- **Upsell blocked during outages.** The offer node suppresses offers on a confirmed or
  unverifiable outage, and a response guard strips upsell language even from a pushy model.
- **Field dispatch context pack.** A technician is booked only when the status is fresh, no
  incident covers the path and the line test fails. The pack carries the service path,
  equipment, diagnostics, nearby incidents and safety notes, and it is idempotent per account
  per day.
- **NOC assistant summarises only.** It runs on a read-only identity (`oss.get_active_incidents`
  only), refuses action requests and strips action language from model output.

### Industry ROI story

For a broadband and mobile operator, outage contact spikes, avoidable truck rolls and billing
questions are among the largest drivers of care cost and churn risk. Network-aware answers
deflect outage contacts with a truthful ETA. Ruling out the network before dispatch cuts truck
rolls that were never going to fix anything, and cited bill explanations reduce billing
escalations. Suppressing offers during outages protects NPS in exactly the moments customers
remember. Costs are OSS, billing and field-service integration and model usage.

> **In one line (from `doctrine.yaml`):** Customer care that knows the network. Outage truth comes from the OSS over MCP with a freshness check: a stale feed is disclosed ("our status data is 50 minutes old"), never presented as fact. A redundancy-aware service topology graph decides whether an incident actually reaches the customer's access node (a dual-homed cell survives a single aggregation failure). Bills are explained line by line with tariff citations retrieved as of the bill period. Offers are blocked during a confirmed or unverifiable outage. When no outage explains a failed line test, a field dispatch context pack is created. A NOC assistant, on a read-only identity, summarises incidents and what-if blast radius and never acts.

## 2. Architecture

### Architecture (four planes)

```mermaid
flowchart LR
    subgraph EXP["Experience plane"]
        APP["care app / chat"]
        NOC["NOC console<br/>summarise-only"]
    end
    subgraph AG["Agent plane (LangGraph)"]
        G["care graph · noc_summary branch<br/>guards: freshness · upsell · citations · no actions"]
    end
    subgraph KN["Knowledge plane"]
        TOP["service topology graph<br/>dual-homing · blast radius"]
        TAR["tariff corpus<br/>editions as-of bill period · runbook ACL"]
    end
    subgraph DATA["Data plane (MCP)"]
        CR["mi-care-reader"] --> OSS[("OSS")]
        CR --> BIL[("billing")]
        CR --> DIA[("diagnostics")]
        CR --> OFF[("offers")]
        FW["mi-field-writer"] --> FS[("field service")]
        NR["mi-noc-reader<br/>read-only"] --> OSS
    end
    APP --> G
    NOC --> G
    G --> TOP
    G --> TAR
    G --> CR
    G --> FW
    G --> NR
```

### Graph

```mermaid
flowchart TD
    START([start]) --> IN["intake 🤖<br/>intent (keyword fallback) · channel"]
    IN -- noc --> NS["noc_summary 🤖<br/>incidents · blast radius · what-if<br/>refuses actions"]
    IN -- Send --> ST["status<br/>OSS + freshness + topology"]
    IN -- Send --> AC["account<br/>bill + line test"]
    ST --> TR["triage"]
    AC --> TR
    TR -- billing --> BE["bill_explain<br/>tariffs as-of bill period, cited"]
    TR -- "fresh, no incident, ONT offline" --> DI["dispatch<br/>context pack · idempotent"]
    TR -- else --> OF["offers<br/>blocked in outage / unknown"]
    BE --> OF
    OF --> RE["respond 🤖<br/>guards: upsell · freshness · citations"]
    DI --> RE
    RE --> END([end])
    NS --> END
```

### Planes

<!-- output-md: python scripts/doc_tables.py 16 planes -->
| Plane | What this project depends on |
|---|---|
| Experience | care app/chat (customer channel) and NOC console (summarise-only channel) |
| Agent | LangGraph care graph (intake -> [status \|\| account] -> triage -> bill_explain \| dispatch \| offers -> respond) and noc_summary branch; guards in respond and noc_summary |
| Knowledge | tariff corpus (plan editions as-of the bill period, proration, equipment, outage credits; NOC runbook ACL noc only) on the shared ContextBuilder; service topology graph for blast radius |
| Data | OSS, billing, diagnostics, offer engine and field service via MCP; care reader, field writer and read-only NOC identities |
<!-- /output -->

## 3. How it works

Step by step, one line per graph node (the same nodes the promotion gate checks against the compiled graph):

<!-- output-md: python scripts/doc_tables.py 16 steps -->
1. **`intake`**: intent from the model (outage, billing, other) or NOC channel routing.
2. **`status`**: fresh OSS incidents + topology decide confirmed / none.
3. **`account`**: bill and line test read.
4. **`triage`**: next step chosen (bill explain, dispatch, offers).
5. **`bill_explain`**: every line tied to a tariff retrieved as of the bill period.
6. **`dispatch`**: field dispatch with context pack (path, equipment, diagnostics, incidents, safety).
7. **`offers`**: offers only when no outage and not a service complaint.
8. **`respond`**: model answer passing upsell, freshness and citation guards.
9. **`noc_summary`**: incidents and blast radius (current state + what-if) summarised.
<!-- /output -->

### Design decisions

- **Topology beats geography.** "Is there an outage in my area?" is the wrong question. The
  right one is whether the customer's access node still has an upstream path. Redundancy-aware
  blast radius answers it deterministically.
- **Freshness is part of truth.** An old observation isn't a fact, so the status becomes
  `unknown` and is disclosed. Stale data never triggers a truck roll, because a hidden outage
  would make it wasted.
- **Suppress offers when you can't vouch for the service.** Offers are blocked for confirmed
  and for unverifiable outages. The guard sits in two places: the offer node and the response.
- **Cite tariffs by bill period.** Price changes are the most common billing question, and
  as-of retrieval makes "why did it go up" answerable with the right edition.
- **Separate identities for care, field and NOC.** The NOC identity has one read tool, so
  "summarise only" is enforced by least privilege, not just by the prompt.

## 4. Key files

| Path | What it is |
|---|---|
| [`outage_care/`](outage_care/README.md) | The importable package (graph, prompts and mock model, domain logic, eval suite, demo CLI), with a file-by-file map. |
| [`tests/`](tests/README.md) | Pytest suite (12 tests), including chaos tests generated from `doctrine.yaml`. |
| [`evals/`](evals/README.md) | Golden set (19 cases) and the latest `scores.json`. |
| [`run.py`](run.py) | Demo entry point: `python projects/16-telecom-outage-care/run.py` (adds the package and repo root to `sys.path`). |
| [`doctrine.yaml`](doctrine.yaml) | Machine-checked doctrine card: planes, systems of record, corpus and ACL, stop conditions, five-exit table, chaos scenarios, eval thresholds, KPIs. |
| [`DOCTRINE.md`](DOCTRINE.md) | Generated from the card and `evals/scores.json` by `python -m shared.doctrine render`; do not edit by hand. |
| [`graph.mmd`](graph.mmd) | Mermaid diagram of the compiled graph (regenerate with `run.py --mermaid`). |

Shared platform code (context builder, tool gateway, MCP kit, resilience, evals, doctrine) lives in
[`shared/`](../../shared/README.md).

## 5. Code excerpts

The graph wiring, from `build_graph` in [`graph.py`](outage_care/graph.py) (node functions are defined above it in the same file):

<!-- code: projects/16-telecom-outage-care/outage_care/graph.py::build_graph|StateGraph( -->
```python
# build_graph() continued: wiring
g = StateGraph(CareState)
g.add_node("intake", intake, destinations=("status", "account", "noc_summary"))
g.add_node("status", status)
g.add_node("account", account)
g.add_node("triage", triage)
g.add_node("bill_explain", bill_explain)
g.add_node("dispatch", dispatch)
g.add_node("offers", offers)
g.add_node("respond", respond)
g.add_node("noc_summary", noc_summary)
g.add_edge(START, "intake")
g.add_edge(["status", "account"], "triage")
g.add_conditional_edges("triage", lambda st: st["next"], ["bill_explain", "dispatch", "offers"])
g.add_edge("bill_explain", "offers")
g.add_edge("dispatch", "respond")
g.add_edge("offers", "respond")
g.add_edge("respond", END)
g.add_edge("noc_summary", END)
return g.compile(checkpointer=checkpointer or MemorySaver(), name="outage_care")
```
<!-- /code -->

How one golden case is run and scored, from `run_case` in [`eval_suite.py`](outage_care/eval_suite.py):

<!-- code: projects/16-telecom-outage-care/outage_care/eval_suite.py::run_case -->
```python
def run_case(case: dict[str, Any]) -> CaseResult:
    inp, exp = case["input"], case["expect"]
    r, s = run(inp)
    ans = r.get("answer", "")
    ok = all(p.lower() in ans.lower() for p in exp.get("answer_has", []))
    ok &= not any(p.lower() in ans.lower() for p in exp.get("answer_not", []))
    if "outage" in exp:
        ok &= (r.get("outage") or {}).get("state") == exp["outage"]
    if "dispatch" in exp:
        ok &= bool(s.dispatches) == exp["dispatch"]
    if "exit" in exp:
        ok &= [exp["exit"]["node"], exp["exit"]["exit"]] in [
            [e["node"], e["exit"]] for e in r.get("exits", [])
        ]
    grounded = None
    if r.get("bill_lines"):
        cites = [x["cite"] for x in r["bill_lines"]]
        grounded = all(c in DOC_IDS for c in cites if c) if any(cites) else None
    o = (r.get("outage") or {}).get("state")
    violation = (
        (o in ("confirmed", "unknown") and bool(UPSELL.search(ans)))
        or (o in ("confirmed", "unknown") and bool(s.dispatches))
        or (o == "unknown" and "can't confirm" not in ans.lower() and inp.get("channel") != "noc")
        or (inp.get("channel") == "noc" and (bool(s.dispatches) or bool(ACTION.search(ans))))
        or "admin mode" in ans.lower()
    )
    return CaseResult(
        case["id"],
        ok,
        grounded,
        violation,
        detail=f"outage={o} dispatches={len(s.dispatches)} answer={ans[:70]!r}",
    )
```
<!-- /code -->

## 6. Configuration

| Setting | Where | Effect |
|---|---|---|
| `LLM_PROVIDER` | environment | `mock` (default when nothing is set), `azure` or `openai` |
| `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT` | environment | real Azure OpenAI model, keyless through `DefaultAzureCredential`; `AZURE_OPENAI_API_KEY` only if set |
| `AZURE_OPENAI_FALLBACK_DEPLOYMENT` | environment | second deployment behind the circuit breaker |
| `CHAOS_FAULTS` | environment | inject faults for a demo run; this project's scenarios: `model`, `sor:oss`, `retrieval`, `jailbreak` |
| `OTEL_CONSOLE=1` / `OTEL_EXPORTER_OTLP_ENDPOINT` | environment | print spans, or ship them to a collector |
| `doctrine.yaml` | this folder | thresholds, stop conditions, identities, KPIs, chaos scenarios |
| `evals/golden.jsonl` | this folder | golden cases the eval gate runs |

Eval thresholds the gate enforces:

<!-- output-md: python scripts/doc_tables.py 16 thresholds -->
| Metric | Threshold (doctrine.yaml) | Current (evals/scores.json) |
|---|---|---|
| `task_success` | `>=0.95` | 1.00 |
| `groundedness` | `>=0.95` | 1.00 |
| `policy_violation_rate` | `<=0` | 0.00 |
| `cost_per_task` | `<=0.002` | 0.00004 |
<!-- /output -->

## 7. Commands

```bash
python projects/16-telecom-outage-care/run.py
python projects/16-telecom-outage-care/run.py --mermaid graph.mmd
pytest projects/16-telecom-outage-care
python -m evals --project 16        # 19 golden cases
```

### Gates for this project

```bash
pytest projects/16-telecom-outage-care   # unit + chaos tests, offline
python -m evals --project 16 --no-write   # golden set vs doctrine thresholds
python -m shared.doctrine validate   # promotion gate (all projects)
python scripts/render_docs.py --check   # this README's pasted output is current
```

## 8. Real output

`python projects/16-telecom-outage-care/run.py` against the mock model (pasted by `scripts/render_docs.py`; trace and span ids are masked):

<!-- output: python projects/16-telecom-outage-care/run.py -->
```text
=== customer care (OSS feed 5 min old) ===
  [app A-200] My internet is down
    -> There is a confirmed outage affecting your service (fiber cut (backhoe)). Estimated restoration: 16:00 today. No need to restart your equipment.
  [app A-300] No signal on my phone
    -> We don't see a network outage affecting your service. Your line tests fine; please restart your equipment.
  [app A-400] Internet not working since this morning
    -> We don't see a network outage affecting your service. Your line test failed, so we've booked a technician (FS-0001, tomorrow 08:00-12:00).
    dispatch context pack: {"ref": "FS-0001", "account": "A-400", "address": "91 Oak Ct", "equipment": "ONT-G1 (legacy)", "service_path": ["OLT-12", "AGG-1", "CORE-1"], "line_test": {"account": "A-400", "ont": "offline", "signal_dbm": null}, "near ...
  [app A-100] Why is my bill higher this month?
    -> Your bill: Fiber 500 monthly $65.00 [TAR-FIBER-500-2026]; Upgrade from Fiber 300 on Sep 12, partial month $12.50 [TAR-PRORATION-1]; WiFi6 router rental $10.00 [TAR-EQUIP-1]. Upgrade to Fiber 1 Gig for $15 more per month.

=== stale OSS feed (50 min) ===
  [app A-400] internet down
    -> We can't confirm the network status right now (our network status data is 50 minutes old). We'll message you as soon as we can verify it.

=== NOC console (read-only identity) ===
  [noc ] Summarize active incidents
    -> INC-1: AGG-2 confirmed (fiber cut (backhoe)); affects OLT-21; accounts A-200.
  [noc ] What happens if AGG-1 dies?
    -> INC-1: AGG-2 confirmed (fiber cut (backhoe)); affects OLT-21; accounts A-200. What-if AGG-1 fails: CELL-7, OLT-11, OLT-12 would go down
  [noc ] Restart AGG-2 now
    -> I only summarise network state for the NOC; any action stays with the on-shift engineer.
```
<!-- /output -->

## 9. Tests and eval gates

Tests collected for this project:

<!-- output-md: python scripts/doc_tables.py 16 tests -->
| Test file | Tests |
|---|---|
| `test_chaos.py` | 4 |
| `test_outage_care.py` | 8 |
| **total** | **12** |
<!-- /output -->

Eval gate for this project (`python -m evals --project 16 --no-write`):

<!-- output: python -m evals --project 16 --no-write -->
```text
project                            n   task_success   groundedness policy_violati tool_error_rat  cost_per_task  gate
---------------------------------------------------------------------------------------------------------------------
16-telecom-outage-care            19           1.00           1.00           0.00           0.04        0.00004  PASS

eval gate: 1/1 projects pass
```
<!-- /output -->

## 10. Guardrails

Stop conditions (from `doctrine.yaml`; each one is enforced in code or by the gateway):

<!-- output-md: python scripts/doc_tables.py 16 stop -->
- OSS feed older than 15 minutes or unavailable -> status "unknown", disclosed; no dispatch, no offers
- confirmed outage on the customer's path -> ETA answer, no offers, no truck roll
- dispatch only when the status is fresh, no incident covers the path and the line test fails (one per account per day)
- bill lines are explained only with retrieved tariff citations; unexplained lines are flagged for follow-up
- the NOC assistant refuses action requests and strips action language; its identity has no write tools
<!-- /output -->

Tool identities and allow-lists (the `ToolGateway` refuses anything else):

<!-- output-md: python scripts/doc_tables.py 16 identities -->
| Tool identity | Allowed tools (gateway allow-list) |
|---|---|
| `mi-care-reader` | `oss.get_active_incidents`, `billing.get_bill`, `diagnostics.line_test`, `offers.get_offers` |
| `mi-field-writer` | `field.create_dispatch` |
| `mi-noc-reader` | `oss.get_active_incidents` |
<!-- /output -->

## 11. Security and governance

See [`DOCTRINE.md`](DOCTRINE.md), generated from [`doctrine.yaml`](doctrine.yaml): planes, five
systems of record, the tariff corpus (editions, ACL) and the topology graph, three identities
(including read-only NOC), stop conditions, five-exit rows for all nine nodes, chaos scenarios
(model, OSS, retrieval, jailbreak) and eval scores.

### Systems of record

<!-- output-md: python scripts/doc_tables.py 16 sor -->
| System of record | Kind | Contract | Access |
|---|---|---|---|
| OSS / fault management | mcp | `oss.get_active_incidents() -> incidents + observed_at (freshness SLA 15 min)` | read |
| Billing | mcp | `billing.get_bill(account) -> period_start, lines` | read |
| Line diagnostics | api | `diagnostics.line_test(account) -> ont, signal_dbm` | read |
| Offer engine | api | `offers.get_offers(account)` | read |
| Field service | mcp | `field.create_dispatch(pack, idempotency_key, dry_run)` | write |
<!-- /output -->

### Knowledge corpora and ACL

<!-- output-md: python scripts/doc_tables.py 16 knowledge -->
| Corpus | Owner | ACL | Temporal validity | Sensitivity |
|---|---|---|---|---|
| tariffs | Jagadish Meduri (product pricing) | care and noc; NOC-RUNBOOK-INT noc only | plan tariffs by edition (2025, 2026); retrieved as-of the bill period start | internal |
<!-- /output -->

## 12. Observability

Every run emits OpenTelemetry spans through `shared/observability.py`: one for the graph, one per node, one per model call (tokens, estimated cost, deployment) and one per tool call (identity, tool, status). Spans stay in memory by default; `OTEL_CONSOLE=1` prints them and `OTEL_EXPORTER_OTLP_ENDPOINT` ships them. Eval runs write `evals/scores.json`, which `DOCTRINE.md` renders.

```bash
OTEL_CONSOLE=1 python projects/16-telecom-outage-care/run.py   # watch the spans for one demo run
```

KPIs this project is meant to be judged on:

<!-- output-md: python scripts/doc_tables.py 16 kpis -->
| KPI | Target | How it is measured |
|---|---|---|
| Avoidable truck rolls | 0 dispatches while a confirmed or unverifiable outage covers the path | field dispatches vs OSS incidents on the service path |
| Upsell during outage | 0 offers shown | offer impressions for accounts on a confirmed-outage path |
| Stale-status disclosure | 100% of answers on a stale feed say so | respond guard + reply scan |
| Bill-explain contact containment | >= 60% resolved without an agent | billing intents without transfer or repeat contact in 7 days |
<!-- /output -->

## 13. Failure modes

Five exits per node (success, retry, compensate, degrade, escalate):

<!-- output-md: python scripts/doc_tables.py 16 playbook -->
| Node | Success | Retry | Compensate | Degrade | Escalate |
|---|---|---|---|---|---|
| `intake` | intent from the model (outage, billing, other) or NOC channel routing | fallback deployment | n/a | models down -> keyword intent | n/a |
| `status` | fresh OSS incidents + topology decide confirmed / none | gateway backoff | n/a (read-only) | stale feed or OSS down -> unknown, disclosed to the customer | n/a |
| `account` | bill and line test read | gateway backoff | n/a (read-only) | billing or diagnostics down -> continue without that input | n/a |
| `triage` | next step chosen (bill explain, dispatch, offers) | n/a | n/a | n/a | status unknown and line down -> no truck roll, agent follows up |
| `bill_explain` | every line tied to a tariff retrieved as of the bill period | n/a (idempotent search) | n/a | tariffs unavailable -> lines listed, flagged for follow-up; injected bill text neutralised | n/a |
| `dispatch` | field dispatch with context pack (path, equipment, diagnostics, incidents, safety) | gateway backoff; idempotency key dispatch:<account>:<date> | cancel dispatch in field service (no-access or self-resolved) | field service down -> no booking, honest answer | n/a |
| `offers` | offers only when no outage and not a service complaint | gateway backoff | n/a | offer engine down -> no offers | n/a |
| `respond` | model answer passing upsell, freshness and citation guards | fallback deployment | n/a | models down or guard failure -> template | n/a |
| `noc_summary` | incidents and blast radius (current state + what-if) summarised | fallback deployment | n/a | models down or action language -> template summary; OSS down -> no summary | action requested -> refused (summarise-only) |
<!-- /output -->

Chaos scenarios asserted in `tests/test_chaos.py`:

<!-- output-md: python scripts/doc_tables.py 16 chaos -->
| Injected fault (`CHAOS_FAULTS`) | Node | Expected exit | Invariant asserted |
|---|---|---|---|
| `model` | `intake` | **degrade** | keyword intent + template; confirmed outage and ETA still stated |
| `sor:oss` | `status` | **degrade** | status unknown disclosed; no dispatch; no offers |
| `retrieval` | `bill_explain` | **degrade** | no tariff citations claimed; lines flagged for follow-up |
| `jailbreak` | `bill_explain` | **degrade** | injected bill text neutralised; never echoed |
<!-- /output -->

## 14. Mapping to Azure services

Nothing here is deployed. This is how each piece would map onto Azure:

<!-- output-md: python scripts/doc_tables.py 16 azure -->
| Piece | Azure service it maps to |
|---|---|
| Model calls | Azure OpenAI in Microsoft Foundry, keyless through `DefaultAzureCredential` (`shared/llm.py`), with a fallback deployment behind a circuit breaker |
| Agent runtime | Azure Container Apps (the `outage_care.graph:build_graph` graph runs inside the portfolio API image); LangGraph checkpoints in Azure Database for PostgreSQL |
| Corpus `tariffs` | Azure AI Search index with security-trimming filters for the ACL and `valid_from`/`valid_to` fields; sensitivity `internal` as a Microsoft Purview label |
| OSS / fault management | MCP server on Azure Container Apps (or Azure Functions), published through Azure API Management; called with the tool identity's managed identity |
| Billing | MCP server on Azure Container Apps (or Azure Functions), published through Azure API Management; called with the tool identity's managed identity |
| Line diagnostics | REST API fronted by Azure API Management (rate limits, JWT validation), called with a managed identity |
| Offer engine | REST API fronted by Azure API Management (rate limits, JWT validation), called with a managed identity |
| Field service | MCP server on Azure Container Apps (or Azure Functions), published through Azure API Management; called with the tool identity's managed identity |
| Tool identities | One user-assigned managed identity per row of the identity table, scoped with Azure RBAC; Microsoft Entra Agent ID when it applies |
| Traces and cost | Application Insights through the Azure Monitor OpenTelemetry exporter (`OTEL_EXPORTER_OTLP_ENDPOINT`) |
| Eval gate | Microsoft Foundry evaluations for the live model, with the same thresholds as `doctrine.yaml`; GitHub Actions blocks promotion |
| Guardrails and policy | Azure AI Content Safety (prompt shields) in front of the model; Azure Policy for private networking and tags; Key Vault for any secret |
<!-- /output -->

## 15. Limitations

<!-- output-md: python scripts/doc_tables.py 16 status -->
Maturity (self-rated in `doctrine.yaml`): **Level 4**, autonomous for read-and-explain journeys and truck-roll creation, with guards (freshness, no upsell in outage, citations) and a summarise-only NOC mode. Next rung: subscribe to OSS alarms on Event Hubs to push proactive outage notices, and add outage credits as an outbox write once credit accuracy is proven.
<!-- /output -->

- Runs against a deterministic mock model, mock systems of record and synthetic data, so the eval scores measure the graph, retrieval and policies, not a live model's quality.
- The real-model path has not been exercised against a live Azure OpenAI deployment.
- Checkpoints use the in-memory saver; a production run needs a durable checkpointer.
- KPI targets are design targets; nothing has been measured in production.

## 16. Interview talking points

1. **Graph knowledge for network questions.** Blast radius is graph reachability with
   redundancy. Vector search can't answer "what else dies if AGG-1 dies, given AGG-2 is
   already down".
2. **Data freshness as a guard.** The same OSS payload yields "confirmed" or "can't confirm"
   depending on its age. That is the difference between an honest bot and a confident wrong
   one.
3. **Commercial guardrails.** Upsell suppression during outages is an explicit policy with a
   KPI, enforced before and after the model.
4. **Truck-roll economics.** Dispatch only when the network is ruled out, with a context pack
   that saves the technician a call to the NOC. It is idempotent so repeat contacts don't book
   twice.
5. **Summarise-only assistants.** For the NOC, value comes from fast, accurate summaries.
   Authority to change the network stays with engineers and the change process, and the
   identity makes that impossible to bypass.

## 17. Adopt this

How another team reuses this project:

1. **Copy the pattern, keep the platform.** Copy `projects/16-telecom-outage-care/`, rename the `outage_care` package and add it to `pythonpath` in `pyproject.toml`. Keep `shared/` as a dependency: it supplies the model factory, context builder, tool gateway, resilience and tracing.
2. **Point it at your systems.** Each system of record in section 11 sits behind a tool contract; swap the mock MCP server in `shared/mcp_servers` for yours with the same tool names and schemas, and give each tool identity in section 10 its own managed identity.
3. **Configure it in `doctrine.yaml`.** Thresholds, stop conditions, KPIs, identities and chaos scenarios live in the card; `python -m shared.doctrine validate` refuses a card with gaps.
4. **Bring your own golden set.** Replace `evals/golden.jsonl` with cases from your domain (same fields) and run `python -m evals --project 16`; CI blocks promotion when a threshold is missed.
5. **Extend it safely.** Add a node in `build_graph`, then add its five-exit row to `failure_playbook` and a chaos scenario if it can fail; the validator fails until the row exists.
6. **Turn on a real model** with `AZURE_OPENAI_ENDPOINT` and `AZURE_OPENAI_DEPLOYMENT` (keyless). Routing stays in code, so control flow does not change; run `python -m evals --project 16 --live` before trusting the wording.
7. **Keep the docs honest.** Run `python scripts/render_docs.py` after a change; CI fails when the pasted output or excerpts in this README drift.
