"""Web channel using FastAPI + WebSocket."""

from __future__ import annotations

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from starlette.websockets import WebSocketState

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.channels.web_attachments import (
    DEFAULT_ATTACHMENT_PROMPT,
    MAX_SINGLE_FILE_SIZE,
    AttachmentError,
    WebAttachmentStore,
)
from nanobot.config.schema import WebConfig
from nanobot.session.manager import Session, SessionManager


class WebSocketManager:
    """Manage WebSocket connections."""

    def __init__(self):
        self._connections: dict[str, WebSocket] = {}

    async def connect(self, session_id: str, websocket: WebSocket) -> None:
        """Register a WebSocket connection."""
        self._connections[session_id] = websocket

    async def disconnect(self, session_id: str, websocket: WebSocket) -> None:
        """Remove a WebSocket connection."""
        if self._connections.get(session_id) is websocket:
            self._connections.pop(session_id, None)

    async def send_to(self, session_id: str, data: dict) -> None:
        """Send JSON data to a specific session."""
        websocket = self._connections.get(session_id)
        if websocket:
            try:
                await websocket.send_json(data)
            except Exception as e:
                logger.error(f"Failed to send to {session_id}: {e}")
                await self.disconnect(session_id, websocket)


class WebChannel(BaseChannel):
    """Web channel using FastAPI + WebSocket."""

    name = "web"

    def __init__(self, config: WebConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.host = config.host
        self.port = config.port
        self.app = FastAPI(lifespan=self._lifespan)
        self._server: uvicorn.Server | None = None
        self._ws_manager = WebSocketManager()
        self._sessions = SessionManager()
        self._attachments = WebAttachmentStore()

        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=config.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST"],
            allow_headers=["*"],
        )
        self._setup_routes()

    def _setup_routes(self) -> None:
        """Set up FastAPI routes."""

        @self.app.get("/status")
        async def status():
            return {"status": "ok"}

        @self.app.get("/sessions")
        async def list_sessions():
            sessions = [
                self._serialize_session_summary(item)
                for item in self._sessions.list_sessions(
                    channel=self.name,
                    backfill_session_title=True,
                )
            ]
            return {"sessions": sessions}

        @self.app.post("/sessions")
        async def create_session(payload: dict):
            session_id = self._parse_session_id(payload)
            session = self._sessions.get_or_create(self._session_key(session_id))
            self._sessions.save(session)
            return {"session": self._serialize_session(session)}

        @self.app.get("/sessions/{session_id}/messages")
        async def get_session_messages(session_id: str):
            session = self._sessions.get(self._session_key(session_id), refresh=True)
            if session is None:
                raise HTTPException(status_code=404, detail="session not found")

            return {
                "session": self._serialize_session(session),
                "messages": [
                    self._serialize_message(session, message, index)
                    for index, message in enumerate(session.messages)
                ],
            }

        @self.app.post("/sessions/{session_id}/pin")
        async def pin_session(session_id: str):
            session = self._sessions.update_metadata(
                self._session_key(session_id),
                {"pinned": True},
            )
            if session is None:
                raise HTTPException(status_code=404, detail="session not found")
            return {"session": self._serialize_session(session)}

        @self.app.post("/sessions/{session_id}/unpin")
        async def unpin_session(session_id: str):
            session = self._sessions.update_metadata(
                self._session_key(session_id),
                {"pinned": False},
            )
            if session is None:
                raise HTTPException(status_code=404, detail="session not found")
            return {"session": self._serialize_session(session)}

        @self.app.post("/sessions/{session_id}/delete")
        async def delete_session(session_id: str):
            session_key = self._session_key(session_id)
            deleted = self._sessions.delete(session_key)
            if not deleted:
                raise HTTPException(status_code=404, detail="session not found")
            try:
                self._attachments.delete_session_attachments(session_key)
            except Exception as e:
                logger.warning(f"Failed to delete web attachments for {session_key}: {e}")
            return {"ok": True}

        @self.app.post("/attachments")
        async def upload_attachment(
            session_id: str = Form(..., alias="sessionId"),
            file: UploadFile = File(...),
        ):
            try:
                session_key = self._session_key(session_id)
                content = await file.read(MAX_SINGLE_FILE_SIZE + 1)
                attachment = self._attachments.save_temporary(
                    session_key=session_key,
                    filename=file.filename or "attachment",
                    content=content,
                    mime_type=file.content_type,
                )
                return {"attachment": attachment}
            except AttachmentError as e:
                status_code = 413 if "large" in str(e) else 400
                raise HTTPException(status_code=status_code, detail=str(e)) from e

        @self.app.post("/attachments/validate")
        async def validate_attachments(payload: dict):
            file_ids = payload.get("fileIds")
            session_id = payload.get("sessionId")
            if not isinstance(file_ids, list) or not all(isinstance(item, str) for item in file_ids):
                raise HTTPException(status_code=400, detail="fileIds is required")
            if not isinstance(session_id, str):
                raise HTTPException(status_code=400, detail="sessionId is required")
            try:
                valid, invalid = self._attachments.validate(
                    file_ids,
                    session_key=self._session_key(session_id),
                )
            except (AttachmentError, HTTPException) as e:
                detail = e.detail if isinstance(e, HTTPException) else str(e)
                raise HTTPException(status_code=400, detail=detail) from e
            return {"valid": valid, "invalid": invalid}

        @self.app.websocket("/ws")
        async def ws_endpoint(websocket: WebSocket):
            await self._handle_ws(websocket)

    def _session_key(self, session_id: str) -> str:
        if not session_id or ":" in session_id:
            raise HTTPException(status_code=400, detail="invalid sessionId")
        return f"{self.name}:{session_id}"

    def _parse_session_id(self, payload: dict) -> str:
        session_id = payload.get("sessionId")
        if not isinstance(session_id, str):
            raise HTTPException(status_code=400, detail="sessionId is required")
        self._session_key(session_id)
        return session_id

    def _serialize_session_summary(self, item: dict) -> dict:
        key = item["key"]
        session_id = key.removeprefix(f"{self.name}:")
        metadata = item.get("metadata") or {}
        return {
            "id": session_id,
            "key": key,
            "sessionTitle": metadata.get("sessionTitle"),
            "createdAt": item.get("created_at"),
            "updatedAt": item.get("updated_at"),
            "pinned": bool(metadata.get("pinned", False)),
        }

    def _serialize_session(self, session: Session) -> dict:
        session_id = session.key.removeprefix(f"{self.name}:")
        metadata = session.metadata or {}
        return {
            "id": session_id,
            "key": session.key,
            "sessionTitle": metadata.get("sessionTitle"),
            "createdAt": session.created_at.isoformat(),
            "updatedAt": session.updated_at.isoformat(),
            "pinned": bool(metadata.get("pinned", False)),
        }

    def _serialize_message(self, session: Session, message: dict, index: int) -> dict:
        metadata = {
            key: value
            for key, value in message.items()
            if key not in {"role", "content", "timestamp"}
        }
        if "tools_used" in metadata:
            metadata["toolsUsed"] = metadata.pop("tools_used")

        data = {
            "id": f"{session.key}:{index}",
            "role": message.get("role"),
            "content": message.get("content", ""),
            "createdAt": message.get("timestamp"),
        }
        if metadata:
            data["metadata"] = metadata
        return data

    async def _handle_ws(self, websocket: WebSocket) -> None:
        """Handle WebSocket connection."""
        await websocket.accept()

        session_id: str | None = None

        try:
            while True:
                try:
                    data = await websocket.receive_json()
                except ValueError:
                    await websocket.send_json({"error": "invalid json"})
                    continue
                if not isinstance(data, dict):
                    await websocket.send_json({"error": "invalid json"})
                    continue

                content = data.get("content", "")
                session_id = data.get("sessionId", "")
                attachments = data.get("attachments", [])

                if not isinstance(content, str):
                    await websocket.send_json({"error": "content is required"})
                    continue

                if not session_id or not isinstance(session_id, str):
                    await websocket.send_json({"error": "sessionId is required"})
                    continue

                try:
                    session_key = self._session_key(session_id)
                    attachment_file_ids = self._parse_attachment_ids(attachments)
                    if not content.strip() and not attachment_file_ids:
                        await websocket.send_json({"error": "content is required"})
                        continue

                    prepared_attachments = self._attachments.prepare_for_message(
                        file_ids=attachment_file_ids,
                        session_key=session_key,
                    )
                    bound_attachments = self._attachments.bind_to_message(
                        file_ids=attachment_file_ids,
                        session_key=session_key,
                    )
                except (AttachmentError, HTTPException) as e:
                    detail = e.detail if isinstance(e, HTTPException) else str(e)
                    await websocket.send_json({"error": detail})
                    continue

                # Register connection
                await self._ws_manager.connect(session_id, websocket)

                # Call base class method to handle message
                await self._handle_message(
                    sender_id=session_id,
                    chat_id=session_id,
                    content=content.strip() or DEFAULT_ATTACHMENT_PROMPT,
                    attachments=prepared_attachments.attachments,
                    metadata={
                        "websocket": websocket,
                        "session_key": session_key,
                        "display_content": content.strip() or DEFAULT_ATTACHMENT_PROMPT,
                        "attachments": bound_attachments,
                    },
                )

                # Note: response is sent by ChannelManager's outbound dispatcher.

        except WebSocketDisconnect:
            logger.info(f"WebSocket disconnected: {session_id}")
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
            try:
                if websocket.client_state == WebSocketState.CONNECTED:
                    await websocket.send_json({"error": str(e)})
            except Exception:
                pass
        finally:
            if session_id:
                await self._ws_manager.disconnect(session_id, websocket)

    async def _lifespan(self, app: FastAPI):
        """Application lifecycle management."""
        try:
            self._attachments.cleanup_expired_temporary()
        except Exception as e:
            logger.warning(f"Failed to cleanup expired web attachments: {e}")
        yield
        # Cleanup on shutdown

    async def start(self) -> None:
        """Start FastAPI server."""
        self._running = True
        config = uvicorn.Config(
            self.app,
            host=self.host,
            port=self.port,
            log_level="info"
        )
        self._server = uvicorn.Server(config)
        await self._server.serve()

    async def stop(self) -> None:
        """Stop FastAPI server."""
        self._running = False
        if self._server:
            self._server.should_exit = True

    async def send(self, msg: OutboundMessage) -> None:
        """Handle outbound messages and send to WebSocket."""
        session_id = msg.chat_id  # chat_id is the session_id
        await self._ws_manager.send_to(session_id, {"sessionId": session_id, "content": msg.content})

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
