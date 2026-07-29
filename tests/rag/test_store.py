import sqlite3
from pathlib import Path
from typing import Any

import pytest

from nanobot.rag import store
from nanobot.rag.types import TextChunk


def _chunk(tmp_path: Path, name: str, index: int, text: str) -> TextChunk:
    return TextChunk(
        text=text,
        source_name=name,
        source_path=tmp_path / name,
        index=index,
    )


def test_dense_store_uses_requested_path_and_returns_candidates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[dict[str, Any]] = []

    class FakeCollection:
        def upsert(self, **kwargs: Any) -> None:
            calls.append({"upsert": kwargs})

        def query(self, **kwargs: Any) -> dict[str, Any]:
            calls.append({"query": kwargs})
            return {
                "ids": [["b:chunk:00001", "a:chunk:00000"]],
                "documents": [["B", "A"]],
                "metadatas": [[{"source": "b"}, {"source": "a", "chunk_index": 0}]],
            }

    collection = FakeCollection()

    class FakeClient:
        def __init__(self, path: str):
            calls.append({"path": path})

        def delete_collection(self, name: str) -> None:
            calls.append({"delete": name})

        def get_or_create_collection(self, **kwargs: Any) -> FakeCollection:
            calls.append({"create": kwargs})
            return collection

    monkeypatch.setattr(store.chromadb, "PersistentClient", FakeClient)
    dense_dir = tmp_path / "db" / "chroma"
    created = store.create_dense_collection(dense_dir, "chunks")
    chunks = [_chunk(tmp_path, "a", 0, "A")]

    store.upsert_dense_embeddings(created, chunks, [[1.0, 0.0]])
    candidates = store.query_dense(dense_dir, "chunks", [0.5, 0.5], top_k=2)

    assert calls[0] == {"path": str(dense_dir)}
    assert calls[2] == {
        "create": {"name": "chunks", "metadata": {"hnsw:space": "cosine"}}
    }
    assert calls[3]["upsert"]["ids"] == [chunks[0].id]
    assert calls[4] == {"query": {"query_embeddings": [[0.5, 0.5]], "n_results": 2}}
    assert [(candidate.chunk_id, candidate.rank) for candidate in candidates] == [
        ("b:chunk:00001", 1),
        ("a:chunk:00000", 2),
    ]
    assert candidates[1].text == "A"
    assert candidates[1].metadata == {"source": "a", "chunk_index": 0}


def test_sparse_store_writes_and_ranks_dot_products(tmp_path: Path) -> None:
    sparse_dir = tmp_path / "db" / "sqlite"
    db_path = store.create_sparse_database(sparse_dir)
    chunks = [
        _chunk(tmp_path, "b.txt", 0, "B"),
        _chunk(tmp_path, "a.txt", 1, "A"),
        _chunk(tmp_path, "c.txt", 2, "C"),
    ]

    store.upsert_sparse_embeddings(
        db_path,
        chunks,
        [
            {10: 2.0},
            {10: 1.0, 20: 1.0},
            {10: 1.0, 20: 1.0},
        ],
    )

    candidates = store.query_sparse(sparse_dir, {10: 1.0, 20: 2.0}, top_k=2)

    assert db_path == sparse_dir / "sparse.db"
    assert store.load_sparse_database(sparse_dir) == db_path
    assert [candidate.chunk_id for candidate in candidates] == [
        chunks[1].id,
        chunks[2].id,
    ]
    assert [candidate.rank for candidate in candidates] == [1, 2]
    assert candidates[0].text == chunks[1].text
    assert candidates[0].metadata == chunks[1].metadata

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM chunks").fetchone() == (3,)
        assert connection.execute("SELECT COUNT(*) FROM sparse_postings").fetchone() == (5,)


def test_sparse_store_rejects_mismatched_batch_lengths(tmp_path: Path) -> None:
    db_path = store.create_sparse_database(tmp_path)

    with pytest.raises(ValueError, match="equal lengths"):
        store.upsert_sparse_embeddings(
            db_path,
            [_chunk(tmp_path, "a.txt", 0, "A")],
            [],
        )
