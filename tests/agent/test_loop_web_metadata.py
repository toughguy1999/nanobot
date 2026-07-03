from pathlib import Path
from typing import Any

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundAttachment, InboundMessage
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


async def test_agent_loop_saves_display_content_without_metadata_attachments(tmp_path: Path):
    manager = make_manager(tmp_path / "sessions")
    loop = AgentLoop(
        bus=MessageBus(),
        provider=FakeProvider(),
        workspace=tmp_path,
        session_manager=manager,
    )
    await loop._process_message(
        InboundMessage(
            channel="web",
            sender_id="session-one",
            chat_id="session-one",
            content="model content with injected text",
            metadata={"display_content": "visible content"},
        )
    )

    session = manager.get("web:session-one", refresh=True)
    assert session is not None
    assert session.messages[0]["content"] == "model content with injected text"
    assert session.messages[0]["display_content"] == "visible content"
    assert session.messages[0]["attachments"] == []


async def test_agent_loop_does_not_duplicate_web_attachment_metadata(tmp_path: Path):
    manager = make_manager(tmp_path / "sessions")
    loop = AgentLoop(
        bus=MessageBus(),
        provider=FakeProvider(),
        workspace=tmp_path,
        session_manager=manager,
    )
    attachment_path = tmp_path / "notes.txt"
    attachment_path.write_text("file body", encoding="utf-8")
    attachment_metadata = {
        "fileId": "att_deadbeef",
        "fileName": "notes.txt",
        "mimeType": "text/plain",
        "extension": "txt",
        "size": 9,
        "type": "text",
        "status": "ready",
    }

    await loop._process_message(
        InboundMessage(
            channel="web",
            sender_id="session-one",
            chat_id="session-one",
            content="visible content",
            attachments=[
                InboundAttachment(
                    file_name="notes.txt",
                    mime_type="text/plain",
                    extension="txt",
                    size=9,
                    type="text",
                    path=str(attachment_path),
                    file_id="att_deadbeef",
                )
            ],
            metadata={"display_content": "visible content"},
        )
    )

    session = manager.get("web:session-one", refresh=True)
    assert session is not None
    assert session.messages[0]["content"] == (
        "visible content\n\n[Text attachment: notes.txt, text/plain]\nfile body"
    )
    assert session.messages[0]["attachments"] == [attachment_metadata]
