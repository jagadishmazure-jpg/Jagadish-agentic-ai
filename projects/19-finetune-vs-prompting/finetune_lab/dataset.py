"""Dataset builder: raw export -> scrubbed, de-duplicated, leakage-checked chat JSONL.

    python -m finetune_lab.dataset --out data/        # from the project folder

Steps, in order:

1. **Scrub PII** from every document (before anything is hashed or written).
2. **Dedup** on a normalised fingerprint (case, whitespace, digits and OCR look-alikes
   folded), keeping the first occurrence. Conflicting labels for one fingerprint drop
   every copy: a label we can't trust is worse than a missing example.
3. **Group split by loan** (train/val/test = 70/15/15 of loan files, seeded). Documents from
   one loan file never straddle splits, so borrower-specific phrasing can't leak.
4. **Leakage check** across splits: shared loan IDs, identical fingerprints and near-
   duplicates (word 3-shingle Jaccard >= 0.8). Offending val/test rows are dropped and
   counted in the manifest; the builder fails if any leak remains.
5. **Write** ``train.jsonl`` / ``val.jsonl`` / ``test.jsonl`` in the chat fine-tuning format
   (``{"messages": [system, user, assistant]}``) plus ``manifest.json`` with counts and
   SHA-256 of each file (the manifest hash versions the dataset in the model registry).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from finetune_lab.corpus import Record, generate
from finetune_lab.labels import LABELS, SYSTEM_PROMPT_FT
from finetune_lab.pii import contains_pii, scrub

SPLITS = ("train", "val", "test")
RATIOS = (0.70, 0.15, 0.15)
NEAR_DUP_JACCARD = 0.8
MIN_TRAIN_EXAMPLES = 10  # Azure OpenAI fine-tuning refuses fewer than 10 training examples
_FOLD = str.maketrans({"1": "l", "0": "o", "5": "s", "c": "e"})


class LeakageError(RuntimeError):
    pass


def fingerprint(text: str) -> str:
    t = re.sub(r"\d", "0", text.lower()).translate(_FOLD)
    t = t.replace("rn", "m")
    t = re.sub(r"[^a-z0\[\]]+", " ", t).strip()
    return hashlib.sha256(t.encode()).hexdigest()[:16]


def shingles(text: str, n: int = 3) -> set[str]:
    words = re.findall(r"[a-z]+", text.lower())
    return {" ".join(words[i : i + n]) for i in range(max(0, len(words) - n + 1))}


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def to_chat(text: str, label: str) -> dict[str, Any]:
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT_FT},
            {"role": "user", "content": text},
            {"role": "assistant", "content": label},
        ]
    }


@dataclass
class Example:
    doc_id: str
    loan_id: str
    label: str
    text: str
    fp: str


@dataclass
class BuildReport:
    raw: int = 0
    pii_redactions: dict[str, int] = field(default_factory=dict)
    exact_duplicates: int = 0
    label_conflicts: int = 0
    leakage_dropped: dict[str, int] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    label_counts: dict[str, dict[str, int]] = field(default_factory=dict)
    sha256: dict[str, str] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return self.__dict__


def dedup(examples: list[Example], report: BuildReport) -> list[Example]:
    by_fp: dict[str, list[Example]] = {}
    for ex in examples:
        by_fp.setdefault(ex.fp, []).append(ex)
    kept = []
    for group in by_fp.values():
        if len({e.label for e in group}) > 1:
            report.label_conflicts += len(group)
            continue
        report.exact_duplicates += len(group) - 1
        kept.append(group[0])
    return sorted(kept, key=lambda e: e.doc_id)


def group_split(examples: list[Example], seed: int) -> dict[str, list[Example]]:
    loans = sorted({e.loan_id for e in examples})
    random.Random(seed).shuffle(loans)
    n_train = round(len(loans) * RATIOS[0])
    n_val = round(len(loans) * RATIOS[1])
    bucket = {
        **dict.fromkeys(loans[:n_train], "train"),
        **dict.fromkeys(loans[n_train : n_train + n_val], "val"),
        **dict.fromkeys(loans[n_train + n_val :], "test"),
    }
    out: dict[str, list[Example]] = {s: [] for s in SPLITS}
    for e in examples:
        out[bucket[e.loan_id]].append(e)
    return out


def find_leaks(splits: dict[str, list[Example]]) -> dict[str, list[str]]:
    """doc_ids in val/test that overlap train (or val, for test) by loan, fingerprint or
    near-duplicate text."""
    leaks: dict[str, list[str]] = {"val": [], "test": []}
    for target, refs in (("val", ["train"]), ("test", ["train", "val"])):
        ref = [e for r in refs for e in splits[r]]
        ref_loans = {e.loan_id for e in ref}
        ref_fps = {e.fp for e in ref}
        ref_sh = [shingles(e.text) for e in ref]
        for e in splits[target]:
            sh = shingles(e.text)
            if (
                e.loan_id in ref_loans
                or e.fp in ref_fps
                or any(jaccard(sh, r) >= NEAR_DUP_JACCARD for r in ref_sh)
            ):
                leaks[target].append(e.doc_id)
    return leaks


def build(records: list[Record] | None = None, seed: int = 19) -> tuple[dict, BuildReport]:
    records = records if records is not None else generate(seed=seed)
    report = BuildReport(raw=len(records))
    redactions: Counter[str] = Counter()
    examples = []
    for r in records:
        if r.label not in LABELS:
            continue
        text, counts = scrub(r.text)
        redactions.update(counts)
        examples.append(Example(r.doc_id, r.loan_id, r.label, text, fingerprint(text)))
    report.pii_redactions = dict(sorted(redactions.items()))
    splits = group_split(dedup(examples, report), seed)
    leaks = find_leaks(splits)
    report.leakage_dropped = {k: len(v) for k, v in leaks.items()}
    for target, ids in leaks.items():
        drop = set(ids)
        splits[target] = [e for e in splits[target] if e.doc_id not in drop]
    if any(find_leaks(splits).values()):
        raise LeakageError("leakage remains after filtering")
    for s in SPLITS:
        report.counts[s] = len(splits[s])
        report.label_counts[s] = dict(sorted(Counter(e.label for e in splits[s]).items()))
    if report.counts["train"] < MIN_TRAIN_EXAMPLES:
        raise ValueError(f"need >= {MIN_TRAIN_EXAMPLES} training examples")
    return splits, report


def validate_chat_file(path: Path) -> list[str]:
    """Problems with a chat-format JSONL file (empty list == valid)."""
    problems = []
    for i, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        try:
            row = json.loads(line)
            roles = [m["role"] for m in row["messages"]]
        except (json.JSONDecodeError, KeyError, TypeError):
            problems.append(f"line {i}: not a chat example")
            continue
        if roles != ["system", "user", "assistant"]:
            problems.append(f"line {i}: roles {roles}")
        elif row["messages"][2]["content"] not in LABELS:
            problems.append(f"line {i}: unknown label")
        elif contains_pii(row["messages"][1]["content"]):
            problems.append(f"line {i}: PII in user content")
    return problems


def write(splits: dict[str, list[Example]], report: BuildReport, out: Path) -> BuildReport:
    out.mkdir(parents=True, exist_ok=True)
    for s in SPLITS:
        lines = [json.dumps(to_chat(e.text, e.label), ensure_ascii=False) for e in splits[s]]
        data = ("\n".join(lines) + "\n").encode("utf-8")
        (out / f"{s}.jsonl").write_bytes(data)
        report.sha256[s] = hashlib.sha256(data).hexdigest()
    (out / "manifest.json").write_text(json.dumps(report.to_json(), indent=2) + "\n")
    return report


def load_split(path: Path) -> list[tuple[str, str]]:
    """(text, label) pairs from a chat JSONL split."""
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8-sig").splitlines() if x]
    return [(r["messages"][1]["content"], r["messages"][2]["content"]) for r in rows]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[1] / "data")
    ap.add_argument("--seed", type=int, default=19)
    args = ap.parse_args(argv)
    splits, report = build(seed=args.seed)
    write(splits, report, args.out)
    print(json.dumps({k: v for k, v in report.to_json().items() if k != "sha256"}, indent=2))


if __name__ == "__main__":
    main()
