"""Offline fine-tuning path: a TF-IDF + multinomial logistic-regression head trained on
the chat JSONL (system/user -> assistant label), exported as a JSON artifact.

Why a linear head and not a hosted fine-tune in CI: it trains on CPU in well under a second,
is deterministic for a fixed seed, and exercises the same lifecycle a hosted fine-tune
goes through (dataset version -> training run -> candidate -> gate -> promote / rollback).
The Azure OpenAI path (``azure_finetune.py``) consumes the *same* JSONL files.

Features are computed here, not by a scikit-learn vectorizer, so the artifact is plain
JSON (vocabulary, idf, weights) and serving needs only numpy: no pickle is ever loaded,
and the registry verifies the artifact's SHA-256 before use.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from finetune_lab.labels import SYSTEM_PROMPT_FT
from shared.observability import estimate_tokens

FEATURIZER = "words-1-2+char-3-v1"
DEFAULT_HYPERPARAMS: dict[str, Any] = {"C": 4.0, "min_df": 2, "max_iter": 2000, "seed": 19}


def features(text: str) -> list[str]:
    t = re.sub(r"\d", "0", text.lower())
    words = re.findall(r"[a-z0\[\]]+", t)
    out = [f"w:{w}" for w in words]
    out += [f"b:{a}_{b}" for a, b in itertools.pairwise(words)]
    for w in words:
        padded = f"^{w}$"
        out += [f"c:{padded[i : i + 3]}" for i in range(len(padded) - 2)]
    return out


@dataclass
class LinearTextModel:
    classes: list[str]
    vocab: dict[str, int]
    idf: list[float]
    coef: list[list[float]]
    intercept: list[float]
    hyperparams: dict[str, Any] = field(default_factory=dict)
    featurizer: str = FEATURIZER
    kind: str = "finetuned"

    def __post_init__(self) -> None:
        self._idf = np.asarray(self.idf)
        self._w = np.asarray(self.coef)
        self._b = np.asarray(self.intercept)

    def _vector(self, text: str) -> np.ndarray:
        x = np.zeros(len(self.vocab))
        for f, n in Counter(features(text)).items():
            j = self.vocab.get(f)
            if j is not None:
                x[j] = (1 + math.log(n)) * self._idf[j]
        norm = np.linalg.norm(x)
        return x / norm if norm else x

    def predict_proba(self, text: str) -> dict[str, float]:
        z = self._w @ self._vector(text) + self._b
        p = np.exp(z - z.max())
        p /= p.sum()
        return dict(zip(self.classes, p.tolist(), strict=True))

    def predict(self, text: str) -> tuple[str, float]:
        probs = self.predict_proba(text)
        label = max(probs, key=probs.__getitem__)
        return label, probs[label]

    @staticmethod
    def input_tokens(text: str) -> int:
        """Tokens a hosted fine-tuned deployment would bill for: short system prompt + doc."""
        return estimate_tokens(SYSTEM_PROMPT_FT) + estimate_tokens(text)

    # ------------------------------------------------------------------ artifact
    def to_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "featurizer": self.featurizer,
            "classes": self.classes,
            "vocab": self.vocab,
            "idf": [round(v, 6) for v in self.idf],
            "coef": [[round(v, 6) for v in row] for row in self.coef],
            "intercept": [round(v, 6) for v in self.intercept],
            "hyperparams": self.hyperparams,
        }

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> LinearTextModel:
        if d.get("featurizer") != FEATURIZER:
            raise ValueError(f"artifact featurizer {d.get('featurizer')} != {FEATURIZER}")
        return cls(d["classes"], d["vocab"], d["idf"], d["coef"], d["intercept"], d["hyperparams"])


def artifact_sha256(artifact: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(artifact, sort_keys=True).encode()).hexdigest()


@dataclass
class TrainResult:
    model: LinearTextModel
    seconds: float
    n_train: int
    n_features: int


def train(pairs: list[tuple[str, str]], **hyperparams: Any) -> TrainResult:
    """Fit on (text, label) pairs. Deterministic for fixed data + hyperparameters."""
    from scipy.sparse import csr_matrix
    from sklearn.linear_model import LogisticRegression

    hp = {**DEFAULT_HYPERPARAMS, **hyperparams}
    start = time.perf_counter()
    docs = [Counter(features(t)) for t, _ in pairs]
    df: Counter[str] = Counter()
    for d in docs:
        df.update(d.keys())
    vocab_terms = sorted(f for f, n in df.items() if n >= hp["min_df"])
    vocab = {f: i for i, f in enumerate(vocab_terms)}
    n = len(docs)
    idf = [math.log((1 + n) / (1 + df[f])) + 1 for f in vocab_terms]
    rows, cols, vals = [], [], []
    for i, d in enumerate(docs):
        entries = [
            (vocab[f], (1 + math.log(c)) * idf[vocab[f]]) for f, c in d.items() if f in vocab
        ]
        norm = math.sqrt(sum(v * v for _, v in entries)) or 1.0
        for j, v in entries:
            rows.append(i)
            cols.append(j)
            vals.append(v / norm)
    x = csr_matrix((vals, (rows, cols)), shape=(n, len(vocab)))
    y = [label for _, label in pairs]
    clf = LogisticRegression(C=hp["C"], max_iter=hp["max_iter"], random_state=hp["seed"])
    clf.fit(x, y)
    model = LinearTextModel(
        [str(c) for c in clf.classes_],
        vocab,
        idf,
        clf.coef_.tolist(),
        clf.intercept_.tolist(),
        hp,
    )
    return TrainResult(model, time.perf_counter() - start, n, len(vocab))


class FineTunedClassifier:
    """Serving wrapper with the same ``predict`` contract as ``PromptedClassifier``.

    In production the fine-tuned model is a hosted deployment, so it honours the shared
    chaos faults ``model`` and ``model:finetuned`` (an outage of that deployment)."""

    kind = "finetuned"

    def __init__(self, model: LinearTextModel, version: str = "unregistered"):
        self.model, self.version = model, version

    def predict(self, text: str):
        from finetune_lab.baseline import Prediction
        from shared import faults
        from shared.resilience import ModelUnavailableError

        if faults.active("model", "model:finetuned"):
            raise ModelUnavailableError("fine-tuned deployment unavailable (injected)")
        label, conf = self.model.predict(text)
        out_tokens = estimate_tokens(label)
        return Prediction(label, conf, self.model.input_tokens(text), out_tokens, self.version)
