"""Comparison harness: prompted base model vs fine-tuned model, then the promotion gate.

    python projects/19-finetune-vs-prompting/run.py compare            # print the report
    python projects/19-finetune-vs-prompting/run.py compare --write    # also rebuild
        registry/ and refresh evals/comparison.json + the README results table

Both variants go through ``shared.evals.harness.run_suite`` (the same harness behind
``python -m evals``), one case per held-out document. On top of task success (accuracy)
the harness here records predictions, wall-clock latency per call and token counts, and
computes macro-F1 and per-label F1. Cost is reported as a **proxy**: input and output
tokens per call for the hosted equivalent (the baseline sends the full rubric every call;
a fine-tuned deployment gets a one-line system prompt). Latency is measured on the offline
stand-ins (mock chat model vs local linear head), so it says nothing about hosted latency.

The promotion decision uses the validation split; the test split is reported only.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import json
import statistics
import time
from pathlib import Path
from typing import Any

from finetune_lab.baseline import PromptedClassifier
from finetune_lab.dataset import load_split
from finetune_lab.labels import LABELS, SYSTEM_PROMPT_BASELINE
from finetune_lab.registry import ModelRegistry, PromotionRefusedError
from finetune_lab.trainer import FineTunedClassifier, train
from shared.evals import CaseResult
from shared.evals.harness import run_suite
from shared.observability import install

PROJECT = Path(__file__).resolve().parents[1]
DATA = PROJECT / "data"
COMPARISON = PROJECT / "evals" / "comparison.json"
REGISTRY = PROJECT / "registry"
README = PROJECT / "README.md"
ERROR_LABEL = "__error__"
BLOCK_START, BLOCK_END = "<!-- results:start -->", "<!-- results:end -->"
BASE_MODEL = "mock-chat-model (offline stand-in for the base deployment)"


def classification_metrics(y_true: list[str], y_pred: list[str]) -> dict[str, Any]:
    per_class = {}
    for label in LABELS:
        tp = sum(t == p == label for t, p in zip(y_true, y_pred, strict=True))
        fp = sum(p == label != t for t, p in zip(y_true, y_pred, strict=True))
        fn = sum(t == label != p for t, p in zip(y_true, y_pred, strict=True))
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        per_class[label] = round(2 * prec * rec / (prec + rec), 4) if prec + rec else 0.0
    present = [lbl for lbl in LABELS if lbl in y_true]
    acc = sum(t == p for t, p in zip(y_true, y_pred, strict=True)) / (len(y_true) or 1)
    return {
        "n": len(y_true),
        "accuracy": round(acc, 4),
        "macro_f1": round(sum(per_class[lbl] for lbl in present) / (len(present) or 1), 4),
        "per_class_f1": per_class,
    }


def evaluate(clf: Any, pairs: list[tuple[str, str]], split: str) -> dict[str, Any]:
    """Run one variant over a split through the shared eval harness."""
    preds: list[str] = []
    lat_ms: list[float] = []
    tin: list[int] = []
    tout: list[int] = []

    def run_case(case: dict[str, Any]) -> CaseResult:
        t0 = time.perf_counter()
        try:
            p = clf.predict(case["input"]["text"])
        except Exception as exc:  # an unavailable variant scores as wrong, never skipped
            lat_ms.append((time.perf_counter() - t0) * 1000)
            preds.append(ERROR_LABEL)
            tin.append(0)
            tout.append(0)
            return CaseResult(case["id"], False, detail=f"error: {type(exc).__name__}")
        lat_ms.append((time.perf_counter() - t0) * 1000)
        preds.append(p.label)
        tin.append(p.input_tokens)
        tout.append(p.output_tokens)
        ok = p.label == case["expect"]["label"]
        return CaseResult(case["id"], ok, detail=f"pred={p.label} conf={p.confidence:.2f}")

    cases = [
        {"id": f"{split}-{i:03d}", "input": {"text": t}, "expect": {"label": y}}
        for i, (t, y) in enumerate(pairs)
    ]
    report = run_suite(f"19-{clf.kind}-{split}", cases, run_case)
    out = classification_metrics([y for _, y in pairs], preds)
    assert abs(out["accuracy"] - report.metrics["task_success"]) < 1e-4
    lat = sorted(lat_ms)
    out.update(
        {
            "latency_ms_p50": round(statistics.median(lat), 3),
            "latency_ms_p95": round(lat[min(len(lat) - 1, int(0.95 * len(lat)))], 3),
            "input_tokens_per_call": round(statistics.mean(tin), 1),
            "output_tokens_per_call": round(statistics.mean(tout), 1),
        }
    )
    return out


def run_comparison(
    data_dir: Path = DATA, registry: ModelRegistry | None = None, llm: Any = None
) -> tuple[dict[str, Any], ModelRegistry]:
    install()
    registry = registry if registry is not None else ModelRegistry()
    manifest = json.loads((data_dir / "manifest.json").read_text())
    dataset_sha = hashlib.sha256(json.dumps(manifest["sha256"], sort_keys=True).encode())
    splits = {s: load_split(data_dir / f"{s}.jsonl") for s in ("train", "val", "test")}

    base = registry.register_prompt(SYSTEM_PROMPT_BASELINE, BASE_MODEL, "rubric + 3-shot")
    trained = train(splits["train"])
    ft = registry.register_finetuned(
        trained.model,
        dataset_sha.hexdigest(),
        dataset_checks_passed=True,  # build() raises on leakage; files re-validated in tests
        notes=f"{trained.n_train} examples, {trained.n_features} features",
    )
    variants = {
        "baseline": (base.version, PromptedClassifier(llm=llm)),
        "finetuned": (ft.version, FineTunedClassifier(trained.model, ft.version)),
    }
    results: dict[str, dict[str, Any]] = {"val": {}, "test": {}}
    for split in ("val", "test"):
        for name, (version, clf) in variants.items():
            m = evaluate(clf, splits[split], split)
            results[split][name] = m
            registry.record_metrics(version, split, m)

    if registry.champion is None:
        registry.promote(base.version)  # the prompt is the incumbent until beaten
    try:
        registry.promote(ft.version)
        gate = {"passed": True, "problems": []}
    except PromotionRefusedError as exc:
        gate = {"passed": False, "problems": exc.problems}
    report = {
        "task": "mortgage document type classification (10 labels)",
        "dataset": {"counts": manifest["counts"], "sha256": dataset_sha.hexdigest()[:16]},
        "training": {
            "seconds": round(trained.seconds, 2),
            "examples": trained.n_train,
            "features": trained.n_features,
            "hyperparams": trained.model.hyperparams,
        },
        "versions": {"baseline": base.version, "finetuned": ft.version},
        "results": results,
        "gate": {"split": "val", **gate},
        "champion": registry.champion.version if registry.champion else None,
    }
    return report, registry


@functools.lru_cache(maxsize=4)
def _load(root: str) -> ModelRegistry:
    if not (Path(root) / "registry.json").exists():
        raise FileNotFoundError(f"no registry at {root}: run `run.py compare --write`")
    return ModelRegistry(Path(root))


def load_registry(root: Path | None = None) -> ModelRegistry:
    """The committed registry (``registry/``) the serving graph reads its champion from.
    Serving never trains: it loads the promoted, hash-verified artifact."""
    return _load(str(root or REGISTRY))


# ------------------------------------------------------------------------------ report
def render_table(report: dict[str, Any]) -> str:
    rows = [
        "| Split | Variant | Accuracy | Macro-F1 | Latency p50 / p95 (ms) | Input tokens/call "
        "| Output tokens/call |",
        "|---|---|---|---|---|---|---|",
    ]
    for split in ("val", "test"):
        for name in ("baseline", "finetuned"):
            m = report["results"][split][name]
            label = "prompted base model" if name == "baseline" else "fine-tuned head"
            rows.append(
                f"| {split} (n={m['n']}) | {label} | {m['accuracy']:.3f} | {m['macro_f1']:.3f} "
                f"| {m['latency_ms_p50']:.3f} / {m['latency_ms_p95']:.3f} "
                f"| {m['input_tokens_per_call']:.0f} | {m['output_tokens_per_call']:.0f} |"
            )
    g = report["gate"]
    verdict = "PASS, fine-tuned model promoted" if g["passed"] else "FAIL, not promoted"
    lines = [
        *rows,
        "",
        f"Promotion gate (validation split): **{verdict}**. Champion: `{report['champion']}`. "
        f"Training: {report['training']['examples']} examples, "
        f"{report['training']['features']} features, {report['training']['seconds']} s on CPU.",
    ]
    if g["problems"]:
        lines.append("Gate problems: " + "; ".join(g["problems"]))
    return "\n".join(lines)


def readme_with_table(readme: str, report: dict[str, Any]) -> str:
    head, _, rest = readme.partition(BLOCK_START)
    _, _, tail = rest.partition(BLOCK_END)
    return f"{head}{BLOCK_START}\n{render_table(report)}\n{BLOCK_END}{tail}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true", help="refresh comparison.json + README")
    ap.add_argument("--registry-dir", type=Path, help="persist the registry here")
    ap.add_argument("--live", action="store_true", help="baseline on the configured real LLM")
    args = ap.parse_args(argv)
    import os

    if not args.live:
        os.environ["LLM_PROVIDER"] = "mock"
    root = args.registry_dir
    if args.write:
        root = REGISTRY  # start fresh (folder READMEs are kept)
        (root / "registry.json").unlink(missing_ok=True)
        for old in (root / "artifacts").glob("*.json"):
            old.unlink()
    report, _ = run_comparison(registry=ModelRegistry(root))
    print(render_table(report))
    if args.write:
        COMPARISON.write_text(json.dumps(report, indent=2) + "\n")
        if BLOCK_START in README.read_text():
            README.write_text(readme_with_table(README.read_text(), report))
        print("\nwrote evals/comparison.json, registry/ and the README results table")
    return 0 if report["gate"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
