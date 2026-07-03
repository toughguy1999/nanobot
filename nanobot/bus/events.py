"""Event types for the message bus."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class InboundAttachment:
    """Local attachment received from a chat channel."""

    file_name: str
    mime_type: str
    extension: str
    size: int
    type: str
    path: str
    file_id: str | None = None
    status: str = "ready"
    uploaded_at: str | None = None

    def to_history_metadata(self) -> dict[str, Any]:
        """Return JSON-safe attachment metadata for persisted session history."""
        metadata: dict[str, Any] = {
            "fileName": self.file_name,
            "mimeType": self.mime_type,
            "extension": self.extension,
            "size": self.size,
            "type": self.type,
            "status": self.status,
        }
        if self.file_id:
            metadata["fileId"] = self.file_id
        if self.uploaded_at:
            metadata["uploadedAt"] = self.uploaded_at
        return metadata


@dataclass
class InboundMessage:
    """Message received from a chat channel."""

    channel: str  # telegram, discord, slack, whatsapp
    sender_id: str  # User identifier
    chat_id: str  # Chat/channel identifier
    content: str  # Message text
    timestamp: datetime = field(default_factory=datetime.now)
    attachments: list[InboundAttachment] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)  # Channel-specific data

    @property
    def session_key(self) -> str:
        """Unique key for session identification."""
        return f"{self.channel}:{self.chat_id}"


@dataclass
class OutboundMessage:
    """Message to send to a chat channel."""

    channel: str
    chat_id: str
    content: str
    reply_to: str | None = None
    media: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


