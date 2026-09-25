"""Mock observability stack, runbooks and deploy system for two incident scenarios.

checkout-api: error-rate spike right after deploy v2.14.0 (DB connection pool exhausted).
search-api:   latency spike, no recent deploy, upstream Elasticsearch timeouts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

LOGS = {
    "checkout-api": [
        (
            "14:03:12",
            "ERROR",
            "HikariPool-1 - Connection is not available, request timed out "
            "after 30000ms (connection pool exhausted)",
        ),
        ("14:03:40", "ERROR", "POST /checkout 500 - could not acquire DB connection"),
        ("14:04:02", "WARN", "retrying payment authorization (attempt 2)"),
        ("13:55:00", "INFO", "health check ok"),
    ],
    "search-api": [
        ("09:12:01", "ERROR", "upstream elasticsearch timeout after 5000ms (cluster es-prod-2)"),
        ("09:12:30", "WARN", "circuit breaker half-open for es-prod-2"),
        ("09:00:00", "INFO", "health check ok"),
    ],
}
METRICS = {
    ("checkout-api", "error_rate"): {
        "baseline": 0.4,
        "current": 18.5,
        "unit": "%",
        "change_at": "14:03",
    },
    ("checkout-api", "latency_p99"): {
        "baseline": 320,
        "current": 2900,
        "unit": "ms",
        "change_at": "14:03",
    },
    ("search-api", "error_rate"): {
        "baseline": 0.2,
        "current": 1.1,
        "unit": "%",
        "change_at": "09:12",
    },
    ("search-api", "latency_p99"): {
        "baseline": 180,
        "current": 5200,
        "unit": "ms",
        "change_at": "09:12",
    },
}
DEPLOYS = {
    "checkout-api": [
        {
            "version": "v2.14.0",
            "at": "14:02",
            "by": "ci-bot",
            "change": "raise worker threads 32->128; DB pool unchanged (20)",
        },
        {"version": "v2.13.2", "at": "yesterday 16:40", "by": "ci-bot", "change": "copy fix"},
    ],
    "search-api": [],
}
RUNBOOKS = {
    "connection pool exhausted": "RB-DB-07: If pool exhaustion starts within 30 min of a "
    "deploy, roll back to the previous version, then right-size pool vs worker threads.",
    "elasticsearch timeout": "RB-SEARCH-02: Check cluster health; page the search-platform "
    "on-call. Do not roll back search-api for upstream timeouts.",
}


@dataclass
class DeploySystem:
    current: dict[str, str] = field(
        default_factory=lambda: {"checkout-api": "v2.14.0", "search-api": "v5.2.1"}
    )
    rollbacks: list[dict[str, Any]] = field(default_factory=list)
    _done: dict[str, dict[str, Any]] = field(default_factory=dict)

    def rollback(self, service: str, to_version: str, idempotency_key: str) -> dict[str, Any]:
        if idempotency_key in self._done:
            return {**self._done[idempotency_key], "replayed": True}
        rec = {"service": service, "from": self.current[service], "to": to_version}
        self.current[service] = to_version
        self._done[idempotency_key] = rec
        self.rollbacks.append(rec)
        return {**rec, "replayed": False}


@dataclass
class Systems:
    deploys: DeploySystem = field(default_factory=DeploySystem)
    tool_calls: list[str] = field(default_factory=list)


def seed_systems() -> Systems:
    return Systems()
