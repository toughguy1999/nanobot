"""Replace the Todo list belonging to one main-agent session."""

from typing import Any

from nanobot.agent.tools.base import Tool
from nanobot.session.manager import Session, SessionManager


class TodoEditTool(Tool):
    def __init__(self, session: Session, sessions: SessionManager):
        self.session = session
        self.sessions = sessions

    @property
    def name(self) -> str:
        return "todoEdit"

    @property
    def description(self) -> str:
        return (
            "当处理复杂任务时，拆分任务，使用该工具维护todo清单。"
            "更新清单时，整体替换当前会话的 Todo 清单，数组顺序就是任务顺序。"
            "保留所有仍需跟踪的事项，未提交的旧事项会被删除。例如：空数组表示清空全部事项。"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "todos": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "content": {"type": "string", "minLength": 1},
                            "status": {
                                "type": "string",
                                "enum": ["pending", "in_progress", "completed"],
                            },
                        },
                        "required": ["content", "status"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["todos"],
            "additionalProperties": False,
        }

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors = super().validate_params(params)
        if errors:
            return errors
        for key in params.keys() - {"todos"}:
            errors.append(f"unknown parameter: {key}")
        for index, item in enumerate(params["todos"]):
            for key in item.keys() - {"content", "status"}:
                errors.append(f"unknown todos[{index}] field: {key}")
            if not item["content"].strip():
                errors.append(f"todos[{index}].content must not be blank")
        return errors

    async def execute(self, **params: Any) -> str:
        if errors := self.validate_params(params):
            raise ValueError("; ".join(errors))
        todos = [
            {"content": item["content"].strip(), "status": item["status"]}
            for item in params["todos"]
        ]
        missing = object()
        previous = self.session.metadata.get("todos", missing)
        self.session.metadata["todos"] = todos
        try:
            self.sessions.save(self.session)
        except Exception:
            if previous is missing:
                self.session.metadata.pop("todos", None)
            else:
                self.session.metadata["todos"] = previous
            raise
        return f"Todo list updated: {len(todos)} items."
