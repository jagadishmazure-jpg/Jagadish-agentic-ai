# `shared/context/`: knowledge-plane context builder

The one retrieval runtime every agent uses. Projects register a `KnowledgeCorpus` (named,
owned, versioned documents with ACL groups and validity dates) and call
`ContextBuilder.build(...)` with a query, the `Principal` the context is built for and an as-of
date. The pipeline is: optional query expansion, ACL and temporal pre-filter, hybrid retrieval
(BM25 plus offline hashing-embedding vectors fused with reciprocal rank fusion), rerank,
sanitising (injected instructions, secrets, PII), then a budgeted pack into a `ContextBundle`
with a source map for citations. Everything runs locally: no network, no model downloads.

| File | What it does |
|---|---|
| [`__init__.py`](__init__.py) | Re-exports the public API (`ContextBuilder`, `ContextBundle`, `KnowledgeCorpus`, `Principal`, `Budget`, `pack`, `sanitize`, `citation_coverage`, errors, ...). |
| [`builder.py`](builder.py) | `ContextBuilder` (`expand`, `retrieve`, `build`) and `ContextBundle` (`text`, `chunk_ids`, `source_map`). Raises `RetrievalUnavailableError` when the backend is down (or a `retrieval` fault is injected) and `EmptyRetrievalError` when nothing visible and valid clears the score floor. |
| [`cache.py`](cache.py) | `SemanticCache` for packed contexts, keyed by principal ACL and as-of date and invalidated whenever the corpus version changes. |
| [`citations.py`](citations.py) | `cited_ids` and `citation_coverage`: the fraction of substantive sentences that carry at least one valid citation, plus any invalid ids. Used by critics and the groundedness metric. |
| [`documents.py`](documents.py) | `Principal`, `Document`, `Chunk`, `KnowledgeCorpus` and `chunk_document`, which splits on markdown headings into parent/child ids (`DOC::1`, `DOC::1.2`) carrying ACL and temporal metadata. |
| [`packer.py`](packer.py) | `Budget`, `Evidence`, `PackedContext` and `pack`: a greedy, order-preserving fill of explicit token allocations (policy / facts / history / tool I/O); overflow is dropped and recorded. |
| [`retrieval.py`](retrieval.py) | `BM25`, `HashingEmbedder` (deterministic offline embedder behind the `Embedder` protocol), `VectorIndex`, `rrf` and `HybridRetriever`. Swap the embedder for a hosted embedding deployment without touching callers. |
| [`sanitize.py`](sanitize.py) | `sanitize` and `looks_like_injection`: neutralise instruction-like spans and redact secrets and PII in untrusted text (retrieved chunks, tickets, tool observations). |

## Usage sketch

```python
from datetime import date
from shared.context import ContextBuilder, Principal

builder = ContextBuilder(corpus=corpus)  # corpus: the project's KnowledgeCorpus
bundle = builder.build("PTO carryover", Principal.of("u1", "employees"), as_of=date(2026, 3, 1))
bundle.text, bundle.source_map, bundle.chunk_ids  # packed evidence, citable ids, hits
```

See a project's `knowledge.py` (for example
[`projects/01-policy-qa-rag/policy_qa/knowledge.py`](../../projects/01-policy-qa-rag/policy_qa/knowledge.py))
for how each project builds its corpus and builder.

## Design notes

- ACL and validity are applied **before** ranking, so an out-of-scope or superseded chunk can
  never be packed, however relevant it looks.
- Empty or failed retrieval raises a typed error instead of returning an empty string, so the
  calling node takes its degrade exit rather than letting the model answer from nothing.

Tests: [`shared/tests/test_context.py`](../tests/test_context.py) (9 tests).
