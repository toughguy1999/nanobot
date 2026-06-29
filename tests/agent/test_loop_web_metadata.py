from pathlib import Path
from typing import Any

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider, LLMResponse
from nanobot.session.manager import SessionManager


def make_manager(tmp_path: Path) -> SessionManager:
    manager = SessionManager()
    tmp_path.mkdir(parents=True, exist_ok=True)
    manager.sessions_dir = tmp_path
    return manager


class FakeProvider(LLMProvider):
    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        return LLMResponse(content="assistant response")

    def get_default_model(self) -> str:
        return "fake-model"


async def test_agent_loop_saves_display_content_and_attachment_metadata(tmp_path: Path):
    manager = make_manager(tmp_path / "sessions")
    loop = AgentLoop(
        bus=MessageBus(),
        provider=FakeProvider(),
        workspace=tmp_path,
        session_manager=manager,
    )
    attachment = {
        "fileId": "att_deadbeef",
        "fileName": "notes.txt",
        "mimeType": "text/plain",
        "extension": "txt",
        "size": 5,
        "type": "text",
        "status": "ready",
    }

    await loop._process_message(
        InboundMessage(
            channel="web",
            sender_id="session-one",
            chat_id="session-one",
            content="model content with injected text",
            metadata={
                "display_content": "visible content",
                "attachments": [attachment],
            },
        )
    )

    session = manager.get("web:session-one", refresh=True)
    assert session is not None
    assert session.messages[0]["content"] == "visible content"
    assert session.messages[0]["attachments"] == [attachment]
    assert "injected text" not in session.messages[0]["content"]
