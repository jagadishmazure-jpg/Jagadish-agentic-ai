"""Azure AI Content Safety Prompt Shields, behind a flag, on top of the offline regex screen.

Which path runs:

* **Offline (default, and the only path tests and CI exercise):** the regex screen alone. Nothing
  here is imported over the network and no request is sent.
* **Prompt Shields (opt-in):** set ``PROMPT_SHIELDS=1`` and ``AZURE_CONTENT_SAFETY_ENDPOINT``.
  The regex screen still runs first; text it let through is then sent, five documents per
  request, to
  ``POST {endpoint}/contentsafety/text:shieldPrompt?api-version=2024-09-01`` with a Microsoft
  Entra bearer token from ``DefaultAzureCredential`` (managed identity in Azure, ``az login``
  locally; no keys). Documents the service flags are withheld.
* **Fail closed:** if the flag is on and the service cannot be reached or answers with an error,
  the whole batch is treated as flagged and withheld, so an outage can cost context but cannot let
  unscreened text through.

Ported from the azure-agent-platform Content Safety gate; the request shape follows the Prompt
Shields REST reference.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

FLAG = "PROMPT_SHIELDS"
ENDPOINT_ENV = "AZURE_CONTENT_SAFETY_ENDPOINT"
API_VERSION = "2024-09-01"
SCOPE = "https://cognitiveservices.azure.com/.default"
BATCH = 5  # documents per shieldPrompt request
MAX_CHARS = 10_000  # per document, matching the service's text limit
SHIELDED = "[removed: Prompt Shields flagged an indirect prompt attack] "

Transport = Callable[[str, dict[str, str], dict[str, str], dict[str, Any]], dict[str, Any]]


def enabled(env: Mapping[str, str] | None = None) -> bool:
    """True only when the flag is ``1`` and an endpoint is configured."""
    env = os.environ if env is None else env
    return env.get(FLAG, "") == "1" and bool(env.get(ENDPOINT_ENV, ""))


def _httpx_post(url: str, params: dict[str, str], headers: dict[str, str], body: dict[str, Any]):
    import httpx

    resp = httpx.post(url, params=params, headers=headers, json=body, timeout=10)
    resp.raise_for_status()
    return resp.json()


@dataclass
class PromptShields:
    """Thin client for ``text:shieldPrompt``. ``credential`` and ``transport`` are injectable."""

    endpoint: str
    credential: Any = None
    transport: Transport | None = None  # None: real HTTPS via httpx
    calls: int = 0
    errors: int = 0
    _token: Callable[[], str] | None = field(default=None, repr=False)

    def _bearer(self) -> str:
        if self._token is None:
            cred = self.credential
            if cred is None:
                from azure.identity import DefaultAzureCredential

                cred = self.credential = DefaultAzureCredential()
            from azure.identity import get_bearer_token_provider

            self._token = get_bearer_token_provider(cred, SCOPE)
        return self._token()

    def analyze(self, user_prompt: str, documents: Sequence[str]) -> tuple[bool, list[bool]]:
        """One request: (user prompt attacked?, attacked flag per document)."""
        self.calls += 1
        body = {
            "userPrompt": user_prompt[:MAX_CHARS],
            "documents": [d[:MAX_CHARS] for d in documents],
        }
        send = self.transport or _httpx_post
        out = send(
            f"{self.endpoint.rstrip('/')}/contentsafety/text:shieldPrompt",
            {"api-version": API_VERSION},
            {"Authorization": f"Bearer {self._bearer()}"},
            body,
        )
        docs = [bool(d.get("attackDetected")) for d in out.get("documentsAnalysis", [])]
        if len(docs) != len(documents):
            raise ValueError("shieldPrompt returned a different number of document results")
        return bool(out.get("userPromptAnalysis", {}).get("attackDetected")), docs

    def documents_attacked(self, documents: Sequence[str]) -> list[bool]:
        """Flag per document, batched; a failed batch counts as attacked (fail closed)."""
        flags: list[bool] = []
        for i in range(0, len(documents), BATCH):
            batch = list(documents[i : i + BATCH])
            try:
                flags += self.analyze("", batch)[1]
            except Exception:  # network, HTTP or shape error: withhold the batch
                self.errors += 1
                flags += [True] * len(batch)
        return flags


_DEFAULT: dict[str, PromptShields | None] = {"client": None}


def configure(client: PromptShields | None) -> None:
    """Install a client (tests pass one with a fake transport); ``None`` resets to the env."""
    _DEFAULT["client"] = client


def shield(texts: Sequence[str], env: Mapping[str, str] | None = None) -> list[bool] | None:
    """Prompt Shields flags for ``texts``, or ``None`` when the flag is off (regex only)."""
    client = _DEFAULT["client"]
    if client is None:
        if not enabled(env):
            return None
        e = os.environ if env is None else env
        client = _DEFAULT["client"] = PromptShields(e[ENDPOINT_ENV])
    return client.documents_attacked(list(texts)) if texts else []


def _leaves(value: Any, out: list[str]) -> None:
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, dict):
        for v in value.values():
            _leaves(v, out)
    elif isinstance(value, list):
        for v in value:
            _leaves(v, out)


def _swap(value: Any, flags: list[bool], replacement: str) -> Any:
    if isinstance(value, str):
        return replacement if flags.pop(0) else value
    if isinstance(value, dict):
        return {k: _swap(v, flags, replacement) for k, v in value.items()}
    if isinstance(value, list):
        return [_swap(v, flags, replacement) for v in value]
    return value


def shield_payload(value: Any, replacement: str, skip: str | None = None) -> tuple[Any, int]:
    """Run Prompt Shields over every string leaf of a JSON-like payload.

    Returns the payload with flagged leaves replaced and the number replaced. With the flag off
    this is a no-op that returns ``(value, 0)``. Leaves equal to ``skip`` (text the regex screen
    already withheld) are not sent.
    """
    leaves: list[str] = []
    _leaves(value, leaves)
    todo = [s for s in leaves if s.strip() and s != skip]
    flags = shield(todo)
    if not flags:
        return value, 0
    it = iter(flags)
    per_leaf = [next(it) if (s.strip() and s != skip) else False for s in leaves]
    return _swap(value, list(per_leaf), replacement), sum(per_leaf)
