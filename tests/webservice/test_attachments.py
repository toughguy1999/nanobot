from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from nanobot.webservice.attachments import (
    MAX_SINGLE_FILE_SIZE,
    TARGET_IMAGE_FILE_SIZE,
    WebAttachmentStore,
)
from nanobot.webservice.errors import AttachmentError


def make_png_bytes(size: tuple[int, int] = (10, 10), color: tuple[int, int, int] = (255, 0, 0)) -> bytes:
    image = Image.new("RGB", size, color)
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def make_animated_gif_bytes() -> bytes:
    frames = [
        Image.new("RGB", (12, 12), (255, 0, 0)),
        Image.new("RGB", (12, 12), (0, 255, 0)),
    ]
    output = BytesIO()
    frames[0].save(
        output,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=100,
        loop=0,
    )
    return output.getvalue()


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
    assert metadata["type"] == "text"
    assert metadata["status"] == "ready"
    assert "path" not in metadata
    assert len(list((tmp_path / "messages" / "web_session-one").iterdir())) == 1


def test_validate_returns_valid_metadata_and_invalid_ids(tmp_path: Path):
    store = WebAttachmentStore(tmp_path)
    metadata = store.save_temporary(
        session_key="web:session-one",
        filename="image.png",
        content=make_png_bytes(),
    )

    valid, invalid = store.validate(
        [metadata["fileId"], "att_deadbeef"],
        session_key="web:session-one",
    )

    assert [item["fileId"] for item in valid] == [metadata["fileId"]]
    assert invalid == ["att_deadbeef"]


def test_image_upload_keeps_resampled_original_format_when_under_target(tmp_path: Path):
    store = WebAttachmentStore(tmp_path)
    original = make_png_bytes(size=(3000, 3000), color=(20, 120, 200))

    metadata = store.save_temporary(
        session_key="web:session-one",
        filename="large.png",
        content=original,
        mime_type="image/png",
    )
    record = store._load_index()[metadata["fileId"]]
    stored_path = tmp_path / record["path"]

    assert metadata["fileName"] == "large.png"
    assert metadata["extension"] == "png"
    assert metadata["mimeType"] == "image/png"
    assert metadata["size"] == stored_path.stat().st_size
    assert metadata["size"] <= TARGET_IMAGE_FILE_SIZE
    assert stored_path.suffix == ".png"
    with Image.open(stored_path) as stored:
        assert max(stored.size) <= 2048


def test_animated_image_upload_preserves_original_file(tmp_path: Path):
    store = WebAttachmentStore(tmp_path)
    original = make_animated_gif_bytes()

    metadata = store.save_temporary(
        session_key="web:session-one",
        filename="loop.gif",
        content=original,
        mime_type="image/gif",
    )
    record = store._load_index()[metadata["fileId"]]
    stored_path = tmp_path / record["path"]

    assert metadata["fileName"] == "loop.gif"
    assert metadata["extension"] == "gif"
    assert metadata["mimeType"] == "image/gif"
    assert stored_path.read_bytes() == original
    with Image.open(stored_path) as stored:
        assert getattr(stored, "is_animated", False)
        assert getattr(stored, "n_frames", 1) == 2


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


def test_prepare_returns_internal_attachments_without_reading_content(tmp_path: Path):
    store = WebAttachmentStore(tmp_path)
    metadata = store.save_temporary(
        session_key="web:session-one",
        filename="long.log",
        content=b"\xff\xfe",
    )

    prepared = store.prepare_for_message(
        file_ids=[metadata["fileId"]],
        session_key="web:session-one",
    )

    assert len(prepared.attachments) == 1
    assert prepared.attachments[0].file_name == "long.log"
    assert prepared.attachments[0].type == "text"
    assert prepared.attachments[0].file_id == metadata["fileId"]
    assert prepared.attachments[0].status == "ready"
    assert prepared.attachments[0].uploaded_at == metadata["uploadedAt"]
    assert prepared.attachments[0].path.endswith(".log")
    assert Path(prepared.attachments[0].path).is_absolute()
    assert Path(prepared.attachments[0].path).is_file()


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
