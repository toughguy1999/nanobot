from pathlib import Path

import pytest

from nanobot.rag import config
from nanobot.rag.service import (
    RagError,
    _scan_source_documents,
    initialize_absurd_novel_knowledge_base,
    query_absurd_novel_knowledge_base,
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


def test_initialize_result_contains_counts_and_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "novel.md").write_text("# 第一章\n\n误会开始了。", encoding="utf-8")
    db_dir = tmp_path / "db"

    upserts: list[dict[str, object]] = []

    class FakeCollection:
        def upsert(self, **kwargs: object) -> None:
            upserts.append(kwargs)

    class FakeClient:
        def __init__(self, path: str):
            self.path = path

        def delete_collection(self, name: str) -> None:
            raise Exception("not found")

        def get_or_create_collection(self, **kwargs: object) -> FakeCollection:
            return FakeCollection()

    class FakeChroma:
        PersistentClient = FakeClient

    class FakeModel:
        def encode(
            self, texts: list[str], batch_size: int, max_length: int
        ) -> dict[str, list[list[float]]]:
            return {"dense_vecs": [[1.0, 0.0] for _ in texts]}

    monkeypatch.setattr(config, "SOURCE_DIR", source_dir)
    monkeypatch.setattr(config, "DB_DIR", db_dir)
    monkeypatch.setattr("nanobot.rag.store.chromadb.PersistentClient", FakeChroma.PersistentClient)
    monkeypatch.setattr("nanobot.rag.embeddings.load_embedding_model", lambda: FakeModel())

    result = initialize_absurd_novel_knowledge_base()

    assert result.document_count == 1
    assert result.chunk_count >= 1
    assert result.index_path == db_dir.resolve()
    assert result.collection_name == config.COLLECTION_NAME
    assert result.elapsed_seconds >= 0
    assert upserts


def test_query_empty_query_fails():
    with pytest.raises(RagError, match="query must not be empty"):
        query_absurd_novel_knowledge_base("   ")
