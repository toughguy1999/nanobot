import json

import pytest

from nanobot.agent.tools.rag import AbsurdNovelKnowledgeSearchTool
from nanobot.agent.tools.registry import ToolRegistry


def test_rag_tool_schema():
    tool = AbsurdNovelKnowledgeSearchTool()

    assert tool.name == "absurd_novel_knowledge_search"
    assert tool.parameters["required"] == ["query"]
    assert tool.parameters["properties"]["query"]["type"] == "string"


async def test_rag_tool_returns_json_array(monkeypatch: pytest.MonkeyPatch):
    def fake_query(query: str) -> list[str]:
        assert query == "锅铲"
        return ["片段一", "片段二"]

    monkeypatch.setattr("nanobot.agent.tools.rag.query_absurd_novel_knowledge_base", fake_query)

    result = await AbsurdNovelKnowledgeSearchTool().execute("锅铲")

    assert json.loads(result) == ["片段一", "片段二"]


async def test_rag_tool_errors_flow_through_registry(monkeypatch: pytest.MonkeyPatch):
    def fake_query(query: str) -> list[str]:
        raise RuntimeError(f"boom: {query}")

    monkeypatch.setattr("nanobot.agent.tools.rag.query_absurd_novel_knowledge_base", fake_query)
    registry = ToolRegistry()
    registry.register(AbsurdNovelKnowledgeSearchTool())

    result = await registry.execute("absurd_novel_knowledge_search", {"query": "荒诞小说集"})

    assert result.startswith("Error executing absurd_novel_knowledge_search:")
    assert "boom: 荒诞小说集" in result
