"""Agent tool for querying the absurd novel knowledge base."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from nanobot.harness.tools.base import Tool
from nanobot.rag import query_absurd_novel_knowledge_base


class AbsurdNovelKnowledgeSearchTool(Tool):
    """Search local original snippets from the absurd novel knowledge base."""

    @property
    def name(self) -> str:
        return "absurd_novel_knowledge_search"

    @property
    def description(self) -> str:
        return (
            "Search the local 荒诞小说集知识库. Use this when the user mentions "
            "荒诞小说集 and asks about its content, facts, plot, characters, chapters, "
            "or wording."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The question or search query about 荒诞小说集.",
                }
            },
            "required": ["query"],
        }

    def isConcurrencySafe(self, params: dict[str, Any]) -> bool:  # noqa: N802
        return True

    async def execute(self, query: str) -> str:
        snippets = await asyncio.to_thread(query_absurd_novel_knowledge_base, query)
        return json.dumps(snippets, ensure_ascii=False)
