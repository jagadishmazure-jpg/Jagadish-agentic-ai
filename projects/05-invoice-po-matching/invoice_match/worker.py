"""Intake worker: the durable boundary around one graph run.

The fetch_erp node retries ERP outages with backoff (RetryPolicy). If the ERP is still down
after the last attempt the error propagates - it is never misfiled as a business exception -
and the worker parks the invoice for redelivery instead of losing it (retry exit).
"""

from __future__ import annotations

from typing import Any

from invoice_match.erp import ERPUnavailableError
from shared.resilience import exit_record


def process(
    graph: Any, raw_text: str, parked: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    try:
        return graph.invoke({"raw_text": raw_text})
    except ERPUnavailableError as exc:
        item = {"raw_text": raw_text, "reason": str(exc)}
        if parked is not None:
            parked.append(item)
        return {
            "result": {"status": "parked", "route_to": "intake_retry_queue", "reason": str(exc)},
            "exits": [exit_record("fetch_erp", "retry", f"ERP unavailable after retries: {exc}")],
            "trace": ["fetch_erp", "parked"],
        }
