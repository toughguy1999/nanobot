"""Shared rules for inbound attachments."""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Literal

from loguru import logger

from nanobot.bus.events import InboundAttachment

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
