"""Expose the latest main-agent context when NANOBOT_LLM_CONTEXT=1."""

import json
import os
from pathlib import Path
from typing import Any

CONTEXT_PATH = Path(__file__).resolve().parents[2] / ".nanobot/debug/context.json"


def publish_context(
    *, model: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
) -> None:
    """Replace the snapshot as the main agent's context changes."""
    if os.environ.get("NANOBOT_LLM_CONTEXT") != "1":
        return

    content = json.dumps(
        {"model": model, "messages": messages, "tools": tools},
        ensure_ascii=False,
        indent=2,
    )
    CONTEXT_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = CONTEXT_PATH.with_suffix(".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(CONTEXT_PATH)
