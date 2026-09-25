# `shared/a2a/`: A2A-style agent-to-agent contract

A small implementation of an A2A-shaped task contract, used by project 12 (agent control plane)
and project 18 (capacity peer agent). Each agent is one FastAPI app that serves an agent card at
`/.well-known/agent.json` and a JSON-RPC 2.0 endpoint with `message/send` and `tasks/get`.
Every call carries a W3C `traceparent` and an `X-Tenant-Id` header, and inputs are validated
against the skill's schema before any agent code runs. The shape follows the public A2A
protocol; it is a subset, not a full SDK.

| File | What it does |
|---|---|
| [`__init__.py`](__init__.py) | Public exports (`a2a_app`, `A2AClient`, models, errors) and a summary of the contract. |
| [`client.py`](client.py) | `A2AClient`: fetches agent cards and sends tasks over any httpx-style client (a real `httpx.Client` or an in-process ASGI transport in tests), propagating traceparent and tenant. Raises `A2AUnavailableError` when the peer is down so callers can degrade, and `A2AError` on rejection. |
| [`models.py`](models.py) | Pydantic models for the contract: `TextPart`, `DataPart`, `Message`, `TaskStatus`, `Artifact`, `Task`, `AgentSkill`, `AgentCapabilities`, `AgentCard` (with control-plane metadata such as owner, side effects, budgets, eval scores) and `CallContext` (caller, tenant, trace). |
| [`server.py`](server.py) | `a2a_app(card, skills, guard=...)` builds the FastAPI app for one agent. `Skill` pairs an input schema with a handler; an optional `guard` (policy engine, kill switch, registry gate) runs before schema validation and can refuse with `A2ARejection`. |

## Design notes

- The guard runs first, so an unregistered or killed caller is refused before the payload is
  even parsed; schema failures are rejected before the handler runs.
- Peer outages surface as a typed `A2AUnavailableError`, which the calling graph maps to its
  degrade exit (for example project 18 keeps drafting the customer notice when the capacity
  agent refuses).

Tests: [`shared/tests/test_a2a.py`](../tests/test_a2a.py) (3 tests), run with
`pytest shared/tests/test_a2a.py`.
