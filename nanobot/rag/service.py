"""Initialization and query orchestration for the absurd novel knowledge base."""

from __future__ import annotations

import logging
import time
from typing import TypeVar

from nanobot.rag import config, embeddings, indexing, store
from nanobot.rag.rerank import weighted_rrf
from nanobot.rag.types import RagInitResult

T = TypeVar("T")
logger = logging.getLogger(__name__)


class RagError(RuntimeError):
    """Raised when the absurd novel knowledge base cannot be initialized or queried."""


def initialize_absurd_novel_knowledge_base() -> RagInitResult:
    """Rebuild the local absurd novel knowledge base from source documents."""
    started = time.perf_counter()
    source_documents = indexing.scan_source_documents(config.SOURCE_DIR, error_type=RagError)
    chunks = indexing.build_chunks(source_documents)
    dense_collection = store.create_dense_collection(
        config.DENSE_DB_DIR, config.COLLECTION_NAME
    )
    sparse_database = store.create_sparse_database(config.SPARSE_DB_DIR)

    model = embeddings.load_embedding_model()
    for chunk_batch in _batched(chunks, config.BATCH_SIZE):
        texts = [chunk.text for chunk in chunk_batch]
        dense_vectors, sparse_vectors = embeddings.embed_texts(
            model, texts, config.BATCH_SIZE
        )
        store.upsert_dense_embeddings(dense_collection, chunk_batch, dense_vectors)
        store.upsert_sparse_embeddings(sparse_database, chunk_batch, sparse_vectors)

    return RagInitResult(
        document_count=len(source_documents),
        chunk_count=len(chunks),
        index_path=config.DB_DIR.resolve(),
        collection_name=config.COLLECTION_NAME,
        elapsed_seconds=time.perf_counter() - started,
    )


def query_absurd_novel_knowledge_base(query: str) -> list[str]:
    """Retrieve hybrid-ranked original snippets from the local knowledge base."""
    query = query.strip()
    if not query:
        raise RagError("query must not be empty")

    model = embeddings.load_embedding_model()
    dense_vectors, sparse_vectors = embeddings.embed_texts(
        model, [query], config.QUERY_BATCH_SIZE
    )

    try:
        dense_candidates = store.query_dense(
            config.DENSE_DB_DIR,
            config.COLLECTION_NAME,
            dense_vectors[0],
            config.DENSE_TOP_K,
        )
    except Exception as exc:
        logger.warning("Dense RAG retrieval failed: %s", exc)
        dense_candidates = []

    try:
        sparse_candidates = store.query_sparse(
            config.SPARSE_DB_DIR,
            sparse_vectors[0],
            config.SPARSE_TOP_K,
        )
    except Exception as exc:
        logger.warning("Sparse RAG retrieval failed: %s", exc)
        sparse_candidates = []

    fused_candidates = weighted_rrf(
        dense_candidates=dense_candidates,
        sparse_candidates=sparse_candidates,
        dense_weight=config.DENSE_WEIGHT,
        sparse_weight=config.SPARSE_WEIGHT,
        rrf_k=config.RRF_K,
        top_k=config.TOP_K,
    )
    return [candidate.text for candidate in fused_candidates]


# Backwards-compatible private alias used by older tests and local scripts.
def _scan_source_documents(source_dir):
    return indexing.scan_source_documents(source_dir, error_type=RagError)


def _batched(items: list[T], size: int) -> list[list[T]]:
    return [items[index : index + size] for index in range(0, len(items), size)]
