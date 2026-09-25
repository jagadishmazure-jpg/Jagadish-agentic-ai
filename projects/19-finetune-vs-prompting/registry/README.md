# `19-finetune-vs-prompting/registry/`: model registry

The committed model registry that the serving graph reads its champion from. It is written by
`python projects/19-finetune-vs-prompting/run.py compare --write` through
[`finetune_lab/registry.py`](../finetune_lab/registry.py); do not edit by hand.

| File | What it does |
|---|---|
| [`registry.json`](registry.json) | Every registered version (kind, base model, system prompt, dataset hash, artifact sha256, metrics per split, stage), the champion stack used for rollback, and the event log (registered, promoted, promotion refused, rolled back). |
| [`artifacts/`](artifacts/README.md) | One JSON artifact per version. |

## Lifecycle

`register` → `record_metrics` → `gate` → `promote` (or `promotion_refused`) → `rollback` if
production monitoring flags the champion. The serving graph loads the champion through
`classifier()`, which recomputes the artifact's sha256 and refuses a mismatch.
