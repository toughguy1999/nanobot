"""Main-agent history compression orchestration."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from math import floor
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.agent.compress.history import build_idle_cleanup_candidate, build_summary_plan
from nanobot.agent.compress.prompts import build_summary_messages
from nanobot.agent.compress.token_estimate import estimate_payload_tokens, estimate_tokens
from nanobot.providers.base import LLMProvider
from nanobot.session.manager import Session, SessionManager

if TYPE_CHECKING:
    from nanobot.config.schema import HistoryCompressionConfig


class HistoryCompressionService:
    """Clean, estimate, and summarize the effective main-agent history."""

    def __init__(
        self,
        config: "HistoryCompressionConfig",
        sessions: SessionManager,
        *,
        clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.config = config
        self.sessions = sessions
        self.clock = clock

    def prepare_for_request(self, session: Session) -> bool:
        candidate = build_idle_cleanup_candidate(
            session.messages,
            session.compression,
            now=self.clock(),
            idle_cleanup_after_seconds=self.config.idle_cleanup_after_seconds,
            keep_tool_rounds=self.config.keep_tool_rounds,
            keep_reasoning_blocks=self.config.keep_reasoning_blocks,
        )
        if candidate is None:
            return False
        self.sessions.commit_compression(session, candidate)
        logger.info("History cleanup applied before the main-model request")
        return True

    def estimate_request(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> int:
        """Estimate the actual request; character counting is cheap and deterministic."""
        return estimate_payload_tokens({"messages": messages, "tools": tools})

    async def maybe_summarize(
        self,
        session: Session,
        *,
        request_tokens: int,
        summary_provider: LLMProvider | None,
        summary_model: str,
    ) -> bool:
        if request_tokens <= self.config.threshold_tokens:
            return False
        if summary_provider is None:
            logger.warning("History summary skipped because the summary provider is unavailable")
            return False

        plan = build_summary_plan(
            session.get_effective_records(),
            threshold_tokens=self.config.threshold_tokens,
            keep_user_turns=self.config.keep_user_turns,
            recent_budget_ratio=self.config.recent_budget_ratio,
        )
        if plan is None:
            logger.warning("History summary skipped because no new safe history prefix is available")
            return False

        summary_budget = max(
            1,
            floor(self.config.threshold_tokens * self.config.summary_budget_ratio),
        )
        summary_messages = build_summary_messages(
            existing_summary=session.compression.summary,
            records=list(plan.records_to_summarize),
            summary_budget_tokens=summary_budget,
        )
        try:
            response = await summary_provider.chat(
                messages=summary_messages,
                tools=None,
                model=summary_model,
                max_tokens=summary_budget,
                temperature=0.2,
            )
        except Exception as exc:
            logger.warning(f"History summary request failed: {exc}")
            return False

        if response.finish_reason == "error":
            logger.warning("History summary request returned an error response")
            return False
        if response.content is None or not response.content.strip():
            logger.warning("History summary request returned empty content")
            return False
        if response.finish_reason == "length":
            logger.warning("History summary reached its output limit; using the non-empty result")
        if estimate_tokens(response.content) > summary_budget:
            logger.warning("History summary exceeds its configured output budget; using it anyway")

        positions = {record["id"]: index for index, record in enumerate(session.messages)}
        boundary = positions[plan.summary_through_id]
        state = session.compression
        candidate = state.model_copy(update={
            "cleared_tool_through_id": _retain_boundary_after(
                state.cleared_tool_through_id,
                boundary,
                positions,
            ),
            "cleared_reasoning_through_id": _retain_boundary_after(
                state.cleared_reasoning_through_id,
                boundary,
                positions,
            ),
            "summary": response.content,
            "summary_through_id": plan.summary_through_id,
        })
        try:
            self.sessions.commit_compression(session, candidate)
        except Exception as exc:
            logger.warning(f"Failed to persist history summary: {exc}")
            return False
        logger.info(
            f"History summary replaced an early prefix; estimated request was {request_tokens} tokens"
        )
        return True

    def warn_if_still_over_threshold(self, request_tokens: int) -> None:
        if request_tokens > self.config.threshold_tokens:
            logger.warning(
                f"Main-model request is estimated at {request_tokens} tokens, above the "
                f"{self.config.threshold_tokens}-token compression threshold; continuing"
            )


def _retain_boundary_after(
    record_id: str | None,
    summary_boundary: int,
    positions: dict[str, int],
) -> str | None:
    if record_id is None or positions[record_id] <= summary_boundary:
        return None
    return record_id
