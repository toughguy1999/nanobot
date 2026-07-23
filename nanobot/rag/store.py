"""Chroma vector-store access for local RAG."""

from pathlib import Path
from threading import Lock
from typing import Any

import chromadb

_collection: Any | None = None
_client: Any | None = None
_collection_lock = Lock()


def create_collection(db_dir: Path, collection_name: str) -> Any:
    """Reset and create the target Chroma collection."""
    db_dir.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(db_dir))
    reset_collection(client, collection_name)
    return client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )


def load_collection(db_dir: Path, collection_name: str) -> Any:
    """Return the process-lifetime Chroma collection singleton."""
    global _client, _collection

    if _collection is None:
        with _collection_lock:
            if _collection is None:
                _client = chromadb.PersistentClient(path=str(db_dir))
                _collection = _client.get_collection(collection_name)
    return _collection


def reset_collection(client: Any, collection_name: str) -> None:
    """Delete the collection if it exists."""
    try:
        client.delete_collection(collection_name)
    except Exception:
        pass


def upsert_embeddings(
    collection: Any,
    ids: list[str],
    documents: list[str],
    embeddings: list[list[float]],
    metadatas: list[dict[str, str | int]],
) -> None:
    """Write embedded documents into the collection."""
    collection.upsert(
        ids=ids,
        documents=documents,
        embeddings=embeddings,
        metadatas=metadatas,
    )
