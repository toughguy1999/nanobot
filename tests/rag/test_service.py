import sqlite3
from pathlib import Path
from typing import Any, cast

import pytest

from nanobot.rag import config
from nanobot.rag.service import (
    RagError,
    _scan_source_documents,
    initialize_absurd_novel_knowledge_base,
    query_absurd_novel_knowledge_base,
)
from nanobot.rag.types import RetrievalCandidate


def _candidate(chunk_id: str, text: str, rank: int) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=chunk_id,
        text=text,
        metadata={"source": f"{chunk_id}.txt"},
        rank=rank,
    )


def test_scan_source_documents_requires_text_documents(tmp_path: Path):
    (tmp_path / "ignored.pdf").write_text("nope", encoding="utf-8")

    with pytest.raises(RagError, match="No source documents"):
        _scan_source_documents(tmp_path)


def test_scan_source_documents_only_includes_md_and_txt(tmp_path: Path):
    md = tmp_path / "a.md"
    txt = tmp_path / "b.txt"
    pdf = tmp_path / "c.pdf"
    md.write_text("# A", encoding="utf-8")
    txt.write_text("B", encoding="utf-8")
    pdf.write_text("C", encoding="utf-8")

    assert _scan_source_documents(tmp_path) == [md, txt]


def test_initialize_builds_dense_and_sparse_indexes_from_same_chunks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "novel.md").write_text("# 第一章\n\n误会开始了。", encoding="utf-8")
    db_dir = tmp_path / "db"
    dense_dir = db_dir / "chroma"
    sparse_dir = db_dir / "sqlite"

    upserts: list[dict[str, object]] = []

    class FakeCollection:
        def upsert(self, **kwargs: object) -> None:
            upserts.append(kwargs)

    class FakeClient:
        def __init__(self, path: str):
            assert path == str(dense_dir)

        def delete_collection(self, name: str) -> None:
            raise Exception("not found")

        def get_or_create_collection(self, **kwargs: object) -> FakeCollection:
            return FakeCollection()

    class FakeModel:
        def encode(self, texts: list[str], **kwargs: Any) -> dict[str, Any]:
            assert kwargs["return_dense"] is True
            assert kwargs["return_sparse"] is True
            return {
                "dense_vecs": [[1.0, 0.0] for _ in texts],
                "lexical_weights": [{"42": 0.5} for _ in texts],
            }

    monkeypatch.setattr(config, "SOURCE_DIR", source_dir)
    monkeypatch.setattr(config, "DB_DIR", db_dir)
    monkeypatch.setattr(config, "DENSE_DB_DIR", dense_dir)
    monkeypatch.setattr(config, "SPARSE_DB_DIR", sparse_dir)
    monkeypatch.setattr("nanobot.rag.store.chromadb.PersistentClient", FakeClient)
    monkeypatch.setattr("nanobot.rag.embeddings.load_embedding_model", lambda: FakeModel())

    result = initialize_absurd_novel_knowledge_base()

    assert result.document_count == 1
    assert result.chunk_count >= 1
    assert result.index_path == db_dir.resolve()
    assert result.collection_name == config.COLLECTION_NAME
    assert result.elapsed_seconds >= 0
    dense_ids = cast(list[str], upserts[0]["ids"])
    with sqlite3.connect(sparse_dir / "sparse.db") as connection:
        sparse_ids = [
            row[0]
            for row in connection.execute(
                "SELECT chunk_id FROM chunks ORDER BY chunk_id"
            ).fetchall()
        ]
    assert sorted(dense_ids) == sparse_ids


def test_query_uses_branch_top_k_and_returns_fused_top_k(
    monkeypatch: pytest.MonkeyPatch,
):
    encode_calls: list[list[str]] = []
    query_calls: list[tuple[str, int]] = []

    class FakeModel:
        def encode(self, texts: list[str], **kwargs: Any) -> dict[str, Any]:
            encode_calls.append(texts)
            return {
                "dense_vecs": [[1.0]],
                "lexical_weights": [{"1": 1.0}],
            }

    dense = [_candidate(f"dense-{index}", f"D{index}", index + 1) for index in range(5)]
    sparse = [
        *[_candidate(f"sparse-{index}", f"S{index}", index + 1) for index in range(4)],
        _candidate("dense-4", "D4", 5),
    ]

    monkeypatch.setattr("nanobot.rag.embeddings.load_embedding_model", lambda: FakeModel())
    def fake_dense(
        _db_dir: Path,
        _collection_name: str,
        _query: list[float],
        top_k: int,
    ):
        query_calls.append(("dense", top_k))
        return dense

    def fake_sparse(_db_dir: Path, _query: dict[int, float], top_k: int):
        query_calls.append(("sparse", top_k))
        return sparse

    monkeypatch.setattr("nanobot.rag.store.query_dense", fake_dense)
    monkeypatch.setattr("nanobot.rag.store.query_sparse", fake_sparse)

    result = query_absurd_novel_knowledge_base("  query  ")

    assert encode_calls == [["query"]]
    assert query_calls == [("dense", 5), ("sparse", 5)]
    assert result == ["D4", "D0", "S0"]


@pytest.mark.parametrize("failed_branch", ["dense", "sparse"])
def test_query_degrades_when_one_branch_fails(
    monkeypatch: pytest.MonkeyPatch, failed_branch: str
):
    class FakeModel:
        def encode(self, texts: list[str], **kwargs: Any) -> dict[str, Any]:
            return {
                "dense_vecs": [[1.0]],
                "lexical_weights": [{"1": 1.0}],
            }

    monkeypatch.setattr("nanobot.rag.embeddings.load_embedding_model", lambda: FakeModel())
    def dense_query(*_args: object):
        if failed_branch == "dense":
            raise RuntimeError("dense failed")
        return [_candidate("dense", "dense result", 1)]

    def sparse_query(*_args: object):
        if failed_branch == "sparse":
            raise RuntimeError("sparse failed")
        return [_candidate("sparse", "sparse result", 1)]

    monkeypatch.setattr("nanobot.rag.store.query_dense", dense_query)
    monkeypatch.setattr("nanobot.rag.store.query_sparse", sparse_query)

    result = query_absurd_novel_knowledge_base("query")

    assert result == [f"{'sparse' if failed_branch == 'dense' else 'dense'} result"]


def test_query_returns_empty_list_when_both_branches_have_no_candidates(
    monkeypatch: pytest.MonkeyPatch,
):
    class FakeModel:
        def encode(self, texts: list[str], **kwargs: Any) -> dict[str, Any]:
            return {
                "dense_vecs": [[1.0]],
                "lexical_weights": [{"1": 1.0}],
            }

    monkeypatch.setattr("nanobot.rag.embeddings.load_embedding_model", lambda: FakeModel())
    monkeypatch.setattr("nanobot.rag.store.query_dense", lambda *_: [])
    monkeypatch.setattr("nanobot.rag.store.query_sparse", lambda *_: [])

    assert query_absurd_novel_knowledge_base("query") == []


def test_query_empty_query_fails():
    with pytest.raises(RagError, match="query must not be empty"):
        query_absurd_novel_knowledge_base("   ")
