"""Shared rules for inbound attachments."""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any, Literal, TypedDict

from loguru import logger

from nanobot.bus.events import InboundAttachment
from nanobot.session.blobs import SessionBlobStore

AttachmentType = Literal["image", "text", "unknown"]

IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"})
TEXT_EXTENSIONS = frozenset({
    ".txt",
    ".md",
    ".markdown",
    ".json",
    ".csv",
    ".tsv",
    ".yaml",
    ".yml",
    ".log",
})
SUPPORTED_ATTACHMENT_EXTENSIONS = IMAGE_EXTENSIONS | TEXT_EXTENSIONS

TEXT_CONTEXT_CHAR_LIMIT = 100_000


class StableUserMessage(TypedDict):
    """User history content produced after stabilizing attachments."""

    content: str | list[dict[str, Any]]
    display_content: str
    attachments: list[dict[str, Any]]


def normalize_extension(extension: str) -> str:
    """Normalize an extension to lowercase with a leading dot."""
    value = extension.lower().strip()
    if not value:
        return ""
    return value if value.startswith(".") else f".{value}"


def classify_attachment(extension: str, mime_type: str | None = None) -> AttachmentType:
    """Classify an attachment by extension and MIME type."""
    normalized = normalize_extension(extension)
    mime = (mime_type or "").lower()

    if normalized in IMAGE_EXTENSIONS or mime.startswith("image/"):
        return "image"
    if normalized in TEXT_EXTENSIONS or mime.startswith("text/"):
        return "text"
    return "unknown"


def inbound_attachment_from_path(
    path: str | Path,
    *,
    file_name: str | None = None,
    mime_type: str | None = None,
) -> InboundAttachment | None:
    """Create an inbound attachment from a local file path when supported."""
    file_path = Path(path)
    if not file_path.is_file():
        logger.warning(f"Skipping attachment with unavailable path: {file_path}")
        return None

    guessed_mime, _ = mimetypes.guess_type(str(file_path))
    resolved_mime = mime_type or guessed_mime or ""
    extension = file_path.suffix.lower()
    attachment_type = classify_attachment(extension, resolved_mime)
    if attachment_type == "unknown":
        logger.warning(f"Skipping attachment with unsupported type: {file_path}")
        return None

    return InboundAttachment(
        file_name=file_name or file_path.name,
        mime_type=resolved_mime,
        extension=extension.lstrip("."),
        size=file_path.stat().st_size,
        type=attachment_type,
        path=str(file_path.resolve()),
    )


def stabilize_user_message(
    *,
    session_key: str,
    text: str,
    attachments: list[InboundAttachment] | None
) -> StableUserMessage:
    """Create LLM-ready, stable history content for a user message."""
    if not attachments:
        result: StableUserMessage = {
            "content": text,
            "display_content": text,
            "attachments": [],
        }
        return result

    text_sections: list[str] = []
    image_items: list[dict[str, Any]] = []

    for attachment in attachments:
        if attachment.type == "text":
            section = _stabilize_text_attachment(attachment)
            if section:
                text_sections.append(section)
        elif attachment.type == "image":
            store = SessionBlobStore()
            blob = _stabilize_image_attachment(session_key, attachment, store)
            if blob:
                image_items.append({
                    "type": "image_url",
                    "image_url": {"blob": blob},
                })
        else:
            logger.warning(f"Skipping unsupported attachment type: {attachment.type}")

    merged_text = text
    if text_sections:
        merged_text = "\n\n".join([text, *text_sections]) if text else "\n\n".join(text_sections)

    content: str | list[dict[str, Any]]
    if image_items:
        content = image_items + [{"type": "text", "text": merged_text}]
    else:
        content = merged_text

    return {
        "content": content,
        "display_content": text,
        "attachments": [],
    }


def _stabilize_text_attachment(attachment: InboundAttachment) -> str | None:
    path = Path(attachment.path)
    if not path.is_file():
        logger.warning(f"Skipping text attachment with unavailable path: {path}")
        return None
    try:
        raw = path.read_bytes()
    except OSError as exc:
        logger.warning(f"Failed to read text attachment {attachment.file_name}: {exc}")
        return None

    text = raw.decode("utf-8", errors="replace")
    if "\ufffd" in text:
        logger.warning(f"Text attachment {attachment.file_name} had invalid UTF-8 bytes")
    truncated = len(text) > TEXT_CONTEXT_CHAR_LIMIT
    text = text[:TEXT_CONTEXT_CHAR_LIMIT]
    suffix = "\n\n[Text attachment truncated at 100,000 characters.]" if truncated else ""
    mime = attachment.mime_type or "application/octet-stream"
    return f"[Text attachment: {attachment.file_name}, {mime}]\n{text}{suffix}"


def _stabilize_image_attachment(
    session_key: str,
    attachment: InboundAttachment,
    store: SessionBlobStore,
) -> dict[str, Any] | None:
    path = Path(attachment.path)
    if not path.is_file():
        logger.warning(f"Skipping image attachment with unavailable path: {path}")
        return None
    mime = attachment.mime_type or mimetypes.guess_type(str(path))[0]
    if not mime or not mime.startswith("image/"):
        logger.warning(f"Skipping image attachment with unsupported MIME type: {attachment.file_name}")
        return None
    try:
        return store.save_file(
            session_key=session_key,
            source_path=path,
            filename=attachment.file_name,
            mime_type=mime,
        )
    except OSError as exc:
        logger.warning(f"Failed to copy image attachment {attachment.file_name}: {exc}")
        return None
