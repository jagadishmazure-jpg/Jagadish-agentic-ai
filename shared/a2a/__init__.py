"""A2A-style agent-to-agent task contract (shape follows the public A2A protocol).

* Agent card served at ``/.well-known/agent.json`` (name, url, version, capabilities,
  skills with input schemas) plus control-plane metadata.
* JSON-RPC 2.0 endpoint at ``/`` with ``message/send`` and ``tasks/get``; a ``message`` carries
  ``parts`` (``text`` / ``data``) and returns a ``Task`` with ``status`` + ``artifacts``.
* Every call propagates W3C ``traceparent`` and an ``X-Tenant-Id`` header; the server rejects
  payloads that fail the skill's input schema before any agent code runs.

``a2a_app`` builds the FastAPI server; ``A2AClient`` is the caller side (works over real HTTP
or in-process through Starlette's TestClient).
"""

from shared.a2a.client import A2AClient, A2AError, A2AUnavailableError
from shared.a2a.models import (
    AgentCard,
    AgentSkill,
    Artifact,
    CallContext,
    DataPart,
    Message,
    Task,
    TaskStatus,
    TextPart,
)
from shared.a2a.server import A2ARejection, Skill, a2a_app

__all__ = [
    "A2AClient",
    "A2AError",
    "A2ARejection",
    "A2AUnavailableError",
    "AgentCard",
    "AgentSkill",
    "Artifact",
    "CallContext",
    "DataPart",
    "Message",
    "Skill",
    "Task",
    "TaskStatus",
    "TextPart",
    "a2a_app",
]
