# `shared/tests/`: tests for the shared platform

Offline tests for the shared packages (55 tests at the time of writing). They
use the deterministic mock LLM and in-process MCP/A2A transports; `test_mcp_http.py` also
starts a FastMCP server over streamable HTTP in a local uvicorn thread. Repo-wide fixtures
(fault isolation, `kill_model`, `kill_retrieval`, `kill_sor`, `jailbreak`) come from the root
[`conftest.py`](../../conftest.py).

| File | What it does |
|---|---|
| [`test_a2a.py`](test_a2a.py) | Agent card round trip with tenant and trace propagation, schema rejection and guard refusal, typed error for an unavailable peer (3). |
| [`test_context.py`](test_context.py) | Parent/child chunk ids, RRF fusion, ACL and temporal filtering, sanitiser, budget packer and source map, typed empty/unavailable errors, cache scoping and invalidation, citation coverage (9). |
| [`test_doctrine_and_evals.py`](test_doctrine_and_evals.py) | Promotion gate over every project card, rejection of incomplete cards, harness metrics and thresholds, one card per project folder, README compliance matrix freshness (22). |
| [`test_llm.py`](test_llm.py) | Provider resolution order, deterministic mock responder, mock support for tool-calling agents (6). |
| [`test_mcp_gateway.py`](test_mcp_gateway.py) | Write tools require idempotency and default to dry-run, idempotent replay, allowlist/quota/schema errors, payload sanitising, retry then circuit breaker, LangChain tools through the gateway, a real stdio server via `langchain-mcp-adapters` (8). |
| [`test_mcp_http.py`](test_mcp_http.py) | Gateway calls over streamable HTTP to a server in its own uvicorn thread (the docker-compose topology) (1). |
| [`test_observability.py`](test_observability.py) | Graph, node and LLM spans carry thread id, identity, tokens and cost (1). |
| [`test_resilience.py`](test_resilience.py) | Retry with backoff, circuit breaker open/half-open, fallback chain, breaker skipping a dead primary, five-exit policy validation (5). |

Numbers in brackets are test counts from `pytest --collect-only`.

```bash
pytest shared/tests
pytest shared/tests/test_context.py -k acl
```
