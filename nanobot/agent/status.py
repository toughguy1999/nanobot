"""Render immutable status snapshots for one main-agent processing turn."""

import time
from collections.abc import Callable
from html import escape

from nanobot.session.manager import Session

STATUS_LABELS = {"pending": "待开始", "in_progress": "进行中", "completed": "已完成"}


class AgentStatus:
    def __init__(self, clock: Callable[[], float] | None = None):
        self._clock = clock if clock is not None else time.monotonic
        self._started_at = self._clock()

    def snapshot(self, session: Session) -> str:
        elapsed = int(self._clock() - self._started_at)
        lines = ["<agent_status>", f"本轮对话已用时间：{elapsed} 秒"]
        todos = session.metadata.get("todos", [])
        if todos:
            lines.append("Todo：")
            for index, todo in enumerate(todos, 1):
                # Keep each item on one line and prevent it from closing the status block.
                content = escape(todo["content"], quote=False).replace("\r", "&#13;").replace("\n", "&#10;")
                lines.append(f"{index}. [{STATUS_LABELS[todo['status']]}] {content}")
        else:
            lines.append("Todo：空")
        lines.append("</agent_status>")
        return "\n".join(lines)
