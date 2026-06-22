"""Session management for conversation history."""

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.utils.helpers import PROJECT_ROOT, ensure_dir, safe_filename


@dataclass
class Session:
    """
    A conversation session.
    
    Stores messages in JSONL format for easy reading and persistence.
    """

    key: str  # channel:chat_id
    messages: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_message(self, role: str, content: str, **kwargs: Any) -> None:
        """Add a message to the session."""
        if self.key.startswith("web:") and role == "user" and not self.metadata.get("sessionTitle"):
            self.metadata["sessionTitle"] = content

        msg = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            **kwargs
        }
        self.messages.append(msg)
        self.updated_at = datetime.now()

    def get_history(self, max_messages: int = 50) -> list[dict[str, Any]]:
        """
        Get message history for LLM context.
        
        Args:
            max_messages: Maximum messages to return.
        
        Returns:
            List of messages in LLM format.
        """
        # Get recent messages
        recent = self.messages[-max_messages:] if len(self.messages) > max_messages else self.messages

        # Convert to LLM format (just role and content)
        return [{"role": m["role"], "content": m["content"]} for m in recent]

    def clear(self) -> None:
        """Clear all messages in the session."""
        self.messages = []
        self.updated_at = datetime.now()


class SessionManager:
    """
    Manages conversation sessions.
    
    Sessions are stored as JSONL files in the sessions directory.
    """

    def __init__(self):
        self.sessions_dir = ensure_dir(PROJECT_ROOT / ".nanobot" / "sessions")
        self._cache: dict[str, Session] = {}

    def _get_session_path(self, key: str) -> Path:
        """Get the file path for a session."""
        safe_key = safe_filename(key.replace(":", "_"))
        return self.sessions_dir / f"{safe_key}.jsonl"

    def get_or_create(self, key: str) -> Session:
        """
        Get an existing session or create a new one.
        
        Args:
            key: Session key (usually channel:chat_id).
        
        Returns:
            The session.
        """
        # Check cache
        if key in self._cache:
            return self._cache[key]

        # Try to load from disk
        session = self._load(key)
        if session is None:
            session = Session(key=key)

        self._cache[key] = session
        return session

    def _load(self, key: str) -> Session | None:
        """Load a session from disk."""
        path = self._get_session_path(key)

        if not path.exists():
            return None

        try:
            messages = []
            metadata = {}
            created_at = None
            updated_at = None

            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    data = json.loads(line)

                    if data.get("_type") == "metadata":
                        metadata = data.get("metadata", {})
                        created_at = datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None
                        updated_at = datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else None
                    else:
                        messages.append(data)

            return Session(
                key=key,
                messages=messages,
                created_at=created_at or datetime.now(),
                updated_at=updated_at or created_at or datetime.now(),
                metadata=metadata
            )
        except Exception as e:
            logger.warning(f"Failed to load session {key}: {e}")
            return None

    def get(self, key: str, refresh: bool = False) -> Session | None:
        """Get an existing session without creating it."""
        if not refresh and key in self._cache:
            return self._cache[key]

        session = self._load(key)
        if session is not None:
            self._cache[key] = session
        return session

    def save(self, session: Session) -> None:
        """Save a session to disk."""
        path = self._get_session_path(session.key)

        with open(path, "w") as f:
            # Write metadata first
            metadata_line = {
                "_type": "metadata",
                "created_at": session.created_at.isoformat(),
                "updated_at": session.updated_at.isoformat(),
                "metadata": session.metadata
            }
            f.write(json.dumps(metadata_line) + "\n")

            # Write messages
            for msg in session.messages:
                f.write(json.dumps(msg) + "\n")

        self._cache[session.key] = session

    def ensure_session_title(self, key: str) -> str | None:
        """Backfill a web session title from its first user message if needed."""
        session = self.get(key, refresh=True)
        if session is None or session.metadata.get("sessionTitle"):
            return session.metadata.get("sessionTitle") if session else None

        first_user_message = next(
            (
                message
                for message in session.messages
                if message.get("role") == "user" and message.get("content")
            ),
            None,
        )
        if not first_user_message:
            return None

        title = str(first_user_message["content"])
        session.metadata["sessionTitle"] = title
        self.save(session)
        return title

    def delete(self, key: str) -> bool:
        """
        Delete a session.
        
        Args:
            key: Session key.
        
        Returns:
            True if deleted, False if not found.
        """
        # Remove from cache
        self._cache.pop(key, None)

        # Remove file
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
        """
        List all sessions.

        Args:
            channel: Optional channel filter.
            backfill_session_title: Populate missing sessionTitle from first user message.
        
        Returns:
            List of session info dicts.
        """
        sessions = []

        for path in self.sessions_dir.glob("*.jsonl"):
            try:
                # Read just the metadata line
                with open(path) as f:
                    first_line = f.readline().strip()
                    if first_line:
                        data = json.loads(first_line)
                        if data.get("_type") == "metadata":
                            key = path.stem.replace("_", ":", 1)
                            if channel and not key.startswith(f"{channel}:"):
                                continue

                            metadata = data.get("metadata", {})
                            if (
                                backfill_session_title
                                and key.startswith("web:")
                                and not metadata.get("sessionTitle")
                            ):
                                title = self.ensure_session_title(key)
                                if title:
                                    metadata = {**metadata, "sessionTitle": title}

                            sessions.append({
                                "key": key,
                                "created_at": data.get("created_at"),
                                "updated_at": data.get("updated_at"),
                                "metadata": metadata,
                                "path": str(path)
                            })
            except Exception:
                continue

        return sorted(sessions, key=lambda x: x.get("updated_at", ""), reverse=True)
