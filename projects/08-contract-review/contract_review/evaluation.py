"""Offline evaluation harness: precision / recall of flagged risks against gold labels.

A flagged risk = (contract, clause_type) in the final report. Severity accuracy is reported
on true positives. ``gate()`` turns metrics into a pass/fail decision for CI (LLMOps gating).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from contract_review.contracts import EVAL_SET
from contract_review.graph import build_graph


@dataclass
class EvalResult:
    rows: list[dict[str, Any]] = field(default_factory=list)
    tp: int = 0
    fp: int = 0
    fn: int = 0
    severity_correct: int = 0

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 1.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0

    @property
    def severity_accuracy(self) -> float:
        return self.severity_correct / self.tp if self.tp else 1.0


def run_eval(graph=None, dataset: list[dict] | None = None) -> EvalResult:
    graph = graph or build_graph()
    res = EvalResult()
    for case in dataset or EVAL_SET:
        report = graph.invoke({"text": case["text"]})["report"]
        pred = {f["clause_type"]: f["severity"] for f in report["findings"]}
        gold = case["gold"]
        tp = set(pred) & set(gold)
        fp, fn = set(pred) - set(gold), set(gold) - set(pred)
        sev_ok = sum(pred[t] == gold[t] for t in tp)
        res.tp, res.fp, res.fn = res.tp + len(tp), res.fp + len(fp), res.fn + len(fn)
        res.severity_correct += sev_ok
        res.rows.append(
            {
                "id": case["id"],
                "tp": len(tp),
                "fp": sorted(fp),
                "fn": sorted(fn),
                "severity_ok": f"{sev_ok}/{len(tp)}",
            }
        )
    return res


def gate(res: EvalResult, min_precision: float, min_recall: float) -> tuple[bool, list[str]]:
    reasons = []
    if res.precision < min_precision:
        reasons.append(f"precision {res.precision:.2f} < {min_precision}")
    if res.recall < min_recall:
        reasons.append(f"recall {res.recall:.2f} < {min_recall}")
    return not reasons, reasons


def format_report(res: EvalResult) -> str:
    lines = [
        f"{'case':<16} {'TP':>3}  {'false positives':<28} {'false negatives':<28} sev",
        "-" * 86,
    ]
    for r in res.rows:
        lines.append(
            f"{r['id']:<16} {r['tp']:>3}  {', '.join(r['fp']) or '-':<28} "
            f"{', '.join(r['fn']) or '-':<28} {r['severity_ok']}"
        )
    lines += [
        "-" * 86,
        f"precision {res.precision:.2f} | recall {res.recall:.2f} | F1 {res.f1:.2f} | "
        f"severity accuracy {res.severity_accuracy:.2f}  (TP={res.tp} FP={res.fp} "
        f"FN={res.fn})",
    ]
    return "\n".join(lines)
