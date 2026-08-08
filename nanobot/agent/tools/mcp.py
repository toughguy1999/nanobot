"""Agent tool adapter for discovered MCP tools."""

import json
from typing import Any

from nanobot.agent.tools.base import Tool
from nanobot.mcp.manager import MCPManager
from nanobot.mcp.types import DiscoveredMCPTool, NormalizedMCPResult


class MCPTool(Tool):
    """Expose one discovered MCP tool through the standard agent Tool contract."""

    def __init__(self, descriptor: DiscoveredMCPTool, manager: MCPManager) -> None:
        self._descriptor = descriptor
        self._manager = manager

    @property
    def name(self) -> str:
        return f"mcp_{self._descriptor.server_name}_{self._descriptor.name}"

    @property
    def description(self) -> str:
        return self._descriptor.description

    @property
    def parameters(self) -> dict[str, Any]:
        return self._descriptor.input_schema

    async def execute(self, **kwargs: Any) -> str:
        result = await self._manager.call_tool(
            self._descriptor.server_name,
            self._descriptor.name,
            kwargs,
        )
        return self._project(result)

    @staticmethod
    def _project(result: NormalizedMCPResult) -> str:
        if result.is_error:
            message = result.error or (
                "\n".join(result.text) if result.text else "MCP tool call failed"
            )
            return json.dumps({"error": message}, ensure_ascii=False)
        if result.structured_content is not None:
            return json.dumps(result.structured_content, ensure_ascii=False)
        if len(result.text) == 1:
            return json.dumps(result.text[0], ensure_ascii=False)
        if result.text:
            return json.dumps(result.text, ensure_ascii=False)
        if result.unsupported_content:
            return json.dumps({"error": result.unsupported_content[0]}, ensure_ascii=False)
        return "null"
