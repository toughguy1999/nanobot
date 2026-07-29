"""Dense Chroma and sparse SQLite storage for local RAG."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from threading import Lock
from typing import Any, cast

import chromadb

from nanobot.rag.types import RetrievalCandidate, SparseVector, TextChunk

_SPARSE_DB_FILENAME = "sparse.db"

_dense_collection: Any | None = None
_dense_client: Any | None = None
_dense_collection_key: tuple[Path, str] | None = None
_dense_collection_lock = Lock()


def create_dense_collection(db_dir: Path, collection_name: str) -> Any:
    """Reset and create the target Chroma collection."""
    global _dense_client, _dense_collection, _dense_collection_key

    db_dir.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(db_dir))
    reset_dense_collection(client, collection_name)
    collection = client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )
    with _dense_collection_lock:
        _dense_client = client
        _dense_collection = collection
        _dense_collection_key = (db_dir.resolve(), collection_name)
    return collection


def load_dense_collection(db_dir: Path, collection_name: str) -> Any:
    """Return the process-lifetime Chroma collection for the requested index."""
    global _dense_client, _dense_collection, _dense_collection_key

    key = (db_dir.resolve(), collection_name)
    if _dense_collection is None or _dense_collection_key != key:
        with _dense_collection_lock:
            if _dense_collection is None or _dense_collection_key != key:
                _dense_client = chromadb.PersistentClient(path=str(db_dir))
                _dense_collection = _dense_client.get_collection(collection_name)
                _dense_collection_key = key
    return _dense_collection


def reset_dense_collection(client: Any, collection_name: str) -> None:
    """Delete the collection if it exists."""
    try:
        client.delete_collection(collection_name)
    except Exception:
        pass


def upsert_dense_embeddings(
    collection: Any,
    chunks: list[TextChunk],
    embeddings: list[list[float]],
) -> None:
    """Write a batch of dense chunk embeddings into Chroma."""
    if len(chunks) != len(embeddings):
        raise ValueError("chunks and dense embeddings must have equal lengths")
    collection.upsert(
        ids=[chunk.id for chunk in chunks],
        documents=[chunk.text for chunk in chunks],
        embeddings=embeddings,
        metadatas=[chunk.metadata for chunk in chunks],
    )


def query_dense(
    db_dir: Path,
    collection_name: str,
    query_embedding: list[float],
    top_k: int,
) -> list[RetrievalCandidate]:
    """Load and query Chroma, converting its result into ranked candidates."""
    collection = load_dense_collection(db_dir, collection_name)
    result = collection.query(query_embeddings=[query_embedding], n_results=top_k)
    ids = _first_result_list(result, "ids")
    documents = _first_result_list(result, "documents")
    metadatas = _first_result_list(result, "metadatas")

    candidates: list[RetrievalCandidate] = []
    for index, chunk_id in enumerate(ids):
        if not isinstance(chunk_id, str) or index >= len(documents):
            continue
        document = documents[index]
        if not isinstance(document, str):
            continue
        raw_metadata = metadatas[index] if index < len(metadatas) else {}
        candidates.append(
            RetrievalCandidate(
                chunk_id=chunk_id,
                text=document,
                metadata=_normalize_metadata(raw_metadata),
                rank=index + 1,
            )
        )
    return candidates


def create_sparse_database(db_dir: Path) -> Path:
    """Reset the SQLite sparse index and return its database path."""
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / _SPARSE_DB_FILENAME
    with _connect_sparse(db_path) as connection:
        connection.executescript(
            """
            DROP TABLE IF EXISTS sparse_postings;
            DROP TABLE IF EXISTS chunks;

            CREATE TABLE chunks (
                chunk_id TEXT PRIMARY KEY,
                document TEXT NOT NULL,
                metadata_json TEXT NOT NULL
            );

            CREATE TABLE sparse_postings (
                token_id INTEGER NOT NULL,
                chunk_id TEXT NOT NULL,
                weight REAL NOT NULL,
                PRIMARY KEY (token_id, chunk_id),
                FOREIGN KEY (chunk_id) REFERENCES chunks(chunk_id)
            );

            CREATE INDEX idx_sparse_postings_token_id
                ON sparse_postings(token_id);
            """
        )
    return db_path

def upsert_sparse_embeddings(
    db_path: Path,
    chunks: list[TextChunk],
    sparse_vectors: list[SparseVector],
) -> None:
    """Write chunk records and sparse postings in one transaction."""
    if len(chunks) != len(sparse_vectors):
        raise ValueError("chunks and sparse embeddings must have equal lengths")

    chunk_rows = [
        (
            chunk.id,
            chunk.text,
            json.dumps(chunk.metadata, ensure_ascii=False, sort_keys=True),
        )
        for chunk in chunks
    ]
    posting_rows = [
        (token_id, chunk.id, weight)
        for chunk, sparse_vector in zip(chunks, sparse_vectors, strict=True)
        for token_id, weight in sparse_vector.items()
    ]

    with _connect_sparse(db_path) as connection:
        connection.executemany(
            """
            INSERT INTO chunks (chunk_id, document, metadata_json)
            VALUES (?, ?, ?)
            ON CONFLICT(chunk_id) DO UPDATE SET
                document = excluded.document,
                metadata_json = excluded.metadata_json
            """,
            chunk_rows,
        )
        connection.executemany(
            """
            INSERT INTO sparse_postings (token_id, chunk_id, weight)
            VALUES (?, ?, ?)
            ON CONFLICT(token_id, chunk_id) DO UPDATE SET
                weight = excluded.weight
            """,
            posting_rows,
        )


def query_sparse(
    db_dir: Path,
    query_vector: SparseVector,
    top_k: int,
) -> list[RetrievalCandidate]:
    """Load SQLite and return chunks ranked by sparse token-weight dot product."""
    if not query_vector or top_k <= 0:
        return []

    db_path = db_dir / _SPARSE_DB_FILENAME
    with _connect_sparse(db_path) as connection:
        connection.execute(
            """
            CREATE TEMP TABLE query_terms (
                token_id INTEGER PRIMARY KEY,
                weight REAL NOT NULL
            )
            """
        )
        connection.executemany(
            "INSERT INTO query_terms (token_id, weight) VALUES (?, ?)",
            query_vector.items(),
        )
        rows = connection.execute(
            """
            SELECT
                chunks.chunk_id,
                chunks.document,
                chunks.metadata_json,
                SUM(sparse_postings.weight * query_terms.weight) AS sparse_score
            FROM query_terms
            JOIN sparse_postings USING (token_id)
            JOIN chunks USING (chunk_id)
            GROUP BY chunks.chunk_id, chunks.document, chunks.metadata_json
            ORDER BY sparse_score DESC, chunks.chunk_id ASC
            LIMIT ?
            """,
            (top_k,),
        ).fetchall()

    return [
        RetrievalCandidate(
            chunk_id=str(row["chunk_id"]),
            text=str(row["document"]),
            metadata=_decode_metadata(str(row["metadata_json"])),
            rank=rank,
        )
        for rank, row in enumerate(rows, start=1)
    ]


def _connect_sparse(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _first_result_list(result: Any, key: str) -> list[Any]:
    values = result.get(key) or [[]]
    return cast(list[Any], values[0] or [])


def _normalize_metadata(value: Any) -> dict[str, str | int]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): item
        for key, item in value.items()
        if isinstance(item, (str, int)) and not isinstance(item, bool)
    }


def _decode_metadata(value: str) -> dict[str, str | int]:
    return _normalize_metadata(json.loads(value))
