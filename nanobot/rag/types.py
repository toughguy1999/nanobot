"""Lightweight data structures for RAG operations."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RagInitResult:
    """Result returned after rebuilding the absurd novel knowledge base."""

    document_count: int
    chunk_count: int
    index_path: Path
    collection_name: str
    elapsed_seconds: float


@dataclass(frozen=True)
class TextChunk:
    """Internal chunk representation for indexing."""

    text: str
    source_name: str
    source_path: Path
    heading: str
    index: int
