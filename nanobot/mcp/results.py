"""Normalize MCP SDK tool results into nanobot's protocol-neutral form."""

from typing import Any

from nanobot.mcp.types import NormalizedMCPResult


def normalize_call_tool_result(result: Any) -> NormalizedMCPResult:
    """Convert an SDK ``CallToolResult`` without retaining rich payload bodies."""

    text: list[str] = []
    unsupported: list[str] = []

    for block in getattr(result, "content", ()) or ():
        content_type = getattr(block, "type", type(block).__name__)
        if content_type == "text":
            text.append(str(getattr(block, "text", "")))
        else:
            unsupported.append(f"MCP {content_type} content is not supported")

    is_error = bool(getattr(result, "is_error", False))
    error = "\n".join(text) if is_error and text else None
    return NormalizedMCPResult(
        is_error=is_error,
        text=text,
        structured_content=getattr(result, "structured_content", None),
        unsupported_content=unsupported,
        error=error,
    )
