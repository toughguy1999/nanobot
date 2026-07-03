from pathlib import Path

from nanobot.agent.attachments import (
    TEXT_CONTEXT_CHAR_LIMIT,
    inbound_attachment_from_path,
    stabilize_user_message,
)
from nanobot.session.history import to_llm_messages


def test_text_attachment_is_stabilized_for_later_history_rebuild(tmp_path: Path):
    text_path = tmp_path / "note.txt"
    text_path.write_text("hello", encoding="utf-8")
    attachment = inbound_attachment_from_path(text_path, mime_type="text/plain")
    assert attachment is not None

    stable = stabilize_user_message(session_key="web:s1", text="read this", attachments=[attachment])
    text_path.unlink()

    assert stable["content"] == "[Text attachment: note.txt, text/plain]\nhello".join(["read this\n\n", ""])
    assert stable["attachments"] == []
    messages = to_llm_messages([{
        "_type": "message",
        "id": "msg_1",
        "role": "user",
        "content": stable["content"],
        "created_at": "2026-01-01T00:00:00",
    }])
    assert messages[0]["content"] == stable["content"]


def test_text_attachment_tracks_invalid_utf8_and_truncation(tmp_path: Path):
    text_path = tmp_path / "bad.txt"
    text_path.write_bytes(b"\xff" + b"a" * TEXT_CONTEXT_CHAR_LIMIT + b"tail")
    attachment = inbound_attachment_from_path(text_path, mime_type="text/plain")
    assert attachment is not None

    stable = stabilize_user_message(session_key="web:s1", text="", attachments=[attachment])

    assert stable["attachments"] == []
    assert "\ufffd" in stable["content"]
    assert "truncated at 100,000 characters" in stable["content"]


