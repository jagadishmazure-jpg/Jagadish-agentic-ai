# `shared/tools/`: MCP client side and the tool gateway

How agents reach systems of record. `McpConnection` holds a real MCP client session (in-memory,
stdio or streamable HTTP) on a background event loop and exposes blocking calls to synchronous
graph nodes. `ToolGateway` is the only door between an agent and those connections: it is
scoped to one agent identity and enforces the allowlist, quotas, timeouts, circuit breakers,
retries, payload schema validation and sanitising, and emits an OTel span per call.

| File | What it does |
|---|---|
| [`__init__.py`](__init__.py) | Re-exports `McpConnection`, `ToolGateway`, the gateway error types and the `connect_*` helpers. |
| [`connection.py`](connection.py) | `McpConnection`: sync wrapper with timeouts around an MCP `ClientSession` over the in-memory transport, stdio or streamable HTTP; `payload` unwraps results and `error_info` decodes error envelopes. |
| [`gateway.py`](gateway.py) | `ToolGateway` (`call`, `scoped`, `langchain_tools`, `stats`, `last`) and typed errors: `ToolDeniedError` (not on the allowlist), `QuotaExceededError`, `SchemaViolationError` (returned payload failed validation), `RemoteToolError`, `SystemOfRecordUnavailableError`, `ToolTimeoutError`. `CallRecord` is the per-call audit entry. |
| [`harness.py`](harness.py) | One-liner wiring: `connect_backends` (mock backends to in-memory MCP connections), `connect_servers` (project-owned `SorServer`s), `connect_urls` (remote servers over HTTP) and `load_stdio_tools_with_adapters` (load tools via `langchain-mcp-adapters`). |

## Typical wiring

```python
def build_gateway(erp: MockERP) -> ToolGateway:
    return ToolGateway(
        AGENT,  # "invoice-matcher"
        IDENTITY,  # "mi-ap-invoice-matcher"
        connect_backends({"erp": ErpBackend(erp)}),  # in-process MCP transport
        ALLOW,  # exact server.tool allowlist
        schemas={"erp.get_purchase_order": PurchaseOrder},
        error_types={"PONotFoundError": PONotFoundError, "POClosedError": POClosedError},
        timeout_s=5.0,
        retry=None,  # the fetch_erp node's RetryPolicy owns retries
    )
```

Nodes then call `gateway.call("erp", "get_purchase_order", po_number=...)`.
This is the real `build_gateway` from
[`projects/05-invoice-po-matching/invoice_match/sor.py`](../../projects/05-invoice-po-matching/invoice_match/sor.py).

## Design notes

- Agents never hold connection strings or broad credentials; they hold a gateway scoped to
  their identity. Several projects (for example 09, 10, 11 and 13-18) split reads and writes
  across separate identities, each with its own gateway.
- Returned payloads are treated as untrusted: they are schema-validated and string fields are
  sanitised before a model sees them.
- Outages raise `SystemOfRecordUnavailableError`, which nodes map to degrade or escalate exits.

Tests: [`shared/tests/test_mcp_gateway.py`](../tests/test_mcp_gateway.py),
[`shared/tests/test_mcp_http.py`](../tests/test_mcp_http.py).
