from pathlib import Path

from nanobot.agent.attachments import inbound_attachment_from_path


def test_inbound_attachment_from_path_accepts_local_images(tmp_path: Path):
    image_path = tmp_path / "photo.png"
    image_path.write_bytes(b"png")

    attachment = inbound_attachment_from_path(image_path, mime_type="image/png")

    assert attachment is not None
    assert attachment.type == "image"
    assert attachment.file_name == "photo.png"
    assert attachment.path == str(image_path.resolve())


def test_inbound_attachment_from_path_rejects_unavailable_or_unknown_files(tmp_path: Path):
    assert inbound_attachment_from_path(tmp_path / "missing.png", mime_type="image/png") is None

    binary_path = tmp_path / "file.bin"
    binary_path.write_bytes(b"bin")

    assert inbound_attachment_from_path(binary_path, mime_type="application/octet-stream") is None
