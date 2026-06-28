"""Attachment storage for the web channel."""

from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from nanobot.utils.helpers import PROJECT_ROOT, ensure_dir, safe_filename

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".json", ".csv", ".tsv", ".yaml", ".yml", ".log"}
SUPPORTED_EXTENSIONS = IMAGE_EXTENSIONS | TEXT_EXTENSIONS

MAX_ATTACHMENTS_PER_MESSAGE = 5
MAX_SINGLE_FILE_SIZE = 10 * 1024 * 1024
MAX_TOTAL_ATTACHMENT_SIZE = 25 * 1024 * 1024
TEXT_CONTEXT_CHAR_LIMIT = 100_000
TEMPORARY_TTL = timedelta(hours=24)
DEFAULT_ATTACHMENT_PROMPT = "请查看我上传的文件。"


class AttachmentError(ValueError):
    """Raised when an attachment operation fails validation."""


@dataclass(frozen=True)
class PreparedAttachments:
    """Attachment data prepared for a single user turn."""

    content: str
    media: list[str]
    metadata: list[dict[str, Any]]


class WebAttachmentStore:
    """Store, validate, bind, and read web-channel attachments."""

    def __init__(self, root: Path | None = None):
        self.root = ensure_dir(root or PROJECT_ROOT / ".nanobot" / "attachments" / "web")
        self.messages_dir = ensure_dir(self.root / "messages")
        self.index_path = self.root / "index.json"

    def save_temporary(
        self,
        *,
        session_key: str,
        filename: str,
        content: bytes,
        mime_type: str | None = None,
        uploaded_at: datetime | None = None,
    ) -> dict[str, Any]:
        """Save an uploaded file as a temporary attachment."""
        clean_name = self._clean_filename(filename)
        extension = Path(clean_name).suffix.lower()
        kind = self._kind_for_extension(extension)
        size = len(content)
        if size > MAX_SINGLE_FILE_SIZE:
            raise AttachmentError("file is too large")

        file_id = f"att_{uuid.uuid4().hex}"
        storage_name = f"{file_id}{extension}"
        session_dir = self._session_dir(session_key)
        path = self._safe_child(session_dir, storage_name)
        path.write_bytes(content)

        record = {
            "fileId": file_id,
            "fileName": clean_name,
            "mimeType": mime_type or "",
            "extension": extension.lstrip("."),
            "size": size,
            "kind": kind,
            "status": "temporary",
            "path": self._relative_path(path),
            "uploadedAt": (uploaded_at or datetime.now()).isoformat(),
            "sessionKey": session_key,
        }
        index = self._load_index()
        index[file_id] = record
        self._save_index(index)
        return self.to_public_metadata(record)

    def validate(
        self,
        file_ids: list[str],
        *,
        session_key: str | None = None,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Validate temporary attachment ids for sending."""
        self._validate_file_id_list(file_ids)
        index = self._load_index()
        valid: list[dict[str, Any]] = []
        invalid: list[str] = []
        for file_id in file_ids:
            record = index.get(file_id)
            if self._is_sendable(record, session_key=session_key):
                valid.append(self.to_public_metadata(record))
            else:
                invalid.append(file_id)
        return valid, invalid

    def prepare_for_message(
        self,
        *,
        content: str,
        file_ids: list[str],
        session_key: str | None = None,
    ) -> PreparedAttachments:
        """Validate attachments and assemble model-facing content/media."""
        self._validate_file_id_list(file_ids)
        index = self._load_index()
        records = [index.get(file_id) for file_id in file_ids]
        invalid = [
            file_id
            for file_id, record in zip(file_ids, records, strict=True)
            if not self._is_sendable(record, session_key=session_key)
        ]
        if invalid:
            raise AttachmentError(f"invalid attachments: {', '.join(invalid)}")

        usable_records = [record for record in records if record is not None]
        total_size = sum(int(record["size"]) for record in usable_records)
        if total_size > MAX_TOTAL_ATTACHMENT_SIZE:
            raise AttachmentError("total attachment size is too large")

        base_content = content.strip() or DEFAULT_ATTACHMENT_PROMPT
        text_sections: list[str] = []
        media: list[str] = []
        for record in usable_records:
            path = self._record_path(record)
            if record["kind"] == "image":
                media.append(str(path))
            elif record["kind"] == "text":
                text_sections.append(self._read_text_context(record, path))

        if text_sections:
            base_content = "\n\n".join([base_content, *text_sections])

        return PreparedAttachments(
            content=base_content,
            media=media,
            metadata=[self.to_public_metadata(record) for record in usable_records],
        )

    def bind_to_message(
        self,
        *,
        file_ids: list[str],
        session_key: str,
    ) -> list[dict[str, Any]]:
        """Mark temporary attachments as bound to a session message."""
        self._validate_file_id_list(file_ids)
        index = self._load_index()
        bound: list[dict[str, Any]] = []

        for file_id in file_ids:
            record = index.get(file_id)
            if record is None or not self._is_sendable(record, session_key=session_key):
                raise AttachmentError(f"invalid attachment: {file_id}")

            record = {
                **record,
                "status": "bound",
                "sessionKey": session_key,
            }
            index[file_id] = record
            bound.append(self.to_public_metadata(record))

        self._save_index(index)
        return bound

    def cleanup_expired_temporary(self, *, now: datetime | None = None) -> list[str]:
        """Remove temporary attachments older than the TTL."""
        current = now or datetime.now()
        index = self._load_index()
        removed: list[str] = []
        for file_id, record in list(index.items()):
            if record.get("status") != "temporary":
                continue
            uploaded_at = self._parse_datetime(record.get("uploadedAt"))
            if uploaded_at and current - uploaded_at <= TEMPORARY_TTL:
                continue
            self._delete_record_file(record)
            index.pop(file_id, None)
            removed.append(file_id)
        if removed:
            self._save_index(index)
        return removed

    def delete_session_attachments(self, session_key: str) -> None:
        """Delete all attachments bound to a web session."""
        index = self._load_index()
        for file_id, record in list(index.items()):
            if record.get("sessionKey") == session_key:
                self._delete_record_file(record)
                index.pop(file_id, None)

        session_dir = self.messages_dir / safe_filename(session_key.replace(":", "_"))
        if session_dir.exists():
            session_dir = self._safe_existing_dir(session_dir)
            shutil.rmtree(session_dir)
        self._save_index(index)

    def to_public_metadata(self, record: dict[str, Any] | None) -> dict[str, Any]:
        """Return frontend/history-safe metadata without absolute paths."""
        if not record:
            raise AttachmentError("attachment not found")
        return {
            "fileId": record["fileId"],
            "fileName": record["fileName"],
            "mimeType": record.get("mimeType", ""),
            "extension": record["extension"],
            "size": record["size"],
            "kind": record["kind"],
            "status": "ready",
            "uploadedAt": record.get("uploadedAt"),
        }

    def _read_text_context(self, record: dict[str, Any], path: Path) -> str:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise AttachmentError(
                f"{record['fileName']} could not be read as UTF-8 text"
            ) from exc

        truncated = len(text) > TEXT_CONTEXT_CHAR_LIMIT
        text = text[:TEXT_CONTEXT_CHAR_LIMIT]
        suffix = "\n\n[Text attachment truncated at 100,000 characters.]" if truncated else ""
        return f"[Text attachment: {record['fileName']}]\n{text}{suffix}"

    def _is_sendable(
        self,
        record: dict[str, Any] | None,
        *,
        session_key: str | None = None,
    ) -> bool:
        if not record or record.get("status") != "temporary":
            return False
        if session_key is not None and record.get("sessionKey") != session_key:
            return False
        try:
            path = self._record_path(record)
        except AttachmentError:
            return False
        return path.is_file()

    def _session_dir(self, session_key: str) -> Path:
        if not isinstance(session_key, str) or not session_key:
            raise AttachmentError("sessionKey is required")
        session_dir = ensure_dir(self.messages_dir / safe_filename(session_key.replace(":", "_")))
        return self._safe_existing_dir(session_dir)

    def _validate_file_id_list(self, file_ids: list[str]) -> None:
        if len(file_ids) > MAX_ATTACHMENTS_PER_MESSAGE:
            raise AttachmentError("too many attachments")
        if len(set(file_ids)) != len(file_ids):
            raise AttachmentError("duplicate attachments are not allowed")
        for file_id in file_ids:
            if not isinstance(file_id, str) or not file_id.startswith("att_"):
                raise AttachmentError("invalid fileId")
            suffix = file_id.removeprefix("att_")
            if not suffix or any(char not in "0123456789abcdef" for char in suffix):
                raise AttachmentError("invalid fileId")

    def _kind_for_extension(self, extension: str) -> str:
        if extension in IMAGE_EXTENSIONS:
            return "image"
        if extension in TEXT_EXTENSIONS:
            return "text"
        raise AttachmentError("unsupported file type")

    def _clean_filename(self, filename: str) -> str:
        basename = Path(filename).name
        cleaned = safe_filename(basename)
        if not cleaned or cleaned in {".", ".."}:
            raise AttachmentError("invalid filename")
        extension = Path(cleaned).suffix.lower()
        self._kind_for_extension(extension)
        return cleaned

    def _load_index(self) -> dict[str, dict[str, Any]]:
        if not self.index_path.exists():
            return {}
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise AttachmentError("attachment index is invalid") from exc
        if not isinstance(data, dict):
            raise AttachmentError("attachment index is invalid")
        return {str(key): value for key, value in data.items() if isinstance(value, dict)}

    def _save_index(self, index: dict[str, dict[str, Any]]) -> None:
        self.index_path.write_text(
            json.dumps(index, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _record_path(self, record: dict[str, Any]) -> Path:
        relative_path = record.get("path")
        if not isinstance(relative_path, str):
            raise AttachmentError("attachment path is invalid")
        return self._safe_child(self.root, relative_path)

    def _relative_path(self, path: Path) -> str:
        resolved = path.resolve()
        if not resolved.is_relative_to(self.root.resolve()):
            raise AttachmentError("attachment path escapes root")
        return resolved.relative_to(self.root.resolve()).as_posix()

    def _safe_child(self, base: Path, child: str) -> Path:
        path = (base / child).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise AttachmentError("attachment path escapes root")
        return path

    def _safe_existing_dir(self, path: Path) -> Path:
        resolved = path.resolve()
        if not resolved.is_relative_to(self.root.resolve()):
            raise AttachmentError("attachment path escapes root")
        return resolved

    def _delete_record_file(self, record: dict[str, Any]) -> None:
        try:
            path = self._record_path(record)
        except AttachmentError:
            return
        if path.exists() and path.is_file():
            path.unlink()

    def _parse_datetime(self, value: Any) -> datetime | None:
        if not isinstance(value, str):
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
