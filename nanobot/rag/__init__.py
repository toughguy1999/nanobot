"""RAG runtime for the absurd novel knowledge base."""

from nanobot.rag.service import (
    RagError,
    initialize_absurd_novel_knowledge_base,
    query_absurd_novel_knowledge_base,
)
from nanobot.rag.types import RagInitResult

__all__ = [
    "RagError",
    "RagInitResult",
    "initialize_absurd_novel_knowledge_base",
    "query_absurd_novel_knowledge_base",
]
