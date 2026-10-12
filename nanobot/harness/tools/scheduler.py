"""Batch-local tool scheduling with ordered results and serial barriers."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nanobot.providers.base import ToolCallRequest

DEFAULT_MAX_TOOL_CONCURRENCY = 4


async def execute_batch(
    calls: Sequence[ToolCallRequest],
    *,
    is_safe: Callable[[ToolCallRequest], bool],
    execute: Callable[[ToolCallRequest], Awaitable[str]],
    max_concurrency: int,
) -> list[str]:
    """Drain adjacent safe groups before crossing each unsafe call."""
    if type(max_concurrency) is not int or max_concurrency <= 0:
        raise ValueError("max_concurrency must be a positive integer")

    results = [""] * len(calls)
    safety = [is_safe(call) for call in calls]
    active: dict[asyncio.Task[str], int] = {}

    async def run(call: ToolCallRequest) -> str:
        try:
            return await execute(call)
        except Exception as exc:
            return f"Error executing {call.name}: {exc}"

    cursor = 0
    try:
        while cursor < len(calls):
            if not safety[cursor]:
                results[cursor] = await run(calls[cursor])
                cursor += 1
                continue

            end = cursor + 1
            while end < len(calls) and safety[end]:
                end += 1
            while cursor < end or active:
                while cursor < end and len(active) < max_concurrency:
                    active[asyncio.create_task(run(calls[cursor]))] = cursor
                    cursor += 1
                done, _ = await asyncio.wait(active, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    results[active.pop(task)] = task.result()
    finally:
        for task in active:
            task.cancel()
        if active:
            await asyncio.gather(*active, return_exceptions=True)
    return results
