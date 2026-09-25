"""Doctrine card schema, validator (promotion gate) and renderer.

A project is 'still a demo' unless its card names: plane dependencies, systems of record /
semantic models, retrieval corpus + ACL, MCP / A2A contracts, stop conditions, a five-exit
failure playbook covering every graph node, chaos scenarios, an eval set with thresholds and
current passing scores, an owner, KPIs with targets, a maturity level and an ROI sketch.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from shared.evals.harness import METRICS, check_thresholds, load_golden
from shared.resilience import EXITS, FiveExitPolicy, exit_table

ROOT = Path(__file__).resolve().parents[2]
MIN_GOLDEN_CASES = 10
PLANES = ("experience", "agent", "knowledge", "data")


class _Strict(BaseModel):
    model_config = {"extra": "forbid"}


class Maturity(_Strict):
    level: int = Field(ge=1, le=5)
    rationale: str = Field(min_length=10)
    next_rung: str = Field(min_length=10)


class Kpi(_Strict):
    name: str
    target: str
    measure: str


class SystemOfRecord(_Strict):
    name: str
    kind: Literal["api", "semantic_model", "mcp", "event_stream", "document_store"]
    contract: str
    access: Literal["read", "write", "read_write"]


class Corpus(_Strict):
    name: str
    owner: str
    acl: str
    temporal: str
    refresh_sla: str
    sensitivity: str


class Knowledge(_Strict):
    corpora: list[Corpus] = Field(default_factory=list)
    notes: str = ""

    @model_validator(mode="after")
    def _justify_empty(self) -> Knowledge:
        if not self.corpora and len(self.notes) < 20:
            raise ValueError("no retrieval corpus: explain why in knowledge.notes")
        return self


class Contracts(_Strict):
    mcp: list[str] = Field(default_factory=list)
    a2a: list[str] = Field(default_factory=list)
    notes: str = ""

    @model_validator(mode="after")
    def _some_contract(self) -> Contracts:
        if not (self.mcp or self.a2a) and len(self.notes) < 20:
            raise ValueError("no MCP/A2A contracts: explain why in contracts.notes")
        return self


class Identity(_Strict):
    identity: str
    allow: list[str]


class ChaosScenario(_Strict):
    fault: str
    node: str
    exit: str
    invariant: str

    @field_validator("exit")
    @classmethod
    def _exit(cls, v: str) -> str:
        if v not in EXITS:
            raise ValueError(f"exit must be one of {EXITS}")
        return v

    @field_validator("fault")
    @classmethod
    def _fault(cls, v: str) -> str:
        base = v.split("*")[0]
        if base != "jailbreak" and base.split(":")[0] not in ("model", "retrieval", "sor"):
            raise ValueError("fault must be model[:x] | retrieval[:x] | sor[:x] | jailbreak")
        return v


class EvalSpec(_Strict):
    golden: str
    suite: str
    thresholds: dict[str, str]

    @field_validator("thresholds")
    @classmethod
    def _known(cls, v: dict[str, str]) -> dict[str, str]:
        unknown = set(v) - set(METRICS)
        if unknown:
            raise ValueError(f"unknown metrics {unknown}")
        for req in ("task_success", "policy_violation_rate"):
            if req not in v:
                raise ValueError(f"threshold for {req} is required")
        return v


class DoctrineCard(_Strict):
    project: str
    title: str
    owner: str
    industry: str
    summary: str
    maturity: Maturity
    kpis: list[Kpi] = Field(min_length=1)
    roi: str = Field(min_length=40)
    planes: dict[str, str]
    systems_of_record: list[SystemOfRecord] = Field(min_length=1)
    knowledge: Knowledge
    contracts: Contracts
    identities: list[Identity] = Field(default_factory=list)
    stop_conditions: list[str] = Field(min_length=1)
    graph: str
    failure_playbook: list[dict[str, str]] = Field(min_length=1)
    chaos: list[ChaosScenario] = Field(min_length=3)
    eval: EvalSpec

    @field_validator("planes")
    @classmethod
    def _planes(cls, v: dict[str, str]) -> dict[str, str]:
        missing = [p for p in PLANES if not str(v.get(p, "")).strip()]
        if missing:
            raise ValueError(f"plane dependencies missing: {missing}")
        return v

    @field_validator("failure_playbook")
    @classmethod
    def _rows(cls, v: list[dict[str, str]]) -> list[dict[str, str]]:
        for row in v:
            FiveExitPolicy.from_dict(row)
        return v

    @model_validator(mode="after")
    def _chaos_nodes(self) -> DoctrineCard:
        nodes = {r["node"] for r in self.failure_playbook}
        bad = [c.node for c in self.chaos if c.node not in nodes]
        if bad:
            raise ValueError(f"chaos scenarios reference nodes without a five-exit row: {bad}")
        kinds = {c.fault.split(":")[0].split("*")[0] for c in self.chaos}
        need = (
            {"model", "jailbreak"}
            | ({"retrieval"} if self.knowledge.corpora else set())
            | ({"sor"} if self.contracts.mcp else set())
        )
        if need - kinds:
            raise ValueError(f"chaos must cover {sorted(need - kinds)}")
        return self

    @property
    def policies(self) -> list[FiveExitPolicy]:
        return [FiveExitPolicy.from_dict(r) for r in self.failure_playbook]


def load_card(path: Path) -> DoctrineCard:
    return DoctrineCard.model_validate(yaml.safe_load(path.read_text()))


def project_dirs() -> list[Path]:
    return sorted(p.parent for p in (ROOT / "projects").glob("*/doctrine.yaml"))


def ensure_path(project_dir: Path) -> None:
    for p in (str(ROOT), str(project_dir)):
        if p not in sys.path:
            sys.path.insert(0, p)


def resolve(ref: str) -> Any:
    mod, _, attr = ref.partition(":")
    return getattr(importlib.import_module(mod), attr)


def graph_nodes(card: DoctrineCard, project_dir: Path) -> set[str]:
    ensure_path(project_dir)
    graph = resolve(card.graph)()
    return {n for n in graph.get_graph().nodes if not n.startswith("__")}


def scores_path(project_dir: Path) -> Path:
    return project_dir / "evals" / "scores.json"


def validate_project(project_dir: Path, check_scores: bool = True) -> list[str]:
    """Promotion gate. Returns a list of problems (empty == promotable)."""
    try:
        card = load_card(project_dir / "doctrine.yaml")
    except (ValidationError, ValueError, FileNotFoundError) as exc:
        return [f"doctrine.yaml invalid: {exc}"]
    problems = []
    if card.project != project_dir.name:
        problems.append(f"project field {card.project} != folder {project_dir.name}")
    nodes = graph_nodes(card, project_dir)
    covered = {r["node"] for r in card.failure_playbook}
    if missing := sorted(nodes - covered):
        problems.append(f"graph nodes without a five-exit row: {missing}")
    if extra := sorted(covered - nodes):
        problems.append(f"five-exit rows for nodes not in the graph: {extra}")
    golden = project_dir / card.eval.golden
    if not golden.exists():
        problems.append(f"golden set missing: {golden}")
    elif len(load_golden(golden)) < MIN_GOLDEN_CASES:
        problems.append(f"golden set has < {MIN_GOLDEN_CASES} cases")
    try:
        resolve(card.eval.suite)
    except (ImportError, AttributeError) as exc:
        problems.append(f"eval suite not importable: {exc}")
    if check_scores:
        sp = scores_path(project_dir)
        if not sp.exists():
            problems.append("no eval scores: run `python -m evals`")
        else:
            scores = json.loads(sp.read_text())
            problems += [
                f"eval gate: {v}" for v in check_thresholds(scores["metrics"], card.eval.thresholds)
            ]
    return problems


# ------------------------------------------------------------------------------ render
def _fmt_metric(name: str, v: float | None) -> str:
    if v is None:
        return "n/a"
    return f"${v:.5f}" if name == "cost_per_task" else f"{v:.2f}"


def render_card(project_dir: Path) -> str:
    card = load_card(project_dir / "doctrine.yaml")
    sp = scores_path(project_dir)
    scores = json.loads(sp.read_text()) if sp.exists() else None
    L: list[str] = [
        f"# Doctrine card: {card.title}",
        "",
        "<!-- GENERATED from doctrine.yaml + evals/scores.json by "
        "`python -m shared.doctrine render`. Do not edit by hand. -->",
        "",
        f"> {card.summary}",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Owner | {card.owner} |",
        f"| Industry | {card.industry} |",
        f"| Maturity | **Level {card.maturity.level}**: {card.maturity.rationale} |",
        f"| Next rung | {card.maturity.next_rung} |",
        f"| Graph | `{card.graph}` |",
        "",
        "## Plane dependencies",
        "",
        "| Plane | Dependency |",
        "|---|---|",
        *[f"| {p.title()} | {card.planes[p]} |" for p in PLANES],
        "",
        "## Systems of record and semantic models",
        "",
        "| System | Kind | Contract | Access |",
        "|---|---|---|---|",
        *[f"| {s.name} | {s.kind} | `{s.contract}` | {s.access} |" for s in card.systems_of_record],
        "",
        "## Knowledge: retrieval corpora and ACL",
        "",
    ]
    if card.knowledge.corpora:
        L += [
            "| Corpus | Owner | ACL | Temporal validity | Refresh SLA | Sensitivity |",
            "|---|---|---|---|---|---|",
            *[
                f"| {c.name} | {c.owner} | {c.acl} | {c.temporal} | {c.refresh_sla} | "
                f"{c.sensitivity} |"
                for c in card.knowledge.corpora
            ],
        ]
    if card.knowledge.notes:
        L += ["", card.knowledge.notes]
    L += ["", "## MCP / A2A contracts", ""]
    L += [f"- MCP `{m}`" for m in card.contracts.mcp] + [f"- A2A `{a}`" for a in card.contracts.a2a]
    if card.contracts.notes:
        L += ["", card.contracts.notes]
    if card.identities:
        L += [
            "",
            "**Tool identities (gateway allowlists):**",
            "",
            "| Identity | Allowed tools |",
            "|---|---|",
            *[
                f"| `{i.identity}` | {', '.join(f'`{a}`' for a in i.allow)} |"
                for i in card.identities
            ],
        ]
    L += [
        "",
        "## Stop conditions",
        "",
        *[f"- {s}" for s in card.stop_conditions],
        "",
        "## Failure playbook (five exits per node)",
        "",
        exit_table(card.policies),
        "",
        "## Chaos scenarios (asserted in `tests/test_chaos.py`)",
        "",
        "| Fault | Node | Expected exit | Invariant |",
        "|---|---|---|---|",
        *[f"| `{c.fault}` | `{c.node}` | **{c.exit}** | {c.invariant} |" for c in card.chaos],
        "",
        "## Evaluation",
        "",
        f"Golden set: `{card.eval.golden}` · suite: `{card.eval.suite}` · run "
        "`python -m evals --project " + card.project[:2] + "`",
        "",
    ]
    L += ["| Metric | Threshold | Current |", "|---|---|---|"]
    for m in METRICS:
        cur = _fmt_metric(m, scores["metrics"][m]) if scores else "n/a"
        L.append(f"| {m} | {card.eval.thresholds.get(m, '-')} | {cur} |")
    if scores:
        L += ["", f"Cases: {scores['n']} · gate: **{'PASS' if scores['passed'] else 'FAIL'}**"]
    L += [
        "",
        "## KPIs",
        "",
        "| KPI | Target | How measured |",
        "|---|---|---|",
        *[f"| {k.name} | {k.target} | {k.measure} |" for k in card.kpis],
        "",
        "## ROI sketch",
        "",
        card.roi.strip(),
        "",
    ]
    return "\n".join(L)


# ------------------------------------------------------------------------------ matrix
MATRIX_START, MATRIX_END = "<!-- doctrine-matrix:start -->", "<!-- doctrine-matrix:end -->"


def render_matrix() -> str:
    """Portfolio-level compliance matrix (top-level README), one row per project card."""
    rows = [
        "| Project | Maturity | Systems of record (MCP servers) | Corpus + ACL | Stop conds"
        " | Five-exit nodes | Chaos | Golden | Task success | Grounded | Policy viol. | KPI"
        " (target) |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for d in project_dirs():
        card = load_card(d / "doctrine.yaml")
        sp = scores_path(d)
        m = json.loads(sp.read_text())["metrics"] if sp.exists() else {}
        servers = sorted({c.split(".", 1)[0].strip('"') for c in card.contracts.mcp if "." in c})
        corpus = (
            ", ".join(f"{c.name} (ACL)" for c in card.knowledge.corpora)
            if card.knowledge.corpora
            else "none (by design)"
        )
        golden = d / card.eval.golden
        kpi = card.kpis[0]
        rows.append(
            f"| [{d.name}](projects/{d.name}/DOCTRINE.md) | L{card.maturity.level} | "
            f"{', '.join(servers) or 'none (retrieval only)'} | {corpus} | "
            f"{len(card.stop_conditions)} | "
            f"{len(card.failure_playbook)} | {len(card.chaos)} | "
            f"{len(load_golden(golden)) if golden.exists() else 0} | "
            f"{_fmt_metric('task_success', m.get('task_success'))} | "
            f"{_fmt_metric('groundedness', m.get('groundedness'))} | "
            f"{_fmt_metric('policy_violation_rate', m.get('policy_violation_rate'))} | "
            f"{kpi.name} ({kpi.target}) |"
        )
    return "\n".join(rows)


def readme_with_matrix(readme: str) -> str:
    head, _, rest = readme.partition(MATRIX_START)
    _, _, tail = rest.partition(MATRIX_END)
    return f"{head}{MATRIX_START}\n{render_matrix()}\n{MATRIX_END}{tail}"
