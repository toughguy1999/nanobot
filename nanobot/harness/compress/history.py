"""Pure second-level history cleanup policy for the main agent."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import floor
from typing import Any

from nanobot.harness.compress.token_estimate import estimate_payload_tokens
from nanobot.harness.session.compression import CompressionState, project_effective_records
from nanobot.harness.session.history import to_llm_messages


@dataclass(frozen=True, slots=True)
class SummaryPlan:
    """A safe continuous effective-history prefix and the retained suffix."""

    records_to_summarize: tuple[dict[str, Any], ...]
    retained_records: tuple[dict[str, Any], ...]
    summary_through_id: str


def build_summary_plan(
    effective_records: list[dict[str, Any]],
    *,
    threshold_tokens: int,
    keep_user_turns: int,
    recent_budget_ratio: float,
) -> SummaryPlan | None:
    """Choose a safe prefix while always retaining the complete current user turn."""
    user_starts = [
        index for index, record in enumerate(effective_records) if record.get("role") == "user"
    ]
    if not user_starts:
        return None

    keep_count = min(keep_user_turns, len(user_starts))
    budget = floor(threshold_tokens * recent_budget_ratio)
    while keep_count > 1:
        retained_start = user_starts[-keep_count]
        if _estimate_records(effective_records[retained_start:]) <= budget:
            break
        keep_count -= 1

    retained_start = user_starts[-keep_count]
    boundary = retained_start - 1
    if boundary < 0:
        return None

    safe_boundaries = [start - 1 for start in user_starts if 0 <= start - 1 <= boundary]
    while boundary >= 0 and not _is_safe_tool_boundary(effective_records, boundary):
        earlier = [candidate for candidate in safe_boundaries if candidate < boundary]
        if not earlier:
            return None
        boundary = earlier[-1]

    summarized = tuple(effective_records[:boundary + 1])
    retained = tuple(effective_records[boundary + 1:])
    if not summarized:
        return None
    return SummaryPlan(
        records_to_summarize=summarized,
        retained_records=retained,
        summary_through_id=summarized[-1]["id"],
    )


def _estimate_records(records: list[dict[str, Any]]) -> int:
    return estimate_payload_tokens(to_llm_messages(records, resolve_images=False))


def build_idle_cleanup_candidate(
    records: list[dict[str, Any]],
    state: CompressionState,
    *,
    now: datetime,
    idle_cleanup_after_seconds: int,
    keep_tool_rounds: int,
    keep_reasoning_blocks: int,
) -> CompressionState | None:
    """Return a candidate only when an idle check adds permanent cleanup."""
    if not _idle_threshold_reached(
        records,
        now=now,
        idle_cleanup_after_seconds=idle_cleanup_after_seconds,
    ):
        return None

    effective = project_effective_records(records, state)
    positions = {record["id"]: index for index, record in enumerate(records)}
    tool_ids = _tool_result_ids_to_clear(effective, keep_tool_rounds)
    reasoning_ids = _reasoning_ids_to_clear(effective, keep_reasoning_blocks)
    tool_boundary = _latest_boundary(
        state.cleared_tool_through_id,
        tool_ids,
        positions,
    )
    reasoning_boundary = _latest_boundary(
        state.cleared_reasoning_through_id,
        reasoning_ids,
        positions,
    )
    if (
        tool_boundary == state.cleared_tool_through_id
        and reasoning_boundary == state.cleared_reasoning_through_id
    ):
        return None

    return state.model_copy(update={
        "cleared_tool_through_id": tool_boundary,
        "cleared_reasoning_through_id": reasoning_boundary,
    })


def _idle_threshold_reached(
    records: list[dict[str, Any]],
    *,
    now: datetime,
    idle_cleanup_after_seconds: int,
) -> bool:
    last_assistant = next(
        (record for record in reversed(records) if record.get("role") == "assistant"),
        None,
    )
    if last_assistant is None:
        return False
    created_at = datetime.fromisoformat(last_assistant["created_at"])
    if created_at.tzinfo is None and now.tzinfo is not None:
        now = now.replace(tzinfo=None)
    elif created_at.tzinfo is not None and now.tzinfo is None:
        created_at = created_at.replace(tzinfo=None)
    return (now - created_at).total_seconds() >= idle_cleanup_after_seconds


def _tool_result_ids_to_clear(
    records: list[dict[str, Any]],
    keep_tool_rounds: int,
) -> list[str]:
    tool_by_call_id = {
        record["tool_call_id"]: record
        for record in records
        if record.get("role") == "tool"
    }
    rounds: list[list[str]] = []
    for record in records:
        if record.get("role") != "assistant":
            continue
        result_ids = [
            tool_by_call_id[tool_call["id"]]["id"]
            for tool_call in record.get("tool_calls", [])
            if tool_call.get("id") in tool_by_call_id
        ]
        if result_ids:
            rounds.append(result_ids)
    cutoff = max(0, len(rounds) - keep_tool_rounds)
    return [record_id for round_ids in rounds[:cutoff] for record_id in round_ids]


def _reasoning_ids_to_clear(
    records: list[dict[str, Any]],
    keep_reasoning_blocks: int,
) -> list[str]:
    visible_reasoning_ids = [
        record["id"]
        for record in records
        if record.get("role") == "assistant"
        and record.get("reasoning_content")
    ]
    cutoff = max(0, len(visible_reasoning_ids) - keep_reasoning_blocks)
    return visible_reasoning_ids[:cutoff]


def _latest_boundary(
    current: str | None,
    candidates: list[str],
    positions: dict[str, int],
) -> str | None:
    boundaries = ([current] if current is not None else []) + candidates
    return max(boundaries, key=positions.__getitem__) if boundaries else None


def _is_safe_tool_boundary(records: list[dict[str, Any]], boundary: int) -> bool:
    assistant_positions: dict[str, int] = {}
    result_positions: dict[str, int] = {}
    for index, record in enumerate(records):
        if record.get("role") == "assistant":
            for tool_call in record.get("tool_calls", []):
                assistant_positions[tool_call["id"]] = index
        elif record.get("role") == "tool":
            result_positions[record["tool_call_id"]] = index

    for call_id, assistant_position in assistant_positions.items():
        result_position = result_positions.get(call_id)
        if assistant_position <= boundary:
            if result_position is None or result_position > boundary:
                return False
        elif result_position is not None and result_position <= boundary:
            return False
    for call_id, result_position in result_positions.items():
        if result_position <= boundary and call_id not in assistant_positions:
            return False
    return True
