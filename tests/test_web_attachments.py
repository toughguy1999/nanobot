from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from nanobot.channels.web_attachments import (
    MAX_SINGLE_FILE_SIZE,
    TEXT_CONTEXT_CHAR_LIMIT,
    AttachmentError,
    WebAttachmentStore,
)


def test_store_rejects_unsupported_extension_and_oversized_file(tmp_path: Path):
    store = WebAttachmentStore(tmp_path)

    with pytest.raises(AttachmentError, match="unsupported"):
        store.save_temporary(session_key="web:session-one", filename="report.pdf", content=b"pdf")

    with pytest.raises(AttachmentError, match="large"):
        store.save_temporary(
            session_key="web:session-one",
            filename="huge.txt",
            content=b"x" * (MAX_SINGLE_FILE_SIZE + 1),
        )


def test_store_saves_temporary_and_returns_public_metadata(tmp_path: Path):
    store = WebAttachmentStore(tmp_path)

    metadata = store.save_temporary(
        session_key="web:session-one",
        filename="../notes.md",
        content=b"# hello",
        mime_type="text/plain",
    )

    assert metadata["fileId"].startswith("att_")
    assert metadata["fileName"] == "notes.md"
    assert metadata["extension"] == "md"
    assert metadata["kind"] == "text"
    assert metadata["status"] == "ready"
    assert "path" not in metadata
    assert len(list((tmp_path / "messages" / "web_session-one").iterdir())) == 1


def test_validate_returns_valid_metadata_and_invalid_ids(tmp_path: Path):
    store = WebAttachmentStore(tmp_path)
    metadata = store.save_temporary(
        session_key="web:session-one",
        filename="image.png",
        content=b"png",
    )

    valid, invalid = store.validate(
        [metadata["fileId"], "att_deadbeef"],
        session_key="web:session-one",
    )

    assert [item["fileId"] for item in valid] == [metadata["fileId"]]
    assert invalid == ["att_deadbeef"]


def test_bind_marks_attachment_bound_without_moving_file(tmp_path: Path):
    store = WebAttachmentStore(tmp_path)
    metadata = store.save_temporary(
        session_key="web:session-one",
        filename="note.txt",
        content=b"hello",
    )
    original_path = store._load_index()[metadata["fileId"]]["path"]

    bound = store.bind_to_message(
        file_ids=[metadata["fileId"]],
        session_key="web:session-one",
    )
    index = store._load_index()
    record = index[metadata["fileId"]]

    assert bound[0]["fileId"] == metadata["fileId"]
    assert record["status"] == "bound"
    assert record["sessionKey"] == "web:session-one"
    assert record["path"].startswith("messages/web_session-one/")
    assert record["path"] == original_path
    assert (tmp_path / record["path"]).exists()


def test_prepare_reads_text_context_and_truncates(tmp_path: Path):
    store = WebAttachmentStore(tmp_path)
    text = "a" * (TEXT_CONTEXT_CHAR_LIMIT + 10)
    metadata = store.save_temporary(
        session_key="web:session-one",
        filename="long.log",
        content=text.encode(),
    )

    prepared = store.prepare_for_message(
        content="read this",
        file_ids=[metadata["fileId"]],
        session_key="web:session-one",
    )

    assert prepared.media == []
    assert prepared.metadata[0]["fileName"] == "long.log"
    assert prepared.content.startswith("read this\n\n[Text attachment: long.log]")
    assert "Text attachment truncated at 100,000 characters" in prepared.content
    assert "a" * TEXT_CONTEXT_CHAR_LIMIT in prepared.content


def test_prepare_reports_utf8_text_decode_errors(tmp_path: Path):
    store = WebAttachmentStore(tmp_path)
    metadata = store.save_temporary(
        session_key="web:session-one",
        filename="bad.txt",
        content=b"\xff\xfe",
    )

    with pytest.raises(AttachmentError, match="UTF-8"):
        store.prepare_for_message(
            content="",
            file_ids=[metadata["fileId"]],
            session_key="web:session-one",
        )


def test_cleanup_expired_temporary_removes_file_and_index(tmp_path: Path):
    store = WebAttachmentStore(tmp_path)
    uploaded_at = datetime.now() - timedelta(hours=25)
    metadata = store.save_temporary(
        session_key="web:session-one",
        filename="old.txt",
        content=b"old",
        uploaded_at=uploaded_at,
    )

    removed = store.cleanup_expired_temporary(now=datetime.now())

    assert removed == [metadata["fileId"]]
    assert store._load_index() == {}
    assert not any((tmp_path / "messages" / "web_session-one").iterdir())


def test_delete_session_attachments_removes_bound_files_and_index(tmp_path: Path):
    store = WebAttachmentStore(tmp_path)
    keep = store.save_temporary(
        session_key="web:keep-me",
        filename="keep.txt",
        content=b"keep",
    )
    delete = store.save_temporary(
        session_key="web:delete-me",
        filename="delete.txt",
        content=b"delete",
    )
    store.bind_to_message(file_ids=[delete["fileId"]], session_key="web:delete-me")
    store.bind_to_message(file_ids=[keep["fileId"]], session_key="web:keep-me")

    store.delete_session_attachments("web:delete-me")
    index: dict[str, dict[str, Any]] = store._load_index()

    assert delete["fileId"] not in index
    assert keep["fileId"] in index
    assert not (tmp_path / "messages" / "web_delete-me").exists()
    assert (tmp_path / index[keep["fileId"]]["path"]).exists()
