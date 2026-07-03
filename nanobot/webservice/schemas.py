"""DTOs used by the web service layer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WebPreparedAttachment:
    """Attachment prepared for handoff to the channel boundary."""

    file_name: str
    mime_type: str
    extension: str
    size: int
    type: str
    path: str
    file_id: str | None = None
    status: str = "ready"
    uploaded_at: str | None = None


@dataclass(frozen=True)
class PreparedAttachments:
    """Attachment data prepared for a single user turn."""

    attachments: list[WebPreparedAttachment]


@dataclass(frozen=True)
class PreparedWebMessage:
    """A web client message validated and normalized for channel dispatch."""

    session_id: str
    session_key: str
    content: str
    attachments: list[WebPreparedAttachment]
    metadata: dict[str, Any]
