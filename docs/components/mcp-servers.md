# MCP servers for systems of record (`shared/mcp_servers/`)

FastMCP servers that wrap mock systems of record with small, business-shaped tool contracts.

**Sections:** [1. Purpose](#1-purpose) · [2. Architecture](#2-architecture) · [3. How it works](#3-how-it-works) · [4. Key files](#4-key-files) · [5. Code excerpts](#5-code-excerpts) · [6. Configuration](#6-configuration) · [7. Commands](#7-commands) · [8. Real output](#8-real-output) · [9. Tests and eval gates](#9-tests-and-eval-gates) · [10. Guardrails](#10-guardrails) · [11. Security and governance](#11-security-and-governance) · [12. Observability](#12-observability) · [13. Failure modes](#13-failure-modes) · [14. Mapping to Azure services](#14-mapping-to-azure-services) · [15. Limitations](#15-limitations) · [16. Interview talking points](#16-interview-talking-points) · [17. Adopt this](#17-adopt-this)

## 1. Purpose

Agents reach enterprise systems through narrow tools (`get_purchase_order`, `issue_refund`), never through a generic "run anything" endpoint. These servers define those contracts once and wrap whatever backend a project injects.

## 2. Architecture

```mermaid
flowchart LR
    B[project backend: mock OMS, ERP, CRM...] --> K[SorServer kit]
    K --> R[@srv.read tools]
    K --> W[@srv.write tools: idempotency_key + dry_run]
    R --> M[FastMCP]
    W --> M
    M -->|in-memory, stdio or HTTP| C[McpConnection in shared/tools]
```

## 3. How it works

1. `build_<domain>_server(backend)` registers the contract tools the backend implements.
2. Read tools have no side effects.
3. Write tools must declare `idempotency_key` and `dry_run=True` by default; a replayed key returns the first result.
4. Errors cross the wire as a JSON envelope (`error_type`, `message`, `retryable`) that the gateway turns back into typed errors.
5. Chaos faults `sor`, `sor:<server>` and `sor:<server>.<tool>` make a server behave like an outage.
6. `python -m shared.mcp_servers <domain>` runs a seeded server over stdio for MCP Inspector or other clients.

## 4. Key files

| File | What it holds |
|---|---|
| `shared/mcp_servers/kit.py` | `SorServer`, read/write decorators, error envelope, idempotency |
| `shared/mcp_servers/domains.py` | contract tools per system of record |
| `shared/mcp_servers/demo_backends.py` | seeded backends for standalone runs |
| `shared/mcp_servers/__main__.py` | stdio entry point |

## 5. Code excerpts

<!-- code: shared/mcp_servers/kit.py::error_envelope -->
```python
def error_envelope(exc: BaseException) -> str:
    retryable = isinstance(exc, ConnectionError | TimeoutError) or bool(
        getattr(exc, "retryable", False)
    )
    return json.dumps(
        {"error_type": type(exc).__name__, "message": str(exc), "retryable": retryable}
    )
```
<!-- /code -->

<!-- code: shared/mcp_servers/domains.py::build_ticketing_server -->
```python
def build_ticketing_server(backend: Any) -> SorServer:
    srv = SorServer("ticketing", "Service desk tickets (ServiceNow/Zendesk-like).", "Ticketing")
    if _has(backend, "list_tickets"):

        @srv.read
        def list_tickets(account: str) -> list[Json]:
            """Open and recent support tickets for an account."""
            return backend.list_tickets(account)

    if _has(backend, "get_ticket"):

        @srv.read
        def get_ticket(ticket_id: str) -> Json:
            """A ticket by id."""
            return backend.get_ticket(ticket_id)

    if _has(backend, "create_ticket"):

        @srv.write
        def create_ticket(
            queue: str,
            subject: str,
            summary: str,
            priority: str,
            idempotency_key: str,
            dry_run: bool = True,
        ) -> Json:
            """Create (route) a ticket into a queue."""
            if dry_run:
                return _preview("create_ticket", queue=queue, priority=priority)
            return backend.create_ticket(queue, subject, summary, priority, idempotency_key)

    return srv
```
<!-- /code -->

## 6. Configuration

| Knob | Effect |
|---|---|
| backend object | any object with methods named like the tools |
| `dry_run` (per call) | preview a write without side effects (default) |
| `idempotency_key` | dedupe writes |
| `CHAOS_FAULTS=sor:<server>` | simulate an outage |

## 7. Commands

```bash
python scripts/component_demos.py mcp       # tool contract of the ticketing server
python -m shared.mcp_servers ticketing        # stdio server for an MCP client
pytest shared/tests/test_mcp_gateway.py
```

## 8. Real output

Tools exposed by the ticketing server (name and parameters):

<!-- output: python scripts/component_demos.py mcp -->
```text
  create_ticket(queue, subject, summary, priority, idempotency_key, dry_run)
  get_ticket(ticket_id)
  list_tickets(account)
```
<!-- /output -->

## 9. Tests and eval gates

<!-- output: python -m pytest shared/tests/test_mcp_http.py -vv -p no:cacheprovider | grep -E 'PASSED|FAILED|SKIPPED' | sed -E 's/ +\[ *[0-9]+%\]//' -->
```text
shared/tests/test_mcp_http.py::test_gateway_over_streamable_http PASSED
```
<!-- /output -->

The gateway tests in `test_mcp_gateway.py` assert that write tools without `idempotency_key` and a `dry_run` default are rejected at registration.

## 10. Guardrails

- Writes are dry-run by default and idempotent.
- Small tool surface per system; no pass-through queries.
- Errors never leak stack traces, only the envelope.

## 11. Security and governance

- Each server is reached through the gateway with a named identity.
- Every write carries an idempotency key that doubles as an audit reference.

## 12. Observability

Calls are traced on the client side by the gateway; servers run inside the same process in tests, so spans share one trace.

## 13. Failure modes

| Failure | Behaviour |
|---|---|
| backend raises | envelope with `error_type`; gateway re-raises a typed error |
| outage (fault) | retryable `ConnectionError`; breaker counts it |
| duplicate write | original result returned, no second side effect |

## 14. Mapping to Azure services

| Piece | Azure service |
|---|---|
| server hosting | Azure Container Apps or Azure Functions (streamable HTTP transport) |
| front door | Azure API Management, which can expose and govern MCP servers |
| backend auth | managed identity to SAP, Dynamics or ServiceNow connectors |

## 15. Limitations

- Backends are mocks with seeded data.
- Idempotency results are kept in memory.

## 16. Interview talking points

- Business-shaped tools are the contract; the backend can change without touching agents.
- Dry-run by default turns a confused agent into a preview, not an incident.

## 17. Adopt this

1. Implement a backend class with methods named like the contract tools.
2. Call the matching `build_<domain>_server(backend)` or write your own with `SorServer`.
3. Host it over streamable HTTP and point `McpConnection` at the URL.
4. Add a gateway allow-list entry per agent that needs it.
