# `shared/mcp_servers/`: MCP servers for systems of record

Model Context Protocol servers (official `mcp` SDK, FastMCP) that wrap each project's mock
systems of record. Projects pass in their in-memory backends; a production build would pass a
real client for the same contract. Tool surfaces are deliberately small and business-shaped
(`get_purchase_order`, `submit_purchase_order`), never a generic "run any query" tool.

| File | What it does |
|---|---|
| [`__init__.py`](__init__.py) | Public exports: `SorServer`, `SorUnavailableError`, the `BUILDERS` registry and the domain `build_*_server` functions. |
| [`__main__.py`](__main__.py) | Runs one domain server over stdio with a seeded demo backend: `python -m shared.mcp_servers oms` (for MCP Inspector, Claude Desktop or adapter tests). |
| [`demo_backends.py`](demo_backends.py) | Small seeded backends (`DemoOMS`, `DemoTicketing`, `DemoERP`, `DemoCRM`) so a domain server can run standalone. |
| [`domains.py`](domains.py) | Tool contracts per system of record: `build_oms_server`, `build_crm_server`, `build_ticketing_server`, `build_erp_server`, `build_suppliers_server`, `build_payments_server`, `build_ops_server`, `build_analytics_server`. Each registers only the tools the injected backend implements. |
| [`kit.py`](kit.py) | `SorServer` conventions: `@srv.read` tools have no side effects; `@srv.write` tools must take `idempotency_key` and `dry_run: bool = True`, and a replayed key returns the original result. Errors cross the wire as a JSON envelope (`error_envelope`); `SorUnavailableError` marks a retryable outage. |

## Design notes

- **Dry-run by default.** A confused caller previews a write instead of committing it; the
  agent must pass `dry_run=False` explicitly.
- **Idempotency keys are mandatory on writes**, so a retried or replayed call never moves money
  or creates a record twice.
- **Typed error envelopes** let the client-side gateway re-raise business errors as the same
  exception types (for example "PO not found") and treat outages as retryable.
- Industry projects (13-18) define their own `SorServer`s in their `sor.py`; they use the same
  kit and connect through `shared.tools.harness.connect_servers`.

## Try it

```bash
python -m shared.mcp_servers oms      # stdio server with the demo OMS backend
pytest shared/tests/test_mcp_gateway.py shared/tests/test_mcp_http.py
```
