# `fnol/`: FNOL from scanned packet to approved reserve

The importable package for project 13. A first notice of loss arrives as a scanned packet. A
Document-Intelligence-style OCR mock returns fields with confidence, and low-confidence
required fields send the packet to manual indexing rather than guessing. Coverage is decided by
deterministic rules over policy form wording retrieved for the policy's edition and state,
while a fraud score comes from an ML endpoint tool, never from the model. An adjuster approves
reserve and payment within authority limits, and the claimant message never contains fraud
language.

| File | What it does |
|---|---|
| [`__init__.py`](__init__.py) | Empty package marker. |
| [`demo.py`](demo.py) | CLI behind `run.py`: clean water loss to approved payment, the same seepage loss on 2019 versus 2023 form editions, a high fraud band leading to an SIU hold, and a blurry policy number sent to the indexing queue; `--mermaid PATH`. |
| [`eval_suite.py`](eval_suite.py) | `run`, `run_case`, `chaos_scenario`, `CHAOS_CHECKS` and `leaky_responder` (a model that leaks internal language, used to prove the guard). |
| [`graph.py`](graph.py) | `build_graph()` and `FnolState`. Nodes: `intake`, `policy`, `coverage`, `fraud`, `adjudicate`, `human_approval` (interrupt), `finalize`, `queue`. Also `customer_safe` / `customer_template` for the claimant message guard. |
| [`knowledge.py`](knowledge.py) | Homeowners policy forms by edition plus state amendatory endorsements on `shared.context`: retrieval as of the edition date on the policy; state carried in the tenant dimension so Texas and California wording never mix; SIU guidelines restricted to `siu`. |
| [`ocr.py`](ocr.py) | OCR mock: `analyze()` returns field/value/confidence (typed 0.98, handwritten `[hw]` 0.78, smudged 0.45); `low_confidence()` lists required fields below the floor. |
| [`rules.py`](rules.py) | Deterministic `coverage()` and `payable()` per form edition and jurisdiction; each rule names the provision it rests on, and the graph accepts the decision only if that provision was actually retrieved. |
| [`sor.py`](sor.py) | MCP servers and two gateway identities: `mi-fnol-reader` (docintel, policy admin, fraud ML) and `mi-claims-writer` (open claim, set reserve, issue payment, queue document). |
| [`systems.py`](systems.py) | Mock scanned-packet store, policy admin, fraud ML endpoint and claims system; `seed_systems()`. |

## Graph

```
intake (OCR via MCP, confidence gate, injection check) -> policy (in force on loss date?)
  -> [coverage (edition + jurisdiction RAG, deterministic rules) || fraud (ML tool)]
  -> adjudicate -> human_approval (adjuster; authority limits; timeout never pays)
  -> finalize (idempotent claims writes, neutral claimant message) | queue
```

## Design notes

- Grounding check: a coverage decision citing a provision that was not retrieved for this
  edition and state is rejected.
- Payment is idempotent on replay, and non-adjusters cannot approve.

## Run

```bash
python projects/13-insurance-fnol-coverage/run.py                    # demo (offline, mock LLM)
python projects/13-insurance-fnol-coverage/run.py --mermaid projects/13-insurance-fnol-coverage/graph.mmd  # also refresh the Mermaid diagram
pytest projects/13-insurance-fnol-coverage                           # tests
python -m evals --project 13                # golden-set eval
CHAOS_FAULTS=model python projects/13-insurance-fnol-coverage/run.py   # demo with every model deployment down
```

See the [project README](../README.md) for the business problem and design trade-offs, and [`DOCTRINE.md`](../DOCTRINE.md) for the five-exit table per node.
