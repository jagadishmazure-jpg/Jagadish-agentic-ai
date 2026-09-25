# `policy_qa/`: corrective RAG over HR/IT policies

The importable package for project 01. It answers employee policy questions with cited,
grounded answers using a corrective RAG loop: rewrite the query, retrieve through the shared
context builder (ACL and as-of filtering), grade the chunks, retry once with an expanded query
if retrieval is weak, then answer and verify groundedness. If the evidence is not there, the
graph says so instead of answering from model memory.

| File | What it does |
|---|---|
| [`__init__.py`](__init__.py) | Package docstring. |
| [`corpus.py`](corpus.py) | In-memory policy corpus chunked by section with stable, citable ids such as `HR-PTO-2`. One section deliberately contains a prompt-injection string to exercise the sanitiser. `load_chunks()`. |
| [`demo.py`](demo.py) | CLI behind `run.py`: runs four demo questions, or the questions passed on the command line; `--mermaid PATH` writes the graph diagram. |
| [`eval_suite.py`](eval_suite.py) | `run_case` for the golden set, `chaos_scenario` and `CHAOS_CHECKS` for the doctrine chaos tests. |
| [`graph.py`](graph.py) | `build_graph()` and the typed `RagState`, `Answer`, `Citation` models. Nodes: `rewrite_query`, `retrieve`, `grade_chunks`, `pack_context`, `generate_answer`, `check_groundedness`, `finalize`, `insufficient_evidence`. |
| [`guards.py`](guards.py) | Project-local `sanitize` (strip instruction-like spans), `pack_context` (greedy pack within a token budget) and `groundedness` (every sentence must cite a packed chunk and overlap it lexically). |
| [`knowledge.py`](knowledge.py) | The policy corpus as a knowledge product on `shared.context`: ACL (`HR-COMP` pay bands only for `hr` / `people-managers`) and a superseded 2025 remote-work stipend edition. `ContextBuilderRetriever` adapts the builder to the project's retriever protocol; `default_retriever()`. |
| [`llm.py`](llm.py) | Prompts for rewrite, grade and answer, plus deterministic mocks (`mock_rewrite`, `mock_grade`, `mock_answer`, `mock_responder`). |
| [`retriever.py`](retriever.py) | Standalone local retrievers behind one interface: `BM25Retriever` and `EmbeddingRetriever` (any `embed(text)` function; `hashing_embedder` offline). |
| [`text.py`](text.py) | Tokenising, crude stemming, stopwords and `estimate_tokens` (about 4 characters per token). |

## Graph

```
rewrite_query -> retrieve (+sanitize) -> grade_chunks
    relevant           -> pack_context -> generate_answer -> check_groundedness
                             grounded -> finalize | ungrounded -> insufficient_evidence
    weak & attempt < 2 -> rewrite_query (expanded) -> retrieve ...
    weak & attempt = 2 -> insufficient_evidence
```

## Failure handling

- Every LLM step has a deterministic degrade: lexical rewrite, lexical grader, extractive answer.
- A retrieval outage takes the honest `insufficient_evidence` exit; nothing is generated from
  model memory.
- Non-happy exits are recorded in `state["exits"]` and must match the five-exit table in the card.

## Run

```bash
python projects/01-policy-qa-rag/run.py                    # demo (offline, mock LLM)
python projects/01-policy-qa-rag/run.py --mermaid projects/01-policy-qa-rag/graph.mmd  # also refresh the Mermaid diagram
pytest projects/01-policy-qa-rag                           # tests
python -m evals --project 01                # golden-set eval
CHAOS_FAULTS=model python projects/01-policy-qa-rag/run.py   # demo with every model deployment down
```

See the [project README](../README.md) for the business problem and design trade-offs, and [`DOCTRINE.md`](../DOCTRINE.md) for the five-exit table per node.
