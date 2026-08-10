"""Application service for browser web client use cases."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from nanobot.session.manager import Session, SessionManager
from nanobot.webservice.attachments import DEFAULT_ATTACHMENT_PROMPT, WebAttachmentStore
from nanobot.webservice.errors import AttachmentError, BadRequestError, NotFoundError
from nanobot.webservice.schemas import PreparedWebMessage
from nanobot.webservice.serialization import serialize_assistant_record, serialize_user_record


class WebService:
    """Business use cases for the web client."""

    channel_name = "web"

    def __init__(
        self,
        sessions: SessionManager | None = None,
        attachments: WebAttachmentStore | None = None,
    ) -> None:
        self.sessions = sessions or SessionManager()
        self.attachments = attachments or WebAttachmentStore()

    def session_key(self, session_id: str) -> str:
        """Return the persistent session key for a browser session id."""
        if not session_id or ":" in session_id:
            raise BadRequestError("invalid sessionId")
        return f"{self.channel_name}:{session_id}"

    def list_sessions(self) -> dict[str, Any]:
        """List web sessions in frontend shape."""
        sessions = [
            self._serialize_session_summary(item)
            for item in self.sessions.list_sessions(
                channel=self.channel_name,
            )
        ]
        return {"sessions": sessions}

    def create_session(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Create or load a web session."""
        session_id = self._parse_session_id(payload)
        session = self.sessions.get_or_create(self.session_key(session_id))
        self.sessions.save(session)
        return {"session": self._serialize_session(session)}

    def get_session_messages(self, session_id: str) -> dict[str, Any]:
        """Return a web session and its serialized messages."""
        session = self.sessions.get(self.session_key(session_id), refresh=True)
        if session is None:
            raise NotFoundError("session not found")

        return {
            "session": self._serialize_session(session),
            "messages": self._project_history_to_web_messages(session),
        }

    def pin_session(self, session_id: str) -> dict[str, Any]:
        """Mark a web session pinned."""
        return {"session": self._update_pinned(session_id, True)}

    def unpin_session(self, session_id: str) -> dict[str, Any]:
        """Mark a web session unpinned."""
        return {"session": self._update_pinned(session_id, False)}

    def delete_session(self, session_id: str) -> dict[str, bool]:
        """Delete a web session and its attachments."""
        session_key = self.session_key(session_id)
        deleted = self.sessions.delete(session_key)
        if not deleted:
            raise NotFoundError("session not found")
        self.attachments.delete_session_attachments(session_key)
        return {"ok": True}

    def save_attachment(
        self,
        *,
        session_id: str,
        filename: str,
        content: bytes,
        mime_type: str | None,
    ) -> dict[str, Any]:
        """Save an uploaded file for later message binding."""
        attachment = self.attachments.save_temporary(
            session_key=self.session_key(session_id),
            filename=filename,
            content=content,
            mime_type=mime_type,
        )
        return {"attachment": attachment}

    def validate_attachments(
        self,
        *,
        session_id: str,
        file_ids: list[str],
    ) -> dict[str, Any]:
        """Validate attachment ids for the given session."""
        valid, invalid = self.attachments.validate(
            file_ids,
            session_key=self.session_key(session_id),
        )
        return {"valid": valid, "invalid": invalid}

    def prepare_message(self, payload: Mapping[str, Any]) -> PreparedWebMessage:
        """Validate and normalize a WebSocket message payload."""
        content = payload.get("content", "")
        session_id = payload.get("sessionId", "")
        attachments = payload.get("attachments", [])

        if not isinstance(content, str):
            raise BadRequestError("content is required")
        if not session_id or not isinstance(session_id, str):
            raise BadRequestError("sessionId is required")

        session_key = self.session_key(session_id)
        attachment_file_ids = self._parse_attachment_ids(attachments)
        if not content.strip() and not attachment_file_ids:
            raise BadRequestError("content is required")

        prepared_attachments = self.attachments.prepare_for_message(
            file_ids=attachment_file_ids,
            session_key=session_key,
        )
        self.attachments.bind_to_message(
            file_ids=attachment_file_ids,
            session_key=session_key,
        )
        display_content = content.strip() or DEFAULT_ATTACHMENT_PROMPT

        return PreparedWebMessage(
            session_id=session_id,
            session_key=session_key,
            content=display_content,
            attachments=prepared_attachments.attachments,
            metadata={
                "session_key": session_key,
                "display_content": display_content,
            },
        )

    def cleanup_expired_temporary_attachments(self) -> list[str]:
        """Remove expired temporary attachments."""
        return self.attachments.cleanup_expired_temporary()

    def _update_pinned(self, session_id: str, pinned: bool) -> dict[str, Any]:
        session = self.sessions.update_metadata(
            self.session_key(session_id),
            {"pinned": pinned},
        )
        if session is None:
            raise NotFoundError("session not found")
        return self._serialize_session(session)

    def _parse_session_id(self, payload: Mapping[str, Any]) -> str:
        session_id = payload.get("sessionId")
        if not isinstance(session_id, str):
            raise BadRequestError("sessionId is required")
        self.session_key(session_id)
        return session_id

    def _parse_attachment_ids(self, attachments: object) -> list[str]:
        if attachments in (None, []):
            return []
        if not isinstance(attachments, list):
            raise AttachmentError("attachments must be a list")

        file_ids: list[str] = []
        for item in attachments:
            if not isinstance(item, dict) or not isinstance(item.get("fileId"), str):
                raise AttachmentError("attachments must contain fileId")
            file_ids.append(item["fileId"])
        return file_ids

    def _serialize_session_summary(self, item: dict[str, Any]) -> dict[str, Any]:
        key = item["key"]
        session_id = key.removeprefix(f"{self.channel_name}:")
        metadata = item.get("metadata") or {}
        return {
            "id": session_id,
            "key": key,
            "sessionTitle": metadata.get("sessionTitle"),
            "createdAt": item.get("created_at"),
            "updatedAt": item.get("updated_at"),
            "pinned": bool(metadata.get("pinned", False)),
        }

    def _serialize_session(self, session: Session) -> dict[str, Any]:
        session_id = session.key.removeprefix(f"{self.channel_name}:")
        metadata = session.metadata or {}
        return {
            "id": session_id,
            "key": session.key,
            "sessionTitle": metadata.get("sessionTitle"),
            "createdAt": session.created_at.isoformat(),
            "updatedAt": session.updated_at.isoformat(),
            "pinned": bool(metadata.get("pinned", False)),
        }

    def _project_history_to_web_messages(self, session: Session) -> list[dict[str, Any]]:
        serializers = {
            "user": serialize_user_record,
            "assistant": serialize_assistant_record,
        }
        return [
            serializers[record["role"]](record)
            for record in session.messages
            if record.get("role") in serializers
        ]
