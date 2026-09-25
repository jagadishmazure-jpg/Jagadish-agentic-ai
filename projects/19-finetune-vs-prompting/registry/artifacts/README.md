# `19-finetune-vs-prompting/registry/artifacts/`: versioned model artifacts

One JSON file per registered version, named after the version id. `compare --write` deletes
and regenerates the `*.json` files and keeps this README.

| File | What it does |
|---|---|
| `ft-<hash>.json` | Fine-tuned head (`LinearTextModel`): labels, vocabulary, IDF weights, coefficients and intercepts rounded to 6 decimals. Loaded with NumPy; no pickle, so the file is safe to load and easy to diff. |
| `prompt-<hash>.json` | Prompted baseline: the base model name and the system prompt (rubric + examples). A prompt is versioned and rolled back like a model. |

The version id is derived from the artifact contents, and its sha256 is recorded in
[`../registry.json`](../registry.json) and checked on every load.
