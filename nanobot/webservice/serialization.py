"""Canonical history serializers shared by HTTP and WebSocket delivery."""

from typing import Any


def serialize_assistant_record(record: dict[str, Any]) -> dict[str, Any]:
    """Serialize one persisted assistant record into the browser message DTO."""
    message: dict[str, Any] = {
        "id": record["id"],
        "role": "assistant",
        "content": str(record.get("content") or ""),
        "createdAt": record["created_at"],
    }
    if reasoning := record.get("reasoning_content"):
        message["reasoningContent"] = reasoning
    if tool_calls := record.get("tool_calls"):
        message["toolCalls"] = [
            {
                "id": tool_call["id"],
                "name": tool_call["function"]["name"],
                "arguments": tool_call["function"]["arguments"],
            }
            for tool_call in tool_calls
        ]
    return message


def serialize_user_record(record: dict[str, Any]) -> dict[str, Any]:
    """Serialize one persisted user record into the browser message DTO."""
    message: dict[str, Any] = {
        "id": record["id"],
        "role": "user",
        "content": _display_content(record),
        "createdAt": record["created_at"],
    }
    if attachments := record.get("attachments"):
        message["attachments"] = attachments
    return message


def _display_content(record: dict[str, Any]) -> str:
    display_content = record.get("display_content")
    if isinstance(display_content, str):
        return display_content
    content = record.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(item.get("text", ""))
            for item in content
            if isinstance(item, dict) and item.get("type") == "text" and item.get("text")
        )
    return str(content) if content is not None else ""
