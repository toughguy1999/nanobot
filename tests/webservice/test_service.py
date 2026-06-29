from pathlib import Path

import pytest

from nanobot.session.manager import SessionManager
from nanobot.webservice.attachments import DEFAULT_ATTACHMENT_PROMPT, WebAttachmentStore
from nanobot.webservice.errors import BadRequestError, NotFoundError
from nanobot.webservice.service import WebService


def make_service(tmp_path: Path) -> WebService:
    sessions = SessionManager()
    sessions.sessions_dir = tmp_path / "sessions"
    sessions.sessions_dir.mkdir(parents=True, exist_ok=True)
    return WebService(
        sessions=sessions,
        attachments=WebAttachmentStore(tmp_path / "attachments"),
    )


def test_session_crud_and_message_serialization(tmp_path: Path):
    service = make_service(tmp_path)

    created = service.create_session({"sessionId": "session-test"})
    assert created["session"]["id"] == "session-test"

    session = service.sessions.get_or_create("web:session-test")
    session.add_message("user", "first message")
    session.add_message("assistant", "answer", tools_used=[])
    service.sessions.save(session)

    assert service.list_sessions()["sessions"][0]["sessionTitle"] == "first message"

    detail = service.get_session_messages("session-test")
    assert detail["messages"][0]["role"] == "user"
    assert detail["messages"][1]["metadata"] == {"toolsUsed": []}

    assert service.pin_session("session-test")["session"]["pinned"] is True
    assert service.unpin_session("session-test")["session"]["pinned"] is False
    assert service.delete_session("session-test") == {"ok": True}

    with pytest.raises(NotFoundError):
        service.get_session_messages("session-test")


def test_session_validation_and_missing_session_errors(tmp_path: Path):
    service = make_service(tmp_path)

    with pytest.raises(BadRequestError, match="sessionId is required"):
        service.create_session({})
    with pytest.raises(BadRequestError, match="invalid sessionId"):
        service.pin_session("bad:id")
    with pytest.raises(NotFoundError):
        service.pin_session("missing")


def test_prepare_message_binds_attachments_and_excludes_websocket(tmp_path: Path):
    service = make_service(tmp_path)
    attachment = service.attachments.save_temporary(
        session_key="web:session-one",
        filename="notes.md",
        content=b"# hello",
    )

    prepared = service.prepare_message(
        {
            "sessionId": "session-one",
            "content": "",
            "attachments": [{"fileId": attachment["fileId"]}],
        }
    )

    assert prepared.session_id == "session-one"
    assert prepared.session_key == "web:session-one"
    assert prepared.content == DEFAULT_ATTACHMENT_PROMPT
    assert prepared.attachments[0].file_name == "notes.md"
    assert prepared.metadata["attachments"][0]["fileId"] == attachment["fileId"]
    assert "websocket" not in prepared.metadata


def test_webservice_does_not_import_channel_or_bus_modules():
    root = Path(__file__).parents[2] / "nanobot" / "webservice"

    for source in root.glob("*.py"):
        text = source.read_text(encoding="utf-8")
        assert "nanobot.bus" not in text
        assert "nanobot.channels" not in text
