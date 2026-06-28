from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.web import WebChannel
from nanobot.channels.web_attachments import DEFAULT_ATTACHMENT_PROMPT, WebAttachmentStore
from nanobot.config.schema import WebConfig
from nanobot.providers.base import LLMProvider, LLMResponse
from nanobot.session.manager import Session, SessionManager


def make_manager(tmp_path: Path) -> SessionManager:
    manager = SessionManager()
    tmp_path.mkdir(parents=True, exist_ok=True)
    manager.sessions_dir = tmp_path
    return manager


def test_session_manager_lists_web_metadata_without_loading_messages(tmp_path: Path):
    manager = make_manager(tmp_path)

    web_session = Session(key="web:session_one")
    web_session.add_message("user", "hello from web")
    web_session.add_message("assistant", "hi")
    manager.save(web_session)

    cli_session = Session(key="cli:direct")
    cli_session.add_message("user", "ignore me")
    manager.save(cli_session)

    sessions = manager.list_sessions(channel="web")

    assert len(sessions) == 1
    assert sessions[0]["key"] == "web:session_one"
    assert sessions[0]["metadata"]["sessionTitle"] == "hello from web"
    assert sessions[0]["updated_at"] == web_session.updated_at.isoformat()

    loaded = manager.get("web:session_one", refresh=True)
    assert loaded is not None
    assert loaded.updated_at == web_session.updated_at


def test_session_manager_lists_pinned_sessions_first(tmp_path: Path):
    manager = make_manager(tmp_path)

    regular_session = Session(key="web:regular")
    regular_session.add_message("user", "regular")
    manager.save(regular_session)

    pinned_session = Session(key="web:pinned")
    pinned_session.add_message("user", "pinned")
    pinned_session.metadata["pinned"] = True
    manager.save(pinned_session)

    sessions = manager.list_sessions(channel="web")

    assert [session["key"] for session in sessions] == ["web:pinned", "web:regular"]


def test_web_channel_session_routes(tmp_path: Path):
    channel = WebChannel(WebConfig(), MessageBus())
    channel._sessions.sessions_dir = tmp_path

    client = TestClient(channel.app)

    created = client.post("/sessions", json={"sessionId": "session-test"})
    assert created.status_code == 200
    assert created.json()["session"]["id"] == "session-test"

    session = channel._sessions.get_or_create("web:session-test")
    session.add_message("user", "first message")
    session.add_message("assistant", "answer", tools_used=[])
    channel._sessions.save(session)

    listed = client.get("/sessions")
    assert listed.status_code == 200
    assert listed.json()["sessions"] == [
        {
            "id": "session-test",
            "key": "web:session-test",
            "sessionTitle": "first message",
            "createdAt": session.created_at.isoformat(),
            "updatedAt": session.updated_at.isoformat(),
            "pinned": False,
        }
    ]

    detail = client.get("/sessions/session-test/messages")
    assert detail.status_code == 200
    body = detail.json()
    assert body["session"]["sessionTitle"] == "first message"
    assert body["messages"][0]["role"] == "user"
    assert body["messages"][0]["createdAt"]
    assert body["messages"][1]["metadata"] == {"toolsUsed": []}


def test_web_channel_session_list_backfills_missing_title(tmp_path: Path):
    channel = WebChannel(WebConfig(), MessageBus())
    channel._sessions.sessions_dir = tmp_path

    session = Session(key="web:legacy-session")
    session.add_message("user", "legacy title")
    session.metadata.pop("sessionTitle")
    channel._sessions.save(session)

    client = TestClient(channel.app)
    listed = client.get("/sessions")

    assert listed.status_code == 200
    assert listed.json()["sessions"][0]["sessionTitle"] == "legacy title"

    reloaded = channel._sessions.get("web:legacy-session", refresh=True)
    assert reloaded is not None
    assert reloaded.metadata["sessionTitle"] == "legacy title"


def test_web_channel_pin_session(tmp_path: Path):
    channel = WebChannel(WebConfig(), MessageBus())
    channel._sessions.sessions_dir = tmp_path

    session = Session(key="web:pin-me")
    channel._sessions.save(session)

    client = TestClient(channel.app)
    response = client.post("/sessions/pin-me/pin")

    assert response.status_code == 200
    assert response.json()["session"]["pinned"] is True

    reloaded = channel._sessions.get("web:pin-me", refresh=True)
    assert reloaded is not None
    assert reloaded.metadata["pinned"] is True


def test_web_channel_unpin_session(tmp_path: Path):
    channel = WebChannel(WebConfig(), MessageBus())
    channel._sessions.sessions_dir = tmp_path

    session = Session(key="web:pin-me", metadata={"pinned": True})
    channel._sessions.save(session)

    client = TestClient(channel.app)
    response = client.post("/sessions/pin-me/unpin")

    assert response.status_code == 200
    assert response.json()["session"]["pinned"] is False

    reloaded = channel._sessions.get("web:pin-me", refresh=True)
    assert reloaded is not None
    assert reloaded.metadata["pinned"] is False


def test_web_channel_pin_missing_session_returns_404(tmp_path: Path):
    channel = WebChannel(WebConfig(), MessageBus())
    channel._sessions.sessions_dir = tmp_path

    client = TestClient(channel.app)
    response = client.post("/sessions/missing/pin")

    assert response.status_code == 404


def test_web_channel_unpin_missing_session_returns_404(tmp_path: Path):
    channel = WebChannel(WebConfig(), MessageBus())
    channel._sessions.sessions_dir = tmp_path

    client = TestClient(channel.app)
    response = client.post("/sessions/missing/unpin")

    assert response.status_code == 404


def test_web_channel_delete_session(tmp_path: Path):
    channel = WebChannel(WebConfig(), MessageBus())
    channel._sessions.sessions_dir = tmp_path

    session = Session(key="web:delete-me")
    channel._sessions.save(session)
    path = channel._sessions._get_session_path("web:delete-me")
    assert path.exists()

    client = TestClient(channel.app)
    response = client.post("/sessions/delete-me/delete")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert not path.exists()
    assert channel._sessions.get("web:delete-me", refresh=True) is None


def test_web_channel_delete_missing_session_returns_404(tmp_path: Path):
    channel = WebChannel(WebConfig(), MessageBus())
    channel._sessions.sessions_dir = tmp_path

    client = TestClient(channel.app)
    response = client.post("/sessions/missing/delete")

    assert response.status_code == 404


def test_web_channel_session_management_rejects_invalid_session_id(tmp_path: Path):
    channel = WebChannel(WebConfig(), MessageBus())
    channel._sessions.sessions_dir = tmp_path

    client = TestClient(channel.app)

    assert client.post("/sessions/bad:id/pin").status_code == 400
    assert client.post("/sessions/bad:id/unpin").status_code == 400
    assert client.post("/sessions/bad:id/delete").status_code == 400


def test_web_channel_attachment_routes_upload_validate_and_reject_invalid(tmp_path: Path):
    channel = WebChannel(WebConfig(), MessageBus())
    channel._attachments = WebAttachmentStore(tmp_path / "attachments")
    client = TestClient(channel.app)

    uploaded = client.post(
        "/attachments",
        data={"sessionId": "session-one"},
        files={"file": ("notes.txt", b"hello", "application/octet-stream")},
    )
    assert uploaded.status_code == 200
    attachment = uploaded.json()["attachment"]
    assert attachment["fileName"] == "notes.txt"
    assert attachment["kind"] == "text"

    validated = client.post(
        "/attachments/validate",
        json={"sessionId": "session-one", "fileIds": [attachment["fileId"]]},
    )
    assert validated.status_code == 200
    assert validated.json()["valid"][0]["fileId"] == attachment["fileId"]
    assert validated.json()["invalid"] == []

    invalid_upload = client.post(
        "/attachments",
        data={"sessionId": "session-one"},
        files={"file": ("report.pdf", b"pdf", "application/pdf")},
    )
    assert invalid_upload.status_code == 400


def test_web_channel_websocket_text_message_regression(tmp_path: Path):
    channel = WebChannel(WebConfig(), MessageBus())
    channel._attachments = WebAttachmentStore(tmp_path / "attachments")
    captured: dict[str, Any] = {}

    async def fake_handle_message(**kwargs: Any) -> None:
        captured.update(kwargs)

    channel._handle_message = fake_handle_message  # type: ignore[assignment, method-assign]

    with TestClient(channel.app) as client:
        with client.websocket_connect("/ws") as websocket:
            websocket.send_json({"sessionId": "session-one", "content": "hello"})

    assert captured["sender_id"] == "session-one"
    assert captured["content"] == "hello"
    assert captured["media"] == []
    assert captured["metadata"]["attachments"] == []


def test_web_channel_websocket_allows_pure_text_attachment(tmp_path: Path):
    channel = WebChannel(WebConfig(), MessageBus())
    channel._attachments = WebAttachmentStore(tmp_path / "attachments")
    attachment = channel._attachments.save_temporary(
        session_key="web:session-one",
        filename="notes.md",
        content=b"# hello",
    )
    captured: dict[str, Any] = {}

    async def fake_handle_message(**kwargs: Any) -> None:
        captured.update(kwargs)

    channel._handle_message = fake_handle_message  # type: ignore[assignment, method-assign]

    with TestClient(channel.app) as client:
        with client.websocket_connect("/ws") as websocket:
            websocket.send_json({
                "sessionId": "session-one",
                "content": "",
                "attachments": [{"fileId": attachment["fileId"]}],
            })

    assert captured["content"].startswith(DEFAULT_ATTACHMENT_PROMPT)
    assert "[Text attachment: notes.md]" in captured["content"]
    assert captured["metadata"]["display_content"] == DEFAULT_ATTACHMENT_PROMPT
    assert captured["metadata"]["attachments"][0]["fileId"] == attachment["fileId"]


def test_web_channel_websocket_image_attachment_enters_media(tmp_path: Path):
    channel = WebChannel(WebConfig(), MessageBus())
    channel._attachments = WebAttachmentStore(tmp_path / "attachments")
    attachment = channel._attachments.save_temporary(
        session_key="web:session-one",
        filename="image.png",
        content=b"png",
    )
    captured: dict[str, Any] = {}

    async def fake_handle_message(**kwargs: Any) -> None:
        captured.update(kwargs)

    channel._handle_message = fake_handle_message  # type: ignore[assignment, method-assign]

    with TestClient(channel.app) as client:
        with client.websocket_connect("/ws") as websocket:
            websocket.send_json({
                "sessionId": "session-one",
                "content": "look",
                "attachments": [{"fileId": attachment["fileId"]}],
            })

    assert captured["content"] == "look"
    assert len(captured["media"]) == 1
    assert captured["media"][0].endswith("att_" + attachment["fileId"].removeprefix("att_") + ".png")
    assert Path(captured["media"][0]).is_file()


def test_web_channel_websocket_rejects_missing_attachment(tmp_path: Path):
    channel = WebChannel(WebConfig(), MessageBus())
    channel._attachments = WebAttachmentStore(tmp_path / "attachments")

    with TestClient(channel.app) as client:
        with client.websocket_connect("/ws") as websocket:
            websocket.send_json({
                "sessionId": "session-one",
                "content": "hello",
                "attachments": [{"fileId": "att_deadbeef"}],
            })
            assert websocket.receive_json() == {"error": "invalid attachments: att_deadbeef"}


def test_web_channel_history_serializes_attachment_metadata(tmp_path: Path):
    channel = WebChannel(WebConfig(), MessageBus())
    channel._sessions.sessions_dir = tmp_path / "sessions"
    channel._sessions.sessions_dir.mkdir(parents=True, exist_ok=True)
    attachment = {
        "fileId": "att_deadbeef",
        "fileName": "notes.txt",
        "mimeType": "text/plain",
        "extension": "txt",
        "size": 5,
        "kind": "text",
        "status": "ready",
    }
    session = Session(key="web:history")
    session.add_message("user", "display text", attachments=[attachment])
    channel._sessions.save(session)

    client = TestClient(channel.app)
    response = client.get("/sessions/history/messages")

    assert response.status_code == 200
    message = response.json()["messages"][0]
    assert message["content"] == "display text"
    assert message["metadata"]["attachments"] == [attachment]


def test_web_channel_delete_session_cleans_attachments(tmp_path: Path):
    channel = WebChannel(WebConfig(), MessageBus())
    channel._sessions.sessions_dir = tmp_path / "sessions"
    channel._sessions.sessions_dir.mkdir(parents=True, exist_ok=True)
    channel._attachments = WebAttachmentStore(tmp_path / "attachments")
    session = Session(key="web:delete-with-attachments")
    channel._sessions.save(session)
    attachment = channel._attachments.save_temporary(
        session_key="web:delete-with-attachments",
        filename="notes.txt",
        content=b"hello",
    )
    channel._attachments.bind_to_message(
        file_ids=[attachment["fileId"]],
        session_key="web:delete-with-attachments",
    )

    client = TestClient(channel.app)
    response = client.post("/sessions/delete-with-attachments/delete")

    assert response.status_code == 200
    assert channel._attachments._load_index() == {}
    assert not (tmp_path / "attachments" / "messages" / "web_delete-with-attachments").exists()


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
        "kind": "text",
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
