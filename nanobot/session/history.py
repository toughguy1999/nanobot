"""Canonical role-based session history records and conversions."""

from __future__ import annotations

from typing import Any, Literal, NotRequired, TypeAlias, TypedDict, cast

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
    agent_status: str


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
    agent_status: NotRequired[str]


class SystemHistoryRecord(TypedDict):
    id: str
    role: Literal["system"]
    content: str
    created_at: str
    agent_status: NotRequired[str]


HistoryRecord: TypeAlias = (
    UserHistoryRecord | AssistantHistoryRecord | ToolHistoryRecord | SystemHistoryRecord
)


def to_llm_messages(
    history: list[dict[str, Any]],
    *,
    resolve_images: bool = True,
) -> list[dict[str, Any]]:
    """Project canonical records directly into provider chat messages."""
    messages: list[dict[str, Any]] = []
    for record in history:
        role = record.get("role")
        if role == "system":
            content = _llm_content(record.get("content", ""), resolve_images=resolve_images)
            messages.append({
                "role": "user",
                "content": _append_agent_status(f"[System: {content}]", record),
            })
        elif role == "user":
            messages.append({
                "role": "user",
                "content": _append_agent_status(
                    _llm_content(record.get("content", ""), resolve_images=resolve_images),
                    record,
                ),
            })
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
                "content": _append_agent_status(record["content"], record),
            })
    return messages


def _append_agent_status(
    content: str | list[dict[str, Any]], record: dict[str, Any],
) -> str | list[dict[str, Any]]:
    """Append only the saved snapshot, without mutating the canonical body."""
    if "agent_status" not in record:
        return content
    status = record["agent_status"]
    if isinstance(content, list):
        return [*content, {"type": "text", "text": status}]
    return f"{content}\n\n{status}"


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
    if "agent_status" in record:
        if role == "assistant" or not isinstance(record["agent_status"], str):
            raise ValueError("agent_status must be a string on a user, tool, or system record")

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


def _llm_content(
    content: object,
    *,
    resolve_images: bool,
) -> str | list[dict[str, Any]]:
    if not isinstance(content, list):
        return str(content) if content is not None else ""

    store = SessionBlobStore()
    converted: list[dict[str, Any]] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if resolve_images and item.get("type") == "image_url":
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
