"""Initialization and query orchestration for the absurd novel knowledge base."""

from __future__ import annotations

import time
from typing import TypeVar

from nanobot.rag import config, embeddings, indexing, store
from nanobot.rag.types import RagInitResult

T = TypeVar("T")


class RagError(RuntimeError):
    """Raised when the absurd novel knowledge base cannot be initialized or queried."""


def initialize_absurd_novel_knowledge_base() -> RagInitResult:
    """Rebuild the local absurd novel knowledge base from source documents."""
    started = time.perf_counter()
    source_documents = indexing.scan_source_documents(config.SOURCE_DIR, error_type=RagError)
    chunks = indexing.build_chunks(source_documents)
    collection = store.create_collection(config.DB_DIR, config.COLLECTION_NAME)

    model = embeddings.load_embedding_model()
    for chunk_batch in _batched(chunks, config.BATCH_SIZE):
        texts = [chunk.text for chunk in chunk_batch]
        chunk_embeddings = embeddings.embed_texts(model, texts, config.BATCH_SIZE)
        store.upsert_embeddings(
            collection=collection,
            ids=[chunk.id for chunk in chunk_batch],
            documents=texts,
            embeddings=chunk_embeddings,
            metadatas=[chunk.metadata for chunk in chunk_batch],
        )

    return RagInitResult(
        document_count=len(source_documents),
        chunk_count=len(chunks),
        index_path=config.DB_DIR.resolve(),
        collection_name=config.COLLECTION_NAME,
        elapsed_seconds=time.perf_counter() - started,
    )


def query_absurd_novel_knowledge_base(query: str) -> list[str]:
    """Retrieve original text snippets from the local absurd novel knowledge base."""
    query = query.strip()
    if not query:
        raise RagError("query must not be empty")

    collection = store.load_collection(config.DB_DIR, config.COLLECTION_NAME)
    model = embeddings.load_embedding_model()
    query_embedding = embeddings.embed_texts(model, [query], config.QUERY_BATCH_SIZE)[0]
    result = collection.query(query_embeddings=[query_embedding], n_results=config.TOP_K)
    documents_result = result.get("documents") or [[]]
    return [document for document in documents_result[0] if document]


# Backwards-compatible private aliases used by older tests and local scripts.
def _scan_source_documents(source_dir):
    return indexing.scan_source_documents(source_dir, error_type=RagError)


def _batched(items: list[T], size: int) -> list[list[T]]:
    return [items[index : index + size] for index in range(0, len(items), size)]
