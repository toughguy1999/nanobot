from io import BytesIO
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from PIL import Image

from nanobot.bus.queue import MessageBus
from nanobot.channels.web import WebChannel
from nanobot.config.schema import WebConfig
from nanobot.session.manager import Session
from nanobot.webservice.attachments import DEFAULT_ATTACHMENT_PROMPT, WebAttachmentStore


def make_png_bytes() -> bytes:
    image = Image.new("RGB", (10, 10), (255, 0, 0))
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_web_channel_session_routes(tmp_path: Path):
    channel = WebChannel(WebConfig(), MessageBus())
    channel._web_service.sessions.sessions_dir = tmp_path

    client = TestClient(channel.app)

    created = client.post("/sessions", json={"sessionId": "session-test"})
    assert created.status_code == 200
    assert created.json()["session"]["id"] == "session-test"

    session = channel._web_service.sessions.get_or_create("web:session-test")
    session.metadata["sessionTitle"] = "first message"
    session.add_message("user", "first message")
    session.add_tool_call(id="call_1", name="read_file", arguments={"path": "README.md"})
    session.add_tool_result(tool_call_id="call_1", name="read_file", content="contents")
    session.add_message("assistant", "answer")
    channel._web_service.sessions.save(session)

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
    assert body["messages"][1]["metadata"] == {"toolsUsed": ["read_file"]}


def test_web_channel_session_list_does_not_backfill_missing_title(tmp_path: Path):
    channel = WebChannel(WebConfig(), MessageBus())
    channel._web_service.sessions.sessions_dir = tmp_path

    session = Session(key="web:legacy-session")
    session.add_message("user", "legacy title")
    channel._web_service.sessions.save(session)

    client = TestClient(channel.app)
    listed = client.get("/sessions")

    assert listed.status_code == 200
    assert listed.json()["sessions"][0]["sessionTitle"] is None

    reloaded = channel._web_service.sessions.get("web:legacy-session", refresh=True)
    assert reloaded is not None
    assert "sessionTitle" not in reloaded.metadata


def test_web_channel_pin_session(tmp_path: Path):
    channel = WebChannel(WebConfig(), MessageBus())
    channel._web_service.sessions.sessions_dir = tmp_path

    session = Session(key="web:pin-me")
    channel._web_service.sessions.save(session)

    client = TestClient(channel.app)
    response = client.post("/sessions/pin-me/pin")

    assert response.status_code == 200
    assert response.json()["session"]["pinned"] is True

    reloaded = channel._web_service.sessions.get("web:pin-me", refresh=True)
    assert reloaded is not None
    assert reloaded.metadata["pinned"] is True


def test_web_channel_unpin_session(tmp_path: Path):
    channel = WebChannel(WebConfig(), MessageBus())
    channel._web_service.sessions.sessions_dir = tmp_path

    session = Session(key="web:pin-me", metadata={"pinned": True})
    channel._web_service.sessions.save(session)

    client = TestClient(channel.app)
    response = client.post("/sessions/pin-me/unpin")

    assert response.status_code == 200
    assert response.json()["session"]["pinned"] is False

    reloaded = channel._web_service.sessions.get("web:pin-me", refresh=True)
    assert reloaded is not None
    assert reloaded.metadata["pinned"] is False


def test_web_channel_pin_missing_session_returns_404(tmp_path: Path):
    channel = WebChannel(WebConfig(), MessageBus())
    channel._web_service.sessions.sessions_dir = tmp_path

    client = TestClient(channel.app)
    response = client.post("/sessions/missing/pin")

    assert response.status_code == 404


def test_web_channel_unpin_missing_session_returns_404(tmp_path: Path):
    channel = WebChannel(WebConfig(), MessageBus())
    channel._web_service.sessions.sessions_dir = tmp_path

    client = TestClient(channel.app)
    response = client.post("/sessions/missing/unpin")

    assert response.status_code == 404


def test_web_channel_delete_session(tmp_path: Path):
    channel = WebChannel(WebConfig(), MessageBus())
    channel._web_service.sessions.sessions_dir = tmp_path

    session = Session(key="web:delete-me")
    channel._web_service.sessions.save(session)
    path = channel._web_service.sessions._get_session_path("web:delete-me")
    assert path.exists()

    client = TestClient(channel.app)
    response = client.post("/sessions/delete-me/delete")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert not path.exists()
    assert channel._web_service.sessions.get("web:delete-me", refresh=True) is None


def test_web_channel_delete_missing_session_returns_404(tmp_path: Path):
    channel = WebChannel(WebConfig(), MessageBus())
    channel._web_service.sessions.sessions_dir = tmp_path

    client = TestClient(channel.app)
    response = client.post("/sessions/missing/delete")

    assert response.status_code == 404


def test_web_channel_session_management_rejects_invalid_session_id(tmp_path: Path):
    channel = WebChannel(WebConfig(), MessageBus())
    channel._web_service.sessions.sessions_dir = tmp_path

    client = TestClient(channel.app)

    assert client.post("/sessions/bad:id/pin").status_code == 400
    assert client.post("/sessions/bad:id/unpin").status_code == 400
    assert client.post("/sessions/bad:id/delete").status_code == 400


def test_web_channel_attachment_routes_upload_validate_and_reject_invalid(tmp_path: Path):
    channel = WebChannel(WebConfig(), MessageBus())
    channel._web_service.attachments = WebAttachmentStore(tmp_path / "attachments")
    client = TestClient(channel.app)

    uploaded = client.post(
        "/attachments",
        data={"sessionId": "session-one"},
        files={"file": ("notes.txt", b"hello", "application/octet-stream")},
    )
    assert uploaded.status_code == 200
    attachment = uploaded.json()["attachment"]
    assert attachment["fileName"] == "notes.txt"
    assert attachment["type"] == "text"

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
    channel._web_service.attachments = WebAttachmentStore(tmp_path / "attachments")
    captured: dict[str, Any] = {}

    async def fake_handle_message(**kwargs: Any) -> None:
        captured.update(kwargs)

    channel._handle_message = fake_handle_message  # type: ignore[assignment, method-assign]

    with TestClient(channel.app) as client:
        with client.websocket_connect("/ws") as websocket:
            websocket.send_json({"sessionId": "session-one", "content": "hello"})

    assert captured["sender_id"] == "session-one"
    assert captured["content"] == "hello"
    assert captured["attachments"] == []
    assert "attachments" not in captured["metadata"]


def test_web_channel_websocket_allows_pure_text_attachment(tmp_path: Path):
    channel = WebChannel(WebConfig(), MessageBus())
    channel._web_service.attachments = WebAttachmentStore(tmp_path / "attachments")
    attachment = channel._web_service.attachments.save_temporary(
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
            websocket.send_json(
                {
                    "sessionId": "session-one",
                    "content": "",
                    "attachments": [{"fileId": attachment["fileId"]}],
                }
            )

    assert captured["content"].startswith(DEFAULT_ATTACHMENT_PROMPT)
    assert len(captured["attachments"]) == 1
    assert captured["attachments"][0].file_name == "notes.md"
    assert captured["attachments"][0].type == "text"
    assert captured["attachments"][0].file_id == attachment["fileId"]
    assert captured["metadata"]["display_content"] == DEFAULT_ATTACHMENT_PROMPT
    assert "attachments" not in captured["metadata"]


def test_web_channel_websocket_image_attachment_enters_attachments(tmp_path: Path):
    channel = WebChannel(WebConfig(), MessageBus())
    channel._web_service.attachments = WebAttachmentStore(tmp_path / "attachments")
    attachment = channel._web_service.attachments.save_temporary(
        session_key="web:session-one",
        filename="image.png",
        content=make_png_bytes(),
    )
    captured: dict[str, Any] = {}

    async def fake_handle_message(**kwargs: Any) -> None:
        captured.update(kwargs)

    channel._handle_message = fake_handle_message  # type: ignore[assignment, method-assign]

    with TestClient(channel.app) as client:
        with client.websocket_connect("/ws") as websocket:
            websocket.send_json(
                {
                    "sessionId": "session-one",
                    "content": "look",
                    "attachments": [{"fileId": attachment["fileId"]}],
                }
            )

    assert captured["content"] == "look"
    assert len(captured["attachments"]) == 1
    assert captured["attachments"][0].type == "image"
    assert captured["attachments"][0].file_id == attachment["fileId"]
    assert captured["attachments"][0].path.endswith(
        "att_" + attachment["fileId"].removeprefix("att_") + f".{attachment['extension']}"
    )
    assert Path(captured["attachments"][0].path).is_file()


def test_web_channel_websocket_rejects_missing_attachment(tmp_path: Path):
    channel = WebChannel(WebConfig(), MessageBus())
    channel._web_service.attachments = WebAttachmentStore(tmp_path / "attachments")

    with TestClient(channel.app) as client:
        with client.websocket_connect("/ws") as websocket:
            websocket.send_json(
                {
                    "sessionId": "session-one",
                    "content": "hello",
                    "attachments": [{"fileId": "att_deadbeef"}],
                }
            )
            assert websocket.receive_json() == {"error": "invalid attachments: att_deadbeef"}


def test_web_channel_history_serializes_attachment_metadata(tmp_path: Path):
    channel = WebChannel(WebConfig(), MessageBus())
    channel._web_service.sessions.sessions_dir = tmp_path / "sessions"
    channel._web_service.sessions.sessions_dir.mkdir(parents=True, exist_ok=True)
    attachment = {
        "fileId": "att_deadbeef",
        "fileName": "notes.txt",
        "mimeType": "text/plain",
        "extension": "txt",
        "size": 5,
        "type": "text",
        "status": "ready",
    }
    session = Session(key="web:history")
    session.add_message("user", "display text", attachments=[attachment])
    channel._web_service.sessions.save(session)

    client = TestClient(channel.app)
    response = client.get("/sessions/history/messages")

    assert response.status_code == 200
    message = response.json()["messages"][0]
    assert message["content"] == "display text"
    assert message["attachments"] == [attachment]
    assert "metadata" not in message


def test_web_channel_delete_session_cleans_attachments(tmp_path: Path):
    channel = WebChannel(WebConfig(), MessageBus())
    channel._web_service.sessions.sessions_dir = tmp_path / "sessions"
    channel._web_service.sessions.sessions_dir.mkdir(parents=True, exist_ok=True)
    channel._web_service.attachments = WebAttachmentStore(tmp_path / "attachments")
    session = Session(key="web:delete-with-attachments")
    channel._web_service.sessions.save(session)
    attachment = channel._web_service.attachments.save_temporary(
        session_key="web:delete-with-attachments",
        filename="notes.txt",
        content=b"hello",
    )
    channel._web_service.attachments.bind_to_message(
        file_ids=[attachment["fileId"]],
        session_key="web:delete-with-attachments",
    )

    client = TestClient(channel.app)
    response = client.post("/sessions/delete-with-attachments/delete")

    assert response.status_code == 200
    assert channel._web_service.attachments._load_index() == {}
    assert not (tmp_path / "attachments" / "messages" / "web_delete-with-attachments").exists()
