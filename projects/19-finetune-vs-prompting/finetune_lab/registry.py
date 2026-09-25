"""Model registry: versioned entries, a promotion gate, a champion pointer and rollback.

Every entry is immutable once registered and carries what you need to reproduce or audit
it: kind (``prompt`` | ``finetuned``), a content-addressed version, the SHA-256 of the
artifact (the prompt text or the JSON weights), the dataset manifest hash it was trained
on, hyperparameters and eval metrics per split. Promotion compares a candidate with the
current champion on the **validation** split; the test split is only ever reported.

Gate (all must hold, else the candidate is marked ``rejected`` and the champion stays):

* macro-F1 >= champion macro-F1 + ``MIN_F1_GAIN``
* accuracy >= champion accuracy
* no single label's F1 drops by more than ``MAX_CLASS_DROP``
* the training set passed the dataset builder's PII and leakage checks

``rollback()`` restores the previous champion (a stack, so repeated rollbacks walk back).
``classifier(version)`` re-verifies the artifact hash before loading, so a tampered or
corrupted artifact is refused rather than served.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from finetune_lab.trainer import FineTunedClassifier, LinearTextModel, artifact_sha256

Kind = Literal["prompt", "finetuned"]
Stage = Literal["candidate", "champion", "archived", "rejected"]
MIN_F1_GAIN = 0.02
MAX_CLASS_DROP = 0.10


class PromotionRefusedError(RuntimeError):
    def __init__(self, version: str, problems: list[str]):
        super().__init__(f"{version} not promoted: {'; '.join(problems)}")
        self.version, self.problems = version, problems


class ArtifactIntegrityError(RuntimeError):
    pass


@dataclass
class Entry:
    version: str
    kind: Kind
    sha256: str
    created_at: str
    stage: Stage = "candidate"
    base_model: str = ""
    dataset_sha256: str = ""
    dataset_checks_passed: bool = True
    hyperparams: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, dict[str, Any]] = field(default_factory=dict)
    notes: str = ""


class ModelRegistry:
    """In memory by default; pass ``root`` to persist ``registry.json`` + ``artifacts/``."""

    def __init__(self, root: Path | None = None):
        self.root = root
        self.entries: dict[str, Entry] = {}
        self.champions: list[str] = []  # stack: last item is the serving champion
        self.events: list[dict[str, str]] = []
        self._artifacts: dict[str, dict[str, Any]] = {}
        self._loaded: dict[str, Any] = {}  # version -> verified FineTunedClassifier
        if root and (root / "registry.json").exists():
            self._load()

    # ------------------------------------------------------------------ persistence
    def _load(self) -> None:
        assert self.root
        raw = json.loads((self.root / "registry.json").read_text())
        self.entries = {v: Entry(**e) for v, e in raw["entries"].items()}
        self.champions, self.events = raw["champions"], raw["events"]

    def _save(self) -> None:
        if not self.root:
            return
        self.root.mkdir(parents=True, exist_ok=True)
        body = {
            "entries": {v: asdict(e) for v, e in self.entries.items()},
            "champions": self.champions,
            "events": self.events,
        }
        (self.root / "registry.json").write_text(json.dumps(body, indent=2) + "\n")

    def _put_artifact(self, version: str, artifact: dict[str, Any]) -> None:
        self._artifacts[version] = artifact
        if self.root:
            (self.root / "artifacts").mkdir(parents=True, exist_ok=True)
            (self.root / "artifacts" / f"{version}.json").write_text(json.dumps(artifact))

    def _get_artifact(self, version: str) -> dict[str, Any]:
        if version in self._artifacts:
            return self._artifacts[version]
        if self.root and (p := self.root / "artifacts" / f"{version}.json").exists():
            return json.loads(p.read_text())
        raise ArtifactIntegrityError(f"artifact for {version} is missing")

    def _log(self, event: str, version: str, detail: str = "") -> None:
        now = datetime.now(UTC).isoformat(timespec="seconds")
        self.events.append({"at": now, "event": event, "version": version, "detail": detail})

    # ------------------------------------------------------------------ register
    def register_prompt(self, prompt: str, base_model: str, notes: str = "") -> Entry:
        sha = hashlib.sha256(prompt.encode()).hexdigest()
        version = f"prompt-{sha[:8]}"
        if version not in self.entries:
            self.entries[version] = Entry(
                version, "prompt", sha, _now(), base_model=base_model, notes=notes
            )
            self._put_artifact(version, {"kind": "prompt", "prompt": prompt})
            self._log("registered", version, base_model)
            self._save()
        return self.entries[version]

    def register_finetuned(
        self,
        model: LinearTextModel,
        dataset_sha256: str,
        dataset_checks_passed: bool = True,
        base_model: str = "local-linear-head",
        notes: str = "",
    ) -> Entry:
        artifact = model.to_json()
        sha = artifact_sha256(artifact)
        version = f"ft-{sha[:8]}"
        if version not in self.entries:
            self.entries[version] = Entry(
                version,
                "finetuned",
                sha,
                _now(),
                base_model=base_model,
                dataset_sha256=dataset_sha256,
                dataset_checks_passed=dataset_checks_passed,
                hyperparams=model.hyperparams,
                notes=notes,
            )
            self._put_artifact(version, artifact)
            self._log("registered", version, f"dataset {dataset_sha256[:12]}")
            self._save()
        return self.entries[version]

    def record_metrics(self, version: str, split: str, metrics: dict[str, Any]) -> None:
        self.entries[version].metrics[split] = metrics
        self._save()

    # ------------------------------------------------------------------ lifecycle
    @property
    def champion(self) -> Entry | None:
        return self.entries[self.champions[-1]] if self.champions else None

    def gate(self, version: str, split: str = "val") -> list[str]:
        cand, champ = self.entries[version], self.champion
        problems = []
        if not cand.dataset_checks_passed:
            problems.append("training data failed PII/leakage checks")
        if split not in cand.metrics:
            return [*problems, f"no {split} metrics for {version}"]
        if champ is None:
            return problems
        if split not in champ.metrics:
            return [*problems, f"no {split} metrics for champion {champ.version}"]
        c, b = cand.metrics[split], champ.metrics[split]
        if c["macro_f1"] < b["macro_f1"] + MIN_F1_GAIN:
            problems.append(
                f"macro_f1 {c['macro_f1']:.3f} < champion {b['macro_f1']:.3f} + {MIN_F1_GAIN}"
            )
        if c["accuracy"] < b["accuracy"]:
            problems.append(f"accuracy {c['accuracy']:.3f} < champion {b['accuracy']:.3f}")
        for label, f1 in b.get("per_class_f1", {}).items():
            drop = f1 - c.get("per_class_f1", {}).get(label, 0.0)
            if drop > MAX_CLASS_DROP:
                problems.append(f"{label} F1 drops {drop:.2f} (> {MAX_CLASS_DROP})")
        return problems

    def promote(self, version: str, split: str = "val") -> Entry:
        problems = self.gate(version, split)
        if problems:
            self.entries[version].stage = "rejected"
            self._log("promotion_refused", version, "; ".join(problems))
            self._save()
            raise PromotionRefusedError(version, problems)
        if self.champion:
            self.champion.stage = "archived"
        self.entries[version].stage = "champion"
        self.champions.append(version)
        self._log("promoted", version)
        self._save()
        return self.entries[version]

    def rollback(self, reason: str) -> Entry:
        if len(self.champions) < 2:
            raise RuntimeError("no previous champion to roll back to")
        bad = self.champions.pop()
        self.entries[bad].stage = "archived"
        self.champion.stage = "champion"  # type: ignore[union-attr]
        self._log("rolled_back", bad, f"to {self.champions[-1]}: {reason}")
        self._save()
        return self.champion  # type: ignore[return-value]

    # ------------------------------------------------------------------ serving
    def classifier(self, version: str | None = None, llm: Any = None):
        """Load a servable classifier, verifying the artifact hash first."""
        from finetune_lab.baseline import PromptedClassifier

        version = version or (self.champion.version if self.champion else None)
        if version is None:
            raise RuntimeError("registry has no champion")
        entry = self.entries[version]
        if version in self._loaded:
            return self._loaded[version]
        artifact = self._get_artifact(version)
        if entry.kind == "prompt":
            actual = hashlib.sha256(artifact["prompt"].encode()).hexdigest()
            if actual != entry.sha256:
                raise ArtifactIntegrityError(f"{version}: prompt hash mismatch")
            clf = PromptedClassifier(llm=llm, prompt=artifact["prompt"])
            clf.version = version
            return clf
        if version not in self._loaded:  # verify once per process, then serve from memory
            if artifact_sha256(artifact) != entry.sha256:
                raise ArtifactIntegrityError(f"{version}: artifact hash mismatch")
            self._loaded[version] = FineTunedClassifier(
                LinearTextModel.from_json(artifact), version
            )
        return self._loaded[version]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
