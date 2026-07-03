import json
from pathlib import Path
from typing import Any

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider, LLMResponse
from nanobot.session.manager import Session, SessionManager


class ConsolidationProvider(LLMProvider):
    def __init__(self, content: str):
        super().__init__()
        self.content = content
        self.prompt = ""

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        self.prompt = str(messages[-1]["content"])
        return LLMResponse(content=self.content)

    def get_default_model(self) -> str:
        return "fake-model"


def make_manager(tmp_path: Path) -> SessionManager:
    manager = SessionManager()
    manager.sessions_dir = tmp_path
    return manager


def make_session() -> Session:
    session = Session(key="cli:direct")
    session.add_user_message("old user")
    session.add_tool_call(id="call_1", name="read_file", arguments={"path": "README.md"})
    session.add_tool_result(tool_call_id="call_1", name="read_file", content="file body")
    session.add_assistant_message("old answer")
    session.add_user_message("new user")
    session.add_assistant_message("new answer")
    return session


async def test_consolidation_archive_all_clears_history_and_writes_memory(tmp_path: Path):
    manager = make_manager(tmp_path / "sessions")
    provider = ConsolidationProvider(json.dumps({
        "history_entry": "[2026-01-01 00:00] archived",
        "memory_update": "remembered",
    }))
    loop = AgentLoop(MessageBus(), provider, tmp_path, memory_window=4, session_manager=manager)
    session = make_session()
    manager.save(session)

    await loop._consolidate_memory(session, archive_all=True)

    assert session.messages == []
    assert (tmp_path / "memory" / "MEMORY.md").read_text(encoding="utf-8") == "remembered"
    assert "archived" in (tmp_path / "memory" / "HISTORY.md").read_text(encoding="utf-8")
    assert "TOOL_CALL read_file" in provider.prompt
    assert "TOOL_RESULT read_file (call_1)" in provider.prompt


async def test_consolidation_uses_trim_boundary_for_kept_history(tmp_path: Path):
    manager = make_manager(tmp_path / "sessions")
    provider = ConsolidationProvider(json.dumps({
        "history_entry": "[2026-01-01 00:00] archived",
        "memory_update": "",
    }))
    loop = AgentLoop(MessageBus(), provider, tmp_path, memory_window=4, session_manager=manager)
    session = make_session()
    manager.save(session)

    await loop._consolidate_memory(session)

    assert [record["_type"] for record in session.messages] == ["message", "message"]
    assert [record["content"] for record in session.messages] == ["new user", "new answer"]
    assert session.get_llm_history() == [
        {"role": "user", "content": "new user"},
        {"role": "assistant", "content": "new answer"},
    ]


async def test_consolidation_invalid_json_keeps_history_unchanged(tmp_path: Path):
    manager = make_manager(tmp_path / "sessions")
    loop = AgentLoop(MessageBus(), ConsolidationProvider("not json"), tmp_path, session_manager=manager)
    session = make_session()
    original = list(session.messages)
    manager.save(session)

    await loop._consolidate_memory(session, archive_all=True)

    assert session.messages == original
