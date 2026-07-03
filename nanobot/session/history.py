"""Canonical session history records and conversions."""

from __future__ import annotations

import json
from typing import Any, Literal, TypeAlias, TypedDict, cast

from loguru import logger

from nanobot.session.blobs import SessionBlobStore


class HistoryMessage(TypedDict, total=False):
    """A user-visible conversational message stored in session history."""

    _type: Literal["message"]
    id: str
    role: Literal["user", "assistant", "system"]
    content: str | list[dict[str, Any]]
    created_at: str
    display_content: str
    attachments: list[dict[str, Any]]


class HistoryToolCall(TypedDict):
    """A single assistant tool call record."""

    _type: Literal["tool_call"]
    id: str
    type: Literal["function"]
    function: dict[str, str]
    content: str
    created_at: str


class HistoryToolResult(TypedDict):
    """A single tool execution result record."""

    _type: Literal["tool_result"]
    role: Literal["tool"]
    tool_call_id: str
    name: str
    content: str
    created_at: str


HistoryRecord: TypeAlias = HistoryMessage | HistoryToolCall | HistoryToolResult


def to_llm_messages(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert canonical history records into provider chat messages."""
    messages: list[dict[str, Any]] = []
    pending_tool_calls: list[dict[str, Any]] = []
    pending_content = ""

    def flush_tool_calls() -> None:
        nonlocal pending_content
        if not pending_tool_calls:
            return
        messages.append({
            "role": "assistant",
            "content": pending_content,
            "tool_calls": pending_tool_calls.copy(),
        })
        pending_tool_calls.clear()
        pending_content = ""

    for record in history:
        record_type = record.get("_type")
        if record_type == "tool_call":
            if not pending_tool_calls:
                pending_content = str(record.get("content") or "")
            pending_tool_calls.append({
                "id": record["id"],
                "type": record.get("type", "function"),
                "function": record["function"],
            })
            continue

        flush_tool_calls()

        if record_type == "message":
            role = record.get("role")
            content = _llm_content(record.get("content", ""))
            if role == "system":
                messages.append({"role": "user", "content": f"[System: {content}]"})
            elif role in {"user", "assistant"}:
                messages.append({"role": role, "content": content})
            continue

        if record_type == "tool_result":
            messages.append({
                "role": "tool",
                "tool_call_id": record["tool_call_id"],
                "name": record.get("name", ""),
                "content": record.get("content", ""),
            })

    flush_tool_calls()
    return messages


def to_memory_transcript(history: list[dict[str, Any]]) -> str:
    """Render canonical history into a compact transcript for consolidation."""
    lines: list[str] = []
    for record in history:
        created_at = str(record.get("created_at") or "?")[:16]
        record_type = record.get("_type")
        if record_type == "message":
            role = str(record.get("role", "message")).upper()
            content = _text_content(record.get("display_content", record.get("content", "")))
            if content:
                lines.append(f"[{created_at}] {role}: {content}")
        elif record_type == "tool_call":
            function = record.get("function") or {}
            name = function.get("name", "")
            arguments = _summarize(function.get("arguments", ""))
            lines.append(f"[{created_at}] TOOL_CALL {name}: {arguments}")
        elif record_type == "tool_result":
            name = record.get("name", "")
            tool_call_id = record.get("tool_call_id", "")
            content = _summarize(record.get("content", ""))
            lines.append(f"[{created_at}] TOOL_RESULT {name} ({tool_call_id}): {content}")
    return "\n".join(lines)


def trim_boundary(history: list[dict[str, Any]], keep_count: int) -> list[dict[str, Any]]:
    """Return a suffix that does not orphan tool calls or tool results."""
    if keep_count <= 0:
        return []
    if keep_count >= len(history):
        return list(history)

    start = len(history) - keep_count
    first = history[start]
    if first.get("_type") == "tool_result":
        tool_call_id = first.get("tool_call_id")
        for index in range(start - 1, -1, -1):
            previous = history[index]
            if previous.get("_type") == "tool_call" and previous.get("id") == tool_call_id:
                start = index
                break
    candidate = list(history[start:])

    while candidate and candidate[0].get("_type") == "tool_result":
        candidate.pop(0)

    included_tool_calls = {
        str(record.get("id"))
        for record in candidate
        if record.get("_type") == "tool_call"
    }
    candidate = [
        record
        for record in candidate
        if record.get("_type") != "tool_result"
        or str(record.get("tool_call_id")) in included_tool_calls
    ]

    result_ids = {
        str(record.get("tool_call_id"))
        for record in candidate
        if record.get("_type") == "tool_result"
    }
    candidate = [
        record
        for record in candidate
        if record.get("_type") != "tool_call"
        or str(record.get("id")) in result_ids
    ]

    while candidate and candidate[0].get("_type") == "tool_result":
        candidate.pop(0)

    return candidate


def validate_history_record(record: dict[str, Any]) -> HistoryRecord:
    """Validate a JSON object enough to fail diagnostically on unknown records."""
    record_type = record.get("_type")
    if record_type == "message":
        if record.get("role") not in {"user", "assistant", "system"}:
            raise ValueError(f"invalid message role: {record.get('role')}")
        if "id" not in record or "content" not in record or "created_at" not in record:
            raise ValueError("message record requires id, content, and created_at")
        return cast(HistoryRecord, record)
    if record_type == "tool_call":
        if "id" not in record or not isinstance(record.get("function"), dict):
            raise ValueError("tool_call record requires id and function")
        return cast(HistoryRecord, record)
    if record_type == "tool_result":
        if "tool_call_id" not in record or "content" not in record:
            raise ValueError("tool_result record requires tool_call_id and content")
        return cast(HistoryRecord, record)
    raise ValueError(f"unknown history record type: {record_type}")


def _text_content(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
        return "\n".join(part for part in parts if part)
    return str(content) if content is not None else ""


def _llm_content(content: object) -> str | list[dict[str, Any]]:
    if not isinstance(content, list):
        return str(content) if content is not None else ""

    store = SessionBlobStore()
    converted: list[dict[str, Any]] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "image_url":
            image_url = item.get("image_url")
            if isinstance(image_url, dict) and isinstance(image_url.get("blob"), dict):
                try:
                    converted.append({
                        "type": "image_url",
                        "image_url": {"url": store.read_data_url(image_url["blob"])},
                    })
                except Exception as exc:
                    logger.warning(f"Skipping unavailable session image blob: {exc}")
                continue
        converted.append(item)
    return converted


def _summarize(value: object, limit: int = 500) -> str:
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False)
    value = value.replace("\n", "\\n")
    if len(value) <= limit:
        return value
    return f"{value[:limit]}..."
