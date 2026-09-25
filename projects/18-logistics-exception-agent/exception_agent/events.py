"""Event Hubs stand-in: partitioned milestone stream, consumer group, checkpoints.

* ``EventHub.send(body, partition_key)`` appends to a partition picked by a stable hash of the
  key (shipment id), so events for one shipment stay ordered.
* ``Consumer`` reads from the last checkpoint per (consumer group, partition). This is
  at-least-once delivery: a crash before ``checkpoint`` replays events.
* ``MilestoneTrigger`` validates each event (malformed -> dead-letter), detects slipped
  milestones and runs the exception graph once per (shipment, milestone). The dedupe set is
  stored with the checkpoint, so replays never trigger twice.
"""

from __future__ import annotations

import zlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

SLIP_THRESHOLD_MIN = 120


class MilestoneEvent(BaseModel):
    event_id: str
    shipment_id: str
    tenant: str
    milestone: str
    planned_at: datetime
    actual_at: datetime | None = None
    status: Literal["on_time", "late", "missed"] = "on_time"
    source: Literal["edi", "driver_app", "inferred"] = "edi"
    confidence: float = 0.97


@dataclass
class EventHub:
    partitions: int = 2
    log: list[list[dict[str, Any]]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.log = [[] for _ in range(self.partitions)]

    def send(self, body: dict[str, Any], partition_key: str) -> tuple[int, int]:
        p = zlib.crc32(partition_key.encode()) % self.partitions
        self.log[p].append({"offset": len(self.log[p]), "body": body})
        return p, len(self.log[p]) - 1


@dataclass
class CheckpointStore:
    offsets: dict[tuple[str, int], int] = field(default_factory=dict)
    processed: set[str] = field(default_factory=set)


@dataclass
class Consumer:
    hub: EventHub
    group: str
    store: CheckpointStore

    def receive(self, max_events: int = 100) -> list[tuple[int, dict[str, Any]]]:
        out = []
        for p, events in enumerate(self.hub.log):
            start = self.store.offsets.get((self.group, p), -1) + 1
            out += [(p, e) for e in events[start : start + max_events]]
        return out

    def checkpoint(self, partition: int, offset: int) -> None:
        self.store.offsets[(self.group, partition)] = offset


def slipped(ev: MilestoneEvent) -> bool:
    if ev.status == "missed":
        return True
    if ev.actual_at is None:
        return False
    return (ev.actual_at - ev.planned_at).total_seconds() / 60 >= SLIP_THRESHOLD_MIN


@dataclass
class MilestoneTrigger:
    consumer: Consumer
    run: Callable[[dict[str, Any]], dict[str, Any]]
    dead_letter: list[dict[str, Any]] = field(default_factory=list)

    def poll(self, crash_after: int | None = None) -> list[dict[str, Any]]:
        """Process a batch; ``crash_after`` simulates a crash before the next checkpoint."""
        results = []
        for n, (p, e) in enumerate(self.consumer.receive()):
            if crash_after is not None and n >= crash_after:
                break
            try:
                ev = MilestoneEvent.model_validate(e["body"])
            except ValidationError as exc:
                self.dead_letter.append(
                    {"partition": p, "offset": e["offset"], "error": str(exc).splitlines()[0]}
                )
                self.consumer.checkpoint(p, e["offset"])
                continue
            key = f"{ev.shipment_id}:{ev.milestone}"
            if slipped(ev) and key not in self.consumer.store.processed:
                results.append(
                    self.run(
                        {
                            "kind": "slip",
                            "shipment_id": ev.shipment_id,
                            "tenant": ev.tenant,
                            "event": ev.model_dump(mode="json"),
                        }
                    )
                )
                self.consumer.store.processed.add(key)
            self.consumer.checkpoint(p, e["offset"])
        return results
