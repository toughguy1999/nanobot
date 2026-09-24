"""Session management for role-based conversation history."""

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.harness.session.compression import (
    CompressionState,
    compression_state_from_dict,
    compression_state_to_dict,
    project_effective_records,
    validate_compression_state,
    validate_compression_transition,
)
from nanobot.harness.session.history import to_llm_messages, validate_history_record
from nanobot.utils.helpers import PROJECT_ROOT, ensure_dir, safe_filename


@dataclass
class Session:
    """A conversation session persisted as metadata plus role records."""

    key: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)
    compression: CompressionState = field(default_factory=CompressionState)

    def add_message(
        self,
        role: str,
        content: str | list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        record = {
            "id": f"msg_{uuid.uuid4().hex}",
            "role": role,
            "content": content,
            "created_at": datetime.now().isoformat(),
            **kwargs,
        }
        validate_history_record(record)
        self.messages.append(record)
        self.updated_at = datetime.now()
        return record

    def add_user_message(
        self, content: str | list[dict[str, Any]], **kwargs: Any
    ) -> dict[str, Any]:
        return self.add_message("user", content, **kwargs)

    def add_assistant_message(self, content: str, **kwargs: Any) -> dict[str, Any]:
        if not kwargs.get("reasoning_content"):
            kwargs.pop("reasoning_content", None)
        if not kwargs.get("tool_calls"):
            kwargs.pop("tool_calls", None)
        return self.add_message("assistant", content, **kwargs)

    def add_system_message(self, content: str, **kwargs: Any) -> dict[str, Any]:
        return self.add_message("system", content, **kwargs)

    def add_tool_result(
        self,
        *,
        tool_call_id: str,
        name: str,
        content: str,
        agent_status: str | None = None,
    ) -> dict[str, Any]:
        return self.add_message(
            "tool",
            content,
            tool_call_id=tool_call_id,
            name=name,
            **({"agent_status": agent_status} if agent_status is not None else {}),
        )

    def get_llm_history(self) -> list[dict[str, Any]]:
        """Project the effective saved records into provider messages."""
        return to_llm_messages(self.get_effective_records())

    def get_effective_records(self) -> list[dict[str, Any]]:
        """Return effective record copies before provider image resolution."""
        return project_effective_records(self.messages, self.compression)

    def clear(self) -> None:
        self.messages = []
        self.compression = CompressionState()
        self.updated_at = datetime.now()


class SessionManager:
    """Manages JSONL conversation sessions."""

    def __init__(self) -> None:
        self.sessions_dir = ensure_dir(PROJECT_ROOT / ".nanobot" / "sessions")
        self._cache: dict[str, Session] = {}

    def _get_session_path(self, key: str) -> Path:
        safe_key = safe_filename(key.replace(":", "_"))
        return self.sessions_dir / f"{safe_key}.jsonl"

    def get_or_create(self, key: str) -> Session:
        if key in self._cache:
            return self._cache[key]
        session = self._load(key)
        if session is None:
            session = Session(key=key)
        self._cache[key] = session
        return session

    def _load(self, key: str) -> Session | None:
        path = self._get_session_path(key)
        if not path.exists():
            return None

        try:
            with path.open(encoding="utf-8") as file:
                lines = [line.strip() for line in file if line.strip()]
            if not lines:
                raise ValueError("session metadata line is missing")
            metadata_record = _validate_metadata_record(json.loads(lines[0]))
            messages = [dict(validate_history_record(json.loads(line))) for line in lines[1:]]
            created_at = datetime.fromisoformat(metadata_record["created_at"])
            metadata = dict(metadata_record["metadata"])
            raw_compression = metadata.pop("compression", None)
            compression = (
                CompressionState()
                if raw_compression is None
                else compression_state_from_dict(raw_compression, messages)
            )
            return Session(
                key=key,
                messages=messages,
                created_at=created_at,
                updated_at=datetime.fromtimestamp(path.stat().st_mtime),
                metadata=metadata,
                compression=compression,
            )
        except Exception as exc:
            logger.warning(f"Failed to load session {key}: {exc}")
            raise ValueError(f"invalid session file for {key}: {exc}") from exc

    def get(self, key: str, refresh: bool = False) -> Session | None:
        if not refresh and key in self._cache:
            return self._cache[key]
        session = self._load(key)
        if session is not None:
            self._cache[key] = session
        return session

    def save(self, session: Session) -> None:
        """Atomically replace a complete session file."""
        ensure_dir(self.sessions_dir)
        path = self._get_session_path(session.key)
        temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        metadata = dict(session.metadata)
        metadata.pop("compression", None)
        validate_compression_state(session.compression, session.messages)
        if not session.compression.is_empty:
            metadata["compression"] = compression_state_to_dict(
                session.compression,
                session.messages,
            )
        metadata_record = {
            "created_at": session.created_at.isoformat(),
            "metadata": metadata,
        }
        _validate_metadata_record(metadata_record)
        for message in session.messages:
            validate_history_record(message)

        try:
            with temp_path.open("w", encoding="utf-8", newline="\n") as file:
                file.write(json.dumps(metadata_record, ensure_ascii=False) + "\n")
                for message in session.messages:
                    file.write(json.dumps(message, ensure_ascii=False) + "\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(temp_path, path)
        finally:
            if temp_path.exists():
                temp_path.unlink()
        session.updated_at = datetime.fromtimestamp(path.stat().st_mtime)
        self._cache[session.key] = session

    def append(self, session: Session, record: dict[str, Any]) -> None:
        """Append exactly one validated role record."""
        validate_history_record(record)
        ensure_dir(self.sessions_dir)
        path = self._get_session_path(session.key)
        if not path.exists():
            self.save(session)
            return
        with path.open("a", encoding="utf-8", newline="\n") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
        session.updated_at = datetime.fromtimestamp(path.stat().st_mtime)
        self._cache[session.key] = session

    def commit_compression(self, session: Session, candidate: CompressionState) -> None:
        """Atomically persist a monotonic candidate, restoring memory on failure."""
        validate_compression_transition(session.compression, candidate, session.messages)
        previous = session.compression
        session.compression = candidate
        try:
            self.save(session)
        except BaseException:
            session.compression = previous
            raise

    def ensure_session_title(self, key: str) -> str | None:
        session = self.get(key, refresh=True)
        if session is None or session.metadata.get("sessionTitle"):
            return session.metadata.get("sessionTitle") if session else None
        first_user = next(
            (
                record
                for record in session.messages
                if record.get("role") == "user" and record.get("content")
            ),
            None,
        )
        if first_user is None:
            return None
        title = _display_text(first_user["content"])
        if not title:
            return None
        session.metadata["sessionTitle"] = title
        self.save(session)
        return title

    def update_metadata(self, key: str, updates: dict[str, Any]) -> Session | None:
        if "compression" in updates:
            raise ValueError("compression metadata must be updated through commit_compression")
        session = self.get(key, refresh=True)
        if session is None:
            return None
        session.metadata.update(updates)
        self.save(session)
        return session

    def delete(self, key: str) -> bool:
        self._cache.pop(key, None)
        path = self._get_session_path(key)
        if path.exists():
            path.unlink()
            return True
        return False

    def list_sessions(
        self,
        channel: str | None = None,
        backfill_session_title: bool = False,
    ) -> list[dict[str, Any]]:
        sessions: list[dict[str, Any]] = []
        for path in self.sessions_dir.glob("*.jsonl"):
            try:
                with path.open(encoding="utf-8") as file:
                    first_line = next((line.strip() for line in file if line.strip()), "")
                if not first_line:
                    raise ValueError("session metadata line is missing")
                data = _validate_metadata_record(json.loads(first_line))
                key = path.stem.replace("_", ":", 1)
                if channel and not key.startswith(f"{channel}:"):
                    continue
                metadata = dict(data["metadata"])
                metadata.pop("compression", None)
                if (
                    backfill_session_title
                    and key.startswith("web:")
                    and not metadata.get("sessionTitle")
                ):
                    title = self.ensure_session_title(key)
                    if title:
                        metadata["sessionTitle"] = title
                sessions.append({
                    "key": key,
                    "created_at": data["created_at"],
                    "updated_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
                    "metadata": metadata,
                    "path": str(path),
                })
            except Exception as exc:
                logger.warning(f"Skipping invalid session file {path}: {exc}")
        return sorted(
            sessions,
            key=lambda item: (
                bool((item.get("metadata") or {}).get("pinned")),
                item.get("updated_at", ""),
            ),
            reverse=True,
        )


def _validate_metadata_record(record: object) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise ValueError("session metadata must be an object")
    if "role" in record or "_type" in record:
        raise ValueError("session metadata must not contain role or _type")
    if not isinstance(record.get("created_at"), str):
        raise ValueError("session metadata requires created_at")
    datetime.fromisoformat(record["created_at"])
    if not isinstance(record.get("metadata"), dict):
        raise ValueError("session metadata requires a metadata object")
    return record


def _display_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(item.get("text", ""))
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        )
    return ""
