"""Stable per-session blob storage for history attachments."""

from __future__ import annotations

import base64
import mimetypes
import shutil
import uuid
from pathlib import Path
from typing import Any

from nanobot.utils.helpers import PROJECT_ROOT, ensure_dir, safe_filename


class SessionBlobStore:
    """Stores binary blobs referenced by canonical session history."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = ensure_dir(root or PROJECT_ROOT / ".nanobot" / "session_blobs")

    def save_file(
        self,
        *,
        session_key: str,
        source_path: str | Path,
        filename: str,
        mime_type: str | None,
    ) -> dict[str, Any]:
        """Copy a local file into stable session blob storage."""
        source = Path(source_path)
        extension = source.suffix or Path(filename).suffix
        blob_name = f"{uuid.uuid4().hex}{extension.lower()}"
        session_dir = ensure_dir(self.root / safe_filename(session_key.replace(":", "_")))
        destination = session_dir / blob_name
        shutil.copyfile(source, destination)
        resolved_mime = mime_type or mimetypes.guess_type(str(source))[0] or "application/octet-stream"
        relative_path = f"{session_dir.name}/{blob_name}"
        return {"store": "session", "path": relative_path, "mimeType": resolved_mime}

    def read_data_url(self, reference: dict[str, Any]) -> str:
        """Read a stored blob reference as a provider-compatible data URL."""
        if reference.get("store") != "session":
            raise ValueError("unsupported blob store")
        path = reference.get("path")
        if not isinstance(path, str) or not path:
            raise ValueError("blob reference requires path")
        blob_path = (self.root / path).resolve()
        root = self.root.resolve()
        if root not in blob_path.parents and blob_path != root:
            raise ValueError("blob reference escapes session blob store")
        mime_type = reference.get("mimeType") or mimetypes.guess_type(str(blob_path))[0] or "application/octet-stream"
        encoded = base64.b64encode(blob_path.read_bytes()).decode()
        return f"data:{mime_type};base64,{encoded}"
