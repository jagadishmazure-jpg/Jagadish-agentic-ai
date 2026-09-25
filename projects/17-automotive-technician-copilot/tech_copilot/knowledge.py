"""Service knowledge: technical service bulletins (TSBs) and wiring-diagram images.

* Temporal: each TSB carries its issue date (valid_from) and, when retired, valid_to;
  retrieval runs as-of the repair date.
* Supersession: a TSB replaced by a newer one is dropped whenever its successor is valid on
  the repair date, even if the old record's valid_to was never filled in (a common data
  quality gap) - the current TSB wins.
* Applicability: model, model years, engine and build-date window come from the TSB registry
  and are checked against the decoded VIN.
* Multimodal: wiring diagrams are indexed by caption (standing in for a vision model) with
  their image id; the answer cites image ids, and applicability (model years, harness rev)
  is checked the same way as TSBs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from shared.context import (
    Budget,
    ContextBuilder,
    Document,
    KnowledgeCorpus,
    Principal,
    SemanticCache,
    chunk_document,
)

D = date.fromisoformat
TECH = frozenset({"technician"})


@dataclass(frozen=True)
class Applies:
    model: str
    years: tuple[int, int]
    engine: str = "*"
    built_from: date | None = None
    parts: tuple[str, ...] = ()
    op_code: str = ""
    supersedes: str = ""


REGISTRY: dict[str, Applies] = {
    "TSB-21-044": Applies(
        "Arden X5", (2021, 2022), "2.0T", parts=("11-4455-A",), op_code="COOL-PUMP-R"
    ),
    "TSB-23-107": Applies(
        "Arden X5",
        (2021, 2023),
        "2.0T",
        parts=("11-4455-C", "11-4460-B"),
        op_code="COOL-PUMP-R",
        supersedes="TSB-21-044",
    ),
    "TSB-22-061": Applies(
        "Arden X5", (2022, 2023), built_from=D("2021-11-01"), op_code="INFO-SW-UPD"
    ),
    "TSB-20-009": Applies("Arden X5", (2020, 2021), parts=("33-1200-D",), op_code="WIN-REG-R"),
    "TSB-24-012": Applies(
        "Arden C3", (2024, 2025), "EV", parts=("77-0901-A",), op_code="CHG-DOOR-R"
    ),
    "IMG-WD-X5-COOL-B": Applies("Arden X5", (2021, 2023), "2.0T", op_code="COOL-PUMP-R"),
    "IMG-WD-X5-COOL-A": Applies("Arden X5", (2019, 2020), "2.0T", op_code="COOL-PUMP-R"),
    "IMG-WD-C3-PORT": Applies("Arden C3", (2024, 2025), "EV", op_code="CHG-DOOR-R"),
}


def _tsb(doc_id: str, title: str, body: str, issued: str, retired: str | None = None) -> Document:
    return Document(
        doc_id,
        title,
        f"# {title}\n{doc_id}: {body}",
        groups=TECH,
        kind="tsb",
        valid_from=D(issued),
        valid_to=D(retired) if retired else None,
        version=issued,
        owner="service-engineering",
    )


def _img(image_id: str, caption: str) -> Document:
    return Document(
        image_id,
        f"Wiring diagram {image_id}",
        f"# Diagram\n{image_id}: {caption}",
        groups=TECH,
        kind="image",
        owner="service-engineering",
    )


DOCS = [
    _tsb(
        "TSB-21-044",
        "Coolant pump seep - Arden X5 2.0T",
        "Coolant seep at the pump weep hole with P0128. Replace coolant pump with part "
        "11-4455-A. Torque pump bolts to 25 Nm.",
        "2021-09-01",
    ),  # valid_to never filled in
    _tsb(
        "TSB-23-107",
        "Coolant pump seep - revised pump (supersedes TSB-21-044)",
        "Coolant seep at the pump weep hole with P0128. Replace coolant pump with revised part "
        "11-4455-C and gasket 11-4460-B. Torque pump bolts to 32 Nm in a cross pattern. "
        "Pressure-test the cooling system to 1.4 bar.",
        "2023-04-15",
    ),
    _tsb(
        "TSB-22-061",
        "Infotainment reboot loop - software 4.2.1",
        "Infotainment head unit reboots repeatedly. Reflash head unit software to 4.2.1 with "
        "the dealer tool. No parts required.",
        "2022-08-01",
    ),
    _tsb(
        "TSB-20-009",
        "Window regulator noise - Arden X5",
        "Grinding noise from the front window regulator. Replace regulator 33-1200-D.",
        "2020-05-01",
        "2022-12-31",
    ),
    _tsb(
        "TSB-24-012",
        "Charge port door will not open - Arden C3",
        "Charge port door fails to open with fault B1A42. Replace door actuator 77-0901-A.",
        "2024-02-01",
    ),
    _img(
        "IMG-WD-X5-COOL-B",
        "Arden X5 2021-2023 2.0T coolant pump and thermostat circuit, "
        "harness revision B: connector C214 pin 3 is 12V feed, pin 5 ground, pump driver "
        "signal on pin 2.",
    ),
    _img(
        "IMG-WD-X5-COOL-A",
        "Arden X5 2019-2020 2.0T coolant pump circuit, harness revision "
        "A: connector C210 pin 1 is 12V feed, pin 4 ground.",
    ),
    _img(
        "IMG-WD-C3-PORT",
        "Arden C3 2024-2025 charge port door actuator circuit: connector "
        "C880 pin 2 actuator +, pin 6 actuator -, LIN on pin 4.",
    ),
]


def corpus() -> KnowledgeCorpus:
    return KnowledgeCorpus(
        "service-knowledge",
        [c for d in DOCS for c in chunk_document(d)],
        synonyms={
            "leak": ["seep", "coolant"],
            "reboot": ["restart", "loop"],
            "wiring": ["connector", "circuit", "diagram"],
        },
        refresh_sla="TSB publication feed, hourly",
    )


def principal() -> Principal:
    return Principal.of("mi-tech-copilot", "technician")


def builder() -> ContextBuilder:
    return ContextBuilder(
        corpus(),
        budget=Budget(policy=900, facts=300, history=0, tool_io=300),
        cache=SemanticCache(),
    )


def applies(doc_id: str, v: dict[str, Any]) -> bool:
    a = REGISTRY.get(doc_id)
    if a is None or a.model != v["model"] or not a.years[0] <= v["year"] <= a.years[1]:
        return False
    if a.engine != "*" and a.engine != v["engine"]:
        return False
    return not (a.built_from and D(v["build_date"]) < a.built_from)


def current_only(doc_ids: list[str], valid: set[str]) -> tuple[list[str], list[str]]:
    """Drop any document superseded by another document that is valid on the repair date."""
    superseded = {
        REGISTRY[d].supersedes for d in valid if REGISTRY.get(d) and REGISTRY[d].supersedes
    }
    keep = [d for d in doc_ids if d not in superseded]
    return keep, [d for d in doc_ids if d in superseded]
