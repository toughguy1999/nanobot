"""Initialization and query service for the absurd novel knowledge base."""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any, TypeVar

import chromadb
import huggingface_hub
from FlagEmbedding import BGEM3FlagModel

from nanobot.rag import config
from nanobot.rag.types import RagInitResult, TextChunk

T = TypeVar("T")


class RagError(RuntimeError):
    """Raised when the absurd novel knowledge base cannot be initialized or queried."""


def initialize_absurd_novel_knowledge_base() -> RagInitResult:
    """Rebuild the local absurd novel knowledge base from source documents."""
    started = time.perf_counter()
    documents = _scan_source_documents(config.SOURCE_DIR)
    chunks = _build_chunks(documents)

    config.DB_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(config.DB_DIR))
    _reset_collection(client, config.COLLECTION_NAME)
    collection = client.get_or_create_collection(
        name=config.COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )

    model = _load_embedding_model()
    for chunk_batch in _batched(chunks, config.BATCH_SIZE):
        texts = [chunk.text for chunk in chunk_batch]
        embeddings = _embed_texts(model, texts, config.BATCH_SIZE)
        collection.upsert(
            ids=[_chunk_id(chunk) for chunk in chunk_batch],
            documents=texts,
            embeddings=embeddings,
            metadatas=[_chunk_metadata(chunk) for chunk in chunk_batch],
        )

    return RagInitResult(
        document_count=len(documents),
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

    collection = _load_collection(config.DB_DIR, config.COLLECTION_NAME)
    model = _load_embedding_model()
    query_embedding = _embed_texts(model, [query], config.QUERY_BATCH_SIZE)[0]
    result = collection.query(query_embeddings=[query_embedding], n_results=config.TOP_K)
    documents = result.get("documents") or [[]]
    return [document for document in documents[0] if document]


def _scan_source_documents(source_dir: Path) -> list[Path]:
    documents = sorted(
        path
        for path in source_dir.iterdir()
        if path.is_file() and path.suffix.lower() in config.SUPPORTED_EXTENSIONS
    )
    if not documents:
        raise RagError(f"No source documents found in {source_dir}")
    return documents


def _build_chunks(documents: list[Path]) -> list[TextChunk]:
    chunks: list[TextChunk] = []
    for document in documents:
        text = document.read_text(encoding="utf-8")
        if document.suffix.lower() == ".md":
            document_chunks = _chunk_markdown(text, document)
        else:
            document_chunks = _chunk_plain_text(text, document)
        chunks.extend(
            TextChunk(
                text=chunk.text,
                source_name=chunk.source_name,
                source_path=chunk.source_path,
                heading=chunk.heading,
                index=len(chunks) + index,
            )
            for index, chunk in enumerate(document_chunks)
        )
    return chunks


def _split_markdown_blocks(markdown: str) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    current_heading = "文档开头"
    buffer: list[str] = []

    def flush() -> None:
        if buffer:
            text = "\n".join(buffer).strip()
            if text:
                blocks.append((current_heading, text))
            buffer.clear()

    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped:
            flush()
            continue

        heading = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if heading:
            flush()
            current_heading = heading.group(2).strip()
            blocks.append((current_heading, stripped))
            continue

        buffer.append(stripped)

    flush()
    return blocks


def _chunk_markdown(markdown: str, source_path: Path) -> list[TextChunk]:
    return _chunk_blocks(_split_markdown_blocks(markdown), source_path)


def _chunk_plain_text(text: str, source_path: Path) -> list[TextChunk]:
    blocks = [("文档开头", block.strip()) for block in re.split(r"\n\s*\n", text) if block.strip()]
    return _chunk_blocks(blocks, source_path)


def _chunk_blocks(blocks: list[tuple[str, str]], source_path: Path) -> list[TextChunk]:
    chunks: list[TextChunk] = []
    current: list[str] = []
    current_len = 0
    current_heading = "文档开头"

    def emit() -> None:
        nonlocal current, current_len
        text = "\n\n".join(current).strip()
        if not text:
            current = []
            current_len = 0
            return
        chunks.append(
            TextChunk(
                text=text,
                source_name=source_path.name,
                source_path=source_path,
                heading=current_heading,
                index=len(chunks),
            )
        )
        tail = text[-config.CHUNK_OVERLAP :].strip() if config.CHUNK_OVERLAP else ""
        current = [tail] if tail else []
        current_len = len(tail)

    for heading, block in blocks:
        block_len = len(block)
        if current and current_len + block_len + 2 > config.CHUNK_SIZE:
            emit()

        current_heading = heading
        if block_len <= config.CHUNK_SIZE:
            current.append(block)
            current_len += block_len + 2
            continue

        step = config.CHUNK_SIZE - config.CHUNK_OVERLAP
        for start in range(0, block_len, step):
            piece = block[start : start + config.CHUNK_SIZE].strip()
            if not piece:
                continue
            if current:
                emit()
            chunks.append(
                TextChunk(
                    text=piece,
                    source_name=source_path.name,
                    source_path=source_path,
                    heading=heading,
                    index=len(chunks),
                )
            )

    if current:
        emit()
    return chunks


def _load_collection(db_dir: Path, collection_name: str) -> Any:
    client = chromadb.PersistentClient(path=str(db_dir))
    return client.get_collection(collection_name)


def _reset_collection(client: Any, collection_name: str) -> None:
    try:
        client.delete_collection(collection_name)
    except Exception:
        pass


def _load_embedding_model() -> Any:
    _ensure_model_downloaded()
    return BGEM3FlagModel(str(config.MODEL_DIR), use_fp16=config.USE_FP16, device=config.DEVICE)


def _ensure_model_downloaded() -> None:
    if _has_local_model(config.MODEL_DIR):
        return

    if config.HF_ENDPOINT:
        os.environ.setdefault("HF_ENDPOINT", config.HF_ENDPOINT)

    config.MODEL_DIR.mkdir(parents=True, exist_ok=True)
    huggingface_hub.snapshot_download(repo_id=config.MODEL_REPO, local_dir=str(config.MODEL_DIR))


def _has_local_model(model_dir: Path) -> bool:
    required_files = [
        "config.json",
        "tokenizer_config.json",
        "sentencepiece.bpe.model",
        "pytorch_model.bin",
    ]
    return model_dir.exists() and all((model_dir / file_name).is_file() for file_name in required_files)


def _embed_texts(model: Any, texts: list[str], batch_size: int) -> list[list[float]]:
    output = model.encode(texts, batch_size=batch_size, max_length=config.MAX_LENGTH)
    dense_vectors = output["dense_vecs"] if isinstance(output, dict) else output
    return [vector.tolist() if hasattr(vector, "tolist") else list(vector) for vector in dense_vectors]


def _batched(items: list[T], size: int) -> list[list[T]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def _chunk_id(chunk: TextChunk) -> str:
    return f"{chunk.source_name}:chunk:{chunk.index:05d}"


def _chunk_metadata(chunk: TextChunk) -> dict[str, str | int]:
    return {
        "source": chunk.source_name,
        "source_path": str(chunk.source_path),
        "heading": chunk.heading,
        "chunk_index": chunk.index,
        "chunk_size": len(chunk.text),
    }
