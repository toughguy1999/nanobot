"""Persistent compression boundaries and model-visible history projection."""

from __future__ import annotations

import copy
from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator

TOOL_RESULT_CLEARED_CONTENT = "[历史工具结果已清理]"


class CompressionState(BaseModel):
    """Small persisted state; canonical session records remain untouched."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    cleared_tool_through_id: str | None = None
    cleared_reasoning_through_id: str | None = None
    summary: str | None = None
    summary_through_id: str | None = None

    @model_validator(mode="after")
    def validate_summary_pair(self) -> "CompressionState":
        if (self.summary is None) != (self.summary_through_id is None):
            raise ValueError("summary and summary_through_id must be set together")
        if self.summary is not None and not self.summary.strip():
            raise ValueError("summary must not be blank")
        return self

    @property
    def is_empty(self) -> bool:
        return not any((
            self.cleared_tool_through_id,
            self.cleared_reasoning_through_id,
            self.summary,
            self.summary_through_id,
        ))


def compression_state_from_dict(
    value: object,
    records: list[dict[str, Any]],
) -> CompressionState:
    state = CompressionState.model_validate(value)
    validate_compression_state(state, records)
    return state


def compression_state_to_dict(
    state: CompressionState,
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    validate_compression_state(state, records)
    return state.model_dump(mode="json")


def validate_compression_state(
    state: CompressionState,
    records: list[dict[str, Any]],
) -> dict[str, int]:
    """Validate persisted boundaries and return record positions."""
    positions = {
        record["id"]: index
        for index, record in enumerate(records)
        if isinstance(record.get("id"), str) and record["id"]
    }
    if len(positions) != len(records):
        raise ValueError("compression requires unique non-empty history record ids")

    expected_roles = {
        "cleared_tool_through_id": "tool",
        "cleared_reasoning_through_id": "assistant",
    }
    for field_name, expected_role in expected_roles.items():
        record_id = getattr(state, field_name)
        if record_id is None:
            continue
        _require_record(record_id, positions, field_name)
        if records[positions[record_id]].get("role") != expected_role:
            raise ValueError(f"{field_name} must reference a {expected_role} record")
    if state.summary_through_id is not None:
        _require_record(state.summary_through_id, positions, "summary_through_id")
    return positions


def validate_compression_transition(
    previous: CompressionState,
    candidate: CompressionState,
    records: list[dict[str, Any]],
) -> None:
    """Do not move a visible boundary backward unless a summary covers it."""
    positions = validate_compression_state(candidate, records)
    validate_compression_state(previous, records)
    previous_summary = _position(previous.summary_through_id, positions)
    candidate_summary = _position(candidate.summary_through_id, positions)
    if candidate_summary < previous_summary:
        raise ValueError("summary boundary must not move backward")

    for field_name in ("cleared_tool_through_id", "cleared_reasoning_through_id"):
        old_position = _position(getattr(previous, field_name), positions)
        new_position = _position(getattr(candidate, field_name), positions)
        if old_position > candidate_summary and new_position < old_position:
            raise ValueError(f"{field_name} must not move backward")


def project_effective_records(
    records: list[dict[str, Any]],
    state: CompressionState,
) -> list[dict[str, Any]]:
    """Return effective record copies without resolving image blobs."""
    positions = validate_compression_state(state, records)
    start = _position(state.summary_through_id, positions) + 1
    tool_boundary = _position(state.cleared_tool_through_id, positions)
    reasoning_boundary = _position(state.cleared_reasoning_through_id, positions)

    projected: list[dict[str, Any]] = []
    for index, source in enumerate(records[start:], start=start):
        record = copy.deepcopy(source)
        if record.get("role") == "tool" and index <= tool_boundary:
            record["content"] = TOOL_RESULT_CLEARED_CONTENT
            record.pop("agent_status", None)
        if record.get("role") == "assistant" and index <= reasoning_boundary:
            record.pop("reasoning_content", None)
        projected.append(record)
    return projected


def _position(record_id: str | None, positions: dict[str, int]) -> int:
    return -1 if record_id is None else positions[record_id]


def _require_record(record_id: str, positions: dict[str, int], field_name: str) -> None:
    if record_id not in positions:
        raise ValueError(f"{field_name} references a missing record: {record_id}")
