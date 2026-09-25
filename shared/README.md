# `shared/`: platform code used by every project

The shared platform that all eighteen projects build on. Graphs in `projects/` stay focused
on business logic; the cross-cutting controls live here so every agent gets them the same
way: the LLM factory and fallback chain, resilience primitives and the five-exit policy,
OpenTelemetry tracing and cost metering, fault injection for chaos tests, the knowledge-plane
context builder, MCP servers and the tool gateway, the A2A contract, the eval harness and the
doctrine promotion gate.

| File | What it does |
|---|---|
| [`__init__.py`](__init__.py) | Package marker (`shared` is imported as a top-level package from the repo root). |
| [`chaos.py`](chaos.py) | Chaos helpers used by every project's `tests/test_chaos.py`: `run_scenario(fault, fn)` injects a fault (`model`, `retrieval`, `sor:<server>`, `jailbreak`, ...) and runs a project scenario; `assert_exit` checks that the declared node took the declared exit; `exits_taken` lists them. |
| [`faults.py`](faults.py) | Process-wide fault registry (`inject`, `clear`, `active`, `fault`). Shared components check it at their failure boundary, so tests can kill the model, retrieval or a system of record without monkeypatching. Demos read `CHAOS_FAULTS="sor:payments,model"` from the environment. |
| [`llm.py`](llm.py) | LLM factory. `get_llm()` picks `LLM_PROVIDER` (mock/azure/openai), then Azure OpenAI, then OpenAI, then the deterministic `MockChatModel`. `get_resilient_llm()` wraps it in a primary to fallback deployment chain. |
| [`observability.py`](observability.py) | OpenTelemetry tracing and cost metering. `install()` registers one LangChain callback handler process-wide so graph, node, LLM and tool spans carry thread id, identity, token counts and estimated cost; `CostMeter`, `ToolStats`, `run_config()` for standard invoke config. Exports to memory by default, console with `OTEL_CONSOLE=1`, OTLP when configured. |
| [`resilience.py`](resilience.py) | Resilience primitives: `retry_call` with `Backoff`, `CircuitBreaker`, `FallbackChatModel` / `with_fallback` (raises `ModelUnavailableError` rather than inventing output), `FiveExitPolicy`, `exit_table` and `exit_record` for the success / retry / compensate / degrade / escalate exits every node documents. |
| [`a2a/`](a2a/README.md) | Agent-to-agent task contract: agent cards, JSON-RPC server and client with traceparent and tenant propagation. |
| [`context/`](context/README.md) | Knowledge-plane runtime: chunking, hybrid retrieval, ACL and as-of filtering, sanitising, budgeted packing, citations, cache. |
| [`doctrine/`](doctrine/README.md) | Doctrine card schema, promotion-gate validator and `DOCTRINE.md` / matrix renderer. |
| [`evals/`](evals/README.md) | Offline eval harness: golden JSONL to metrics to thresholds. |
| [`mcp_servers/`](mcp_servers/README.md) | FastMCP servers that wrap mock systems of record with small, business-shaped tool contracts. |
| [`tests/`](tests/README.md) | Unit and integration tests for everything in `shared/`. |
| [`tools/`](tools/README.md) | MCP client side: connections, LangChain adapters and the `ToolGateway`. |

## How the pieces fit

```
graph node ──get_resilient_llm()──> FallbackChatModel ──> mock | Azure OpenAI | OpenAI
     │
     ├──ContextBuilder.build(query, principal, as_of)──> shared/context (ACL, temporal, hybrid, sanitize, pack)
     │
     └──ToolGateway.call("erp", "get_purchase_order", ...)──> McpConnection ──MCP──> SorServer (shared/mcp_servers)
```

Each boundary raises a typed error (`ModelUnavailableError`, `RetrievalUnavailableError`,
`EmptyRetrievalError`, `SystemOfRecordUnavailableError`, `ToolDeniedError`, ...) so the calling
node can take its declared degrade or escalate exit instead of letting a model improvise.
`faults.py` injects failures at exactly these boundaries, and `chaos.py` checks the exit taken.

## Tests

```bash
pytest shared            # tests for the shared platform
python -m shared.doctrine validate
```
