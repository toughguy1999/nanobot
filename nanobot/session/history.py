"""Canonical role-based session history records and conversions."""

from __future__ import annotations

import json
from typing import Any, Literal, TypeAlias, TypedDict, cast

from loguru import logger

from nanobot.session.blobs import SessionBlobStore


class ToolFunction(TypedDict):
    """Provider-compatible tool function payload."""

    name: str
    arguments: str


class AssistantToolCall(TypedDict):
    """A tool call owned by an assistant history record."""

    id: str
    type: Literal["function"]
    function: ToolFunction


class UserHistoryRecord(TypedDict, total=False):
    id: str
    role: Literal["user"]
    content: str | list[dict[str, Any]]
    created_at: str
    display_content: str
    attachments: list[dict[str, Any]]


class AssistantHistoryRecord(TypedDict, total=False):
    id: str
    role: Literal["assistant"]
    content: str
    created_at: str
    reasoning_content: str
    tool_calls: list[AssistantToolCall]


class ToolHistoryRecord(TypedDict):
    id: str
    role: Literal["tool"]
    tool_call_id: str
    name: str
    content: str
    created_at: str


class SystemHistoryRecord(TypedDict):
    id: str
    role: Literal["system"]
    content: str
    created_at: str


HistoryRecord: TypeAlias = (
    UserHistoryRecord | AssistantHistoryRecord | ToolHistoryRecord | SystemHistoryRecord
)


def to_llm_messages(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project canonical records directly into provider chat messages."""
    messages: list[dict[str, Any]] = []
    for record in history:
        role = record.get("role")
        if role == "system":
            content = _llm_content(record.get("content", ""))
            messages.append({"role": "user", "content": f"[System: {content}]"})
        elif role == "user":
            messages.append({"role": "user", "content": _llm_content(record.get("content", ""))})
        elif role == "assistant":
            message: dict[str, Any] = {
                "role": "assistant",
                "content": str(record.get("content") or ""),
            }
            if reasoning := record.get("reasoning_content"):
                message["reasoning_content"] = reasoning
            if tool_calls := record.get("tool_calls"):
                message["tool_calls"] = tool_calls
            messages.append(message)
        elif role == "tool":
            messages.append({
                "role": "tool",
                "tool_call_id": record["tool_call_id"],
                "name": record["name"],
                "content": record["content"],
            })
    return messages


def to_memory_transcript(history: list[dict[str, Any]]) -> str:
    """Render canonical history into a compact transcript for consolidation."""
    lines: list[str] = []
    for record in history:
        created_at = str(record.get("created_at") or "?")[:16]
        role = record.get("role")
        if role in {"user", "assistant", "system"}:
            content = _text_content(record.get("display_content", record.get("content", "")))
            if content:
                lines.append(f"[{created_at}] {str(role).upper()}: {content}")
            if role == "assistant":
                for tool_call in record.get("tool_calls") or []:
                    function = tool_call.get("function") or {}
                    lines.append(
                        f"[{created_at}] TOOL_CALL {function.get('name', '')}: "
                        f"{_summarize(function.get('arguments', ''))}"
                    )
        elif role == "tool":
            lines.append(
                f"[{created_at}] TOOL_RESULT {record.get('name', '')} "
                f"({record.get('tool_call_id', '')}): {_summarize(record.get('content', ''))}"
            )
    return "\n".join(lines)


def trim_boundary(history: list[dict[str, Any]], keep_count: int) -> list[dict[str, Any]]:
    """Return a suffix without orphaning an assistant tool-call stage."""
    if keep_count <= 0:
        return []
    start = max(0, len(history) - keep_count)
    if history[start].get("role") == "tool":
        pending_id = str(history[start].get("tool_call_id", ""))
        for index in range(start - 1, -1, -1):
            previous = history[index]
            if previous.get("role") != "assistant":
                continue
            call_ids = {
                str(call.get("id", "")) for call in previous.get("tool_calls") or []
            }
            if pending_id in call_ids:
                start = index
                break

    candidate = list(history[start:])
    while candidate and candidate[0].get("role") == "tool":
        candidate.pop(0)

    if candidate and candidate[0].get("role") == "assistant":
        expected = {
            str(call.get("id", "")) for call in candidate[0].get("tool_calls") or []
        }
        if expected:
            actual: set[str] = set()
            for record in candidate[1:]:
                if record.get("role") != "tool":
                    break
                actual.add(str(record.get("tool_call_id", "")))
            if actual != expected:
                candidate.pop(0)
                while candidate and candidate[0].get("role") == "tool":
                    candidate.pop(0)

    return candidate


def validate_history_record(record: dict[str, Any]) -> HistoryRecord:
    """Validate one canonical role record and reject legacy record shapes."""
    if "_type" in record:
        raise ValueError("legacy _type history records are not supported")
    role = record.get("role")
    if role not in {"user", "assistant", "tool", "system"}:
        raise ValueError(f"invalid history role: {role}")
    _require(record, "id", "content", "created_at")
    if not isinstance(record["id"], str) or not isinstance(record["created_at"], str):
        raise ValueError("history record id and created_at must be strings")

    if role == "user":
        if not isinstance(record["content"], (str, list)):
            raise ValueError("user content must be a string or content list")
        if "attachments" in record and not isinstance(record["attachments"], list):
            raise ValueError("user attachments must be a list")
    elif role in {"assistant", "system"}:
        if not isinstance(record["content"], str):
            raise ValueError(f"{role} content must be a string")
        if role == "assistant":
            if "reasoning_content" in record and not isinstance(record["reasoning_content"], str):
                raise ValueError("assistant reasoning_content must be a string")
            _validate_tool_calls(record.get("tool_calls"))
    else:
        _require(record, "tool_call_id", "name")
        if not all(isinstance(record[field], str) for field in ("tool_call_id", "name", "content")):
            raise ValueError("tool_call_id, name, and tool content must be strings")
    return cast(HistoryRecord, record)


def _validate_tool_calls(tool_calls: object) -> None:
    if tool_calls is None:
        return
    if not isinstance(tool_calls, list):
        raise ValueError("assistant tool_calls must be a list")
    for tool_call in tool_calls:
        if not isinstance(tool_call, dict):
            raise ValueError("assistant tool call must be an object")
        if tool_call.get("type") != "function" or not isinstance(tool_call.get("id"), str):
            raise ValueError("assistant tool call requires id and type=function")
        function = tool_call.get("function")
        if not isinstance(function, dict):
            raise ValueError("assistant tool call requires function")
        if not isinstance(function.get("name"), str) or not isinstance(function.get("arguments"), str):
            raise ValueError("tool function name and arguments must be strings")


def _require(record: dict[str, Any], *fields: str) -> None:
    missing = [field for field in fields if field not in record]
    if missing:
        raise ValueError(f"history record requires {', '.join(missing)}")


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
    return value if len(value) <= limit else f"{value[:limit]}..."
