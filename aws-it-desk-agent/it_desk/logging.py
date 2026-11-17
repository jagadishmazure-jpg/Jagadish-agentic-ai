"""Structured logs for the IT desk agent.

The container always writes one JSON object per question to stdout, which the ECS
``awslogs`` driver and AgentCore Runtime ship to CloudWatch. ``IT_DESK_LOG_MODE=cloudwatch``
also calls ``PutLogEvents`` when a log group is set. Tests use the in-memory sink.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from typing import Any, Protocol


def question_hash(question: str) -> str:
    return hashlib.sha256(question.encode()).hexdigest()[:16]


def event(
    *,
    provider: str,
    model: str,
    status: str,
    latency_ms: int,
    citations: list[str],
    question: str,
) -> dict[str, Any]:
    """One log record. The question text stays out of the record; only a short hash is kept."""
    return {
        "service": "it-desk-playbook",
        "provider": provider,
        "model": model,
        "status": status,
        "latency_ms": latency_ms,
        "citations": citations,
        "question_sha256": question_hash(question),
    }


class LogSink(Protocol):
    def emit(self, record: dict[str, Any]) -> str: ...


class MemorySink:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def emit(self, record: dict[str, Any]) -> str:
        line = json.dumps(record, sort_keys=True)
        self.events.append(record)
        print(line, file=sys.stdout, flush=True)
        return line


class CloudWatchSink:
    """PutLogEvents into an existing group. The stream is created on the first record."""

    def __init__(self, client: Any, group: str, stream: str):
        self.client = client
        self.group = group
        self.stream = stream
        self._ready = False

    def emit(self, record: dict[str, Any]) -> str:
        line = json.dumps(record, sort_keys=True)
        if not self._ready:
            try:
                self.client.create_log_stream(logGroupName=self.group, logStreamName=self.stream)
            except Exception as exc:
                if "ResourceAlreadyExistsException" not in type(exc).__name__:
                    raise
            self._ready = True
        self.client.put_log_events(
            logGroupName=self.group,
            logStreamName=self.stream,
            logEvents=[{"timestamp": int(time.time() * 1000), "message": line}],
        )
        print(line, file=sys.stdout, flush=True)
        return line


def build_sink(env: dict[str, str] | None = None, *, client: Any = None) -> LogSink:
    env = dict(os.environ) if env is None else env
    group = env.get("IT_DESK_LOG_GROUP", "").strip()
    if env.get("IT_DESK_LOG_MODE", "").strip().lower() == "cloudwatch" and group:
        if client is None:
            try:
                import boto3
            except ImportError as exc:  # pragma: no cover - depends on the aws extra
                raise RuntimeError("boto3 is not installed. Run: uv sync --extra aws") from exc
            region = env.get("AWS_REGION") or env.get("AWS_DEFAULT_REGION") or "us-east-1"
            client = boto3.client("logs", region_name=region)
        stream = env.get("IT_DESK_LOG_STREAM", "").strip() or "it-desk-playbook"
        return CloudWatchSink(client, group, stream)
    return MemorySink()
