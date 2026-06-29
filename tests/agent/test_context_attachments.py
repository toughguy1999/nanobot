from pathlib import Path

from nanobot.agent.attachments import TEXT_CONTEXT_CHAR_LIMIT
from nanobot.agent.context import ContextBuilder
from nanobot.bus.events import InboundAttachment


def make_attachment(path: Path, *, type: str, mime_type: str = "") -> InboundAttachment:
    return InboundAttachment(
        file_name=path.name,
        mime_type=mime_type,
        extension=path.suffix.lstrip("."),
        size=path.stat().st_size if path.exists() else 0,
        type=type,
        path=str(path),
    )


def user_content(
    builder: ContextBuilder,
    text: str,
    attachments: list[InboundAttachment] | None = None,
):
    return builder.build_messages([], text, attachments=attachments)[-1]["content"]


def test_build_messages_without_attachments_keeps_string_content(tmp_path: Path):
    content = user_content(ContextBuilder(tmp_path), "hello")

    assert content == "hello"


def test_build_messages_includes_text_attachment_context(tmp_path: Path):
    file_path = tmp_path / "notes.md"
    file_path.write_text("# hello", encoding="utf-8")

    content = user_content(
        ContextBuilder(tmp_path),
        "read this",
        [make_attachment(file_path, type="text", mime_type="text/markdown")],
    )

    assert isinstance(content, str)
    assert content.startswith("read this\n\n[Text attachment: notes.md, text/markdown]")
    assert "# hello" in content


def test_build_messages_truncates_text_attachment(tmp_path: Path):
    file_path = tmp_path / "long.log"
    file_path.write_text("a" * (TEXT_CONTEXT_CHAR_LIMIT + 5), encoding="utf-8")

    content = user_content(
        ContextBuilder(tmp_path),
        "",
        [make_attachment(file_path, type="text", mime_type="text/plain")],
    )

    assert isinstance(content, str)
    assert "a" * TEXT_CONTEXT_CHAR_LIMIT in content
    assert "Text attachment truncated at 100,000 characters" in content


def test_build_messages_includes_image_attachment_data_url(tmp_path: Path):
    file_path = tmp_path / "image.png"
    file_path.write_bytes(b"png")

    content = user_content(
        ContextBuilder(tmp_path),
        "look",
        [make_attachment(file_path, type="image", mime_type="image/png")],
    )

    assert isinstance(content, list)
    assert content[0]["type"] == "image_url"
    assert content[0]["image_url"]["url"] == "data:image/png;base64,cG5n"
    assert content[1] == {"type": "text", "text": "look"}


def test_build_messages_combines_text_and_image_attachments(tmp_path: Path):
    image_path = tmp_path / "image.png"
    text_path = tmp_path / "notes.txt"
    image_path.write_bytes(b"png")
    text_path.write_text("note body", encoding="utf-8")

    content = user_content(
        ContextBuilder(tmp_path),
        "mixed",
        [
            make_attachment(text_path, type="text", mime_type="text/plain"),
            make_attachment(image_path, type="image", mime_type="image/png"),
        ],
    )

    assert isinstance(content, list)
    assert content[0]["type"] == "image_url"
    assert content[1]["text"].startswith("mixed\n\n[Text attachment: notes.txt, text/plain]")
    assert "note body" in content[1]["text"]


def test_build_messages_skips_invalid_unknown_and_bad_utf8_attachments(tmp_path: Path):
    missing_path = tmp_path / "missing.txt"
    unknown_path = tmp_path / "data.bin"
    bad_text_path = tmp_path / "bad.txt"
    unknown_path.write_bytes(b"bin")
    bad_text_path.write_bytes(b"\xff\xfe")

    content = user_content(
        ContextBuilder(tmp_path),
        "base",
        [
            InboundAttachment("missing.txt", "text/plain", "txt", 0, "text", str(missing_path)),
            make_attachment(unknown_path, type="unknown"),
            make_attachment(bad_text_path, type="text", mime_type="text/plain"),
        ],
    )

    assert isinstance(content, str)
    assert content.startswith("base\n\n[Text attachment: bad.txt, text/plain]")
    assert "\ufffd\ufffd" in content
