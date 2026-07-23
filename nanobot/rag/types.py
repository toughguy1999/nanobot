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
    index: int

    @property
    def id(self) -> str:
        """Stable vector-store id for this chunk."""
        return f"{self.source_name}:chunk:{self.index:05d}"

    @property
    def metadata(self) -> dict[str, str | int]:
        """Vector-store metadata for this chunk."""
        return {
            "source": self.source_name,
            "source_path": str(self.source_path),
            "chunk_index": self.index,
            "chunk_size": len(self.text),
        }
