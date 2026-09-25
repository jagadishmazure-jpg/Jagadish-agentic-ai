# `19-finetune-vs-prompting/tests/`: tests

Pytest suite for this project: dataset hygiene, training, the promotion gate and registry, the
serving graph, the Azure script's guards, plus chaos tests driven by the doctrine card. Shared
fixtures such as `kill_model`, `kill_sor` and `jailbreak`, and per-test fault isolation, come
from the repo-root [`conftest.py`](../../../conftest.py).

| File | What it does |
|---|---|
| [`conftest.py`](conftest.py) | Forces `LLM_PROVIDER=mock` for every test in the folder. |
| [`test_azure_script.py`](test_azure_script.py) | Dry run plans every request without network, `--execute` requires the env vars and refuses under CI or pytest, a model not supported for supervised fine-tuning and an invalid suffix are rejected before anything is sent, upload copies are UTF-8 with BOM. (6) |
| [`test_chaos.py`](test_chaos.py) | Doctrine-driven chaos tests. (4) |
| [`test_dataset.py`](test_dataset.py) | No planted PII value survives in any split, OCR-garbled anchors are scrubbed while document cues are kept, duplicates removed before splitting, rescans share a fingerprint, conflicting labels drop every copy, splits share no loan, fingerprint or near duplicate, the leak detector flags a near duplicate, the build refuses to write when leakage remains, files are valid chat format, bad rows rejected, committed data reproducible from the seed. (11) |
| [`test_graph.py`](test_graph.py) | Champion files a confident page, low confidence goes to a processor, PII scrubbed before the model and never filed, replay is idempotent in the LOS. (4) |
| [`test_training_and_gate.py`](test_training_and_gate.py) | Training is fast and deterministic, the artifact round-trips through JSON without pickle, fine-tuned beats the baseline and is promoted, a weak candidate is refused, the gate blocks a per-label regression and bad training data, rollback restores and persists, a tampered artifact is refused, committed results match a fresh run, the README table is rendered from the committed comparison, an unavailable candidate scores as errors. (10) |

Numbers in brackets are test counts from `pytest --collect-only` (35 in total).

## Run

```bash
pytest projects/19-finetune-vs-prompting                      # from the repo root
pytest projects/19-finetune-vs-prompting/tests/test_chaos.py -v
```

Tests run offline against the deterministic mock model; no API keys or network needed. The
Azure script is never executed against Azure.

## Chaos scenarios (from `doctrine.yaml`)

`test_chaos.py` is parametrized from the card's `chaos:` list, so adding a scenario to the card
adds a test. Each fault must make the named node take the declared exit, and the invariant is
checked by `CHAOS_CHECKS` in [`finetune_lab/eval_suite.py`](../finetune_lab/eval_suite.py).

| Fault | Node | Exit | Invariant |
|---|---|---|---|
| `model` | `classify` | degrade | every model down → processor review with "classifier unavailable", no guessed type |
| `model:finetuned` | `classify` | degrade | fine-tuned deployment down → prompted baseline files the W-2 and records its version |
| `sor:los` | `file_document` | degrade | type kept, filing parked in the outbox with idempotency key `classify:<doc_id>` |
| `jailbreak` | `intake` | escalate | page with injected instructions goes to processor review, not the requested type |
