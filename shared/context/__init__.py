"""Knowledge-plane runtime: one context builder for every agent."""

from shared.context.builder import (
    ContextBuilder,
    ContextBundle,
    EmptyRetrievalError,
    RetrievalError,
    RetrievalUnavailableError,
)
from shared.context.cache import SemanticCache
from shared.context.citations import citation_coverage, cited_ids
from shared.context.documents import Chunk, Document, KnowledgeCorpus, Principal, chunk_document
from shared.context.packer import Budget, Evidence, PackedContext, pack
from shared.context.retrieval import BM25, Embedder, HashingEmbedder, Hit, HybridRetriever, rrf
from shared.context.sanitize import Sanitized, looks_like_injection, sanitize

__all__ = [
    "BM25",
    "Budget",
    "Chunk",
    "ContextBuilder",
    "ContextBundle",
    "Document",
    "Embedder",
    "EmptyRetrievalError",
    "Evidence",
    "HashingEmbedder",
    "Hit",
    "HybridRetriever",
    "KnowledgeCorpus",
    "PackedContext",
    "Principal",
    "RetrievalError",
    "RetrievalUnavailableError",
    "Sanitized",
    "SemanticCache",
    "chunk_document",
    "citation_coverage",
    "cited_ids",
    "looks_like_injection",
    "pack",
    "rrf",
    "sanitize",
]
