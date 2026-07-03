"""Web channel using FastAPI + WebSocket."""

from __future__ import annotations

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from starlette.websockets import WebSocketState

from nanobot.bus.events import InboundAttachment, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import WebConfig
from nanobot.webservice.attachments import MAX_SINGLE_FILE_SIZE
from nanobot.webservice.errors import (
    AttachmentError,
    AttachmentTooLargeError,
    BadRequestError,
    NotFoundError,
    WebServiceError,
)
from nanobot.webservice.schemas import WebPreparedAttachment
from nanobot.webservice.service import WebService


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
        self._web_service = WebService()

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
            return self._web_service.list_sessions()

        @self.app.post("/sessions")
        async def create_session(payload: dict):
            try:
                return self._web_service.create_session(payload)
            except WebServiceError as e:
                raise self._to_http_exception(e) from e

        @self.app.get("/sessions/{session_id}/messages")
        async def get_session_messages(session_id: str):
            try:
                return self._web_service.get_session_messages(session_id)
            except WebServiceError as e:
                raise self._to_http_exception(e) from e

        @self.app.post("/sessions/{session_id}/pin")
        async def pin_session(session_id: str):
            try:
                return self._web_service.pin_session(session_id)
            except WebServiceError as e:
                raise self._to_http_exception(e) from e

        @self.app.post("/sessions/{session_id}/unpin")
        async def unpin_session(session_id: str):
            try:
                return self._web_service.unpin_session(session_id)
            except WebServiceError as e:
                raise self._to_http_exception(e) from e

        @self.app.post("/sessions/{session_id}/delete")
        async def delete_session(session_id: str):
            try:
                return self._web_service.delete_session(session_id)
            except WebServiceError as e:
                raise self._to_http_exception(e) from e
            except Exception as e:
                logger.warning(f"Failed to delete web session {session_id}: {e}")
                raise HTTPException(status_code=500, detail="failed to delete session") from e

        @self.app.post("/attachments")
        async def upload_attachment(
            session_id: str = Form(..., alias="sessionId"),
            file: UploadFile = File(...),
        ):
            try:
                content = await file.read(MAX_SINGLE_FILE_SIZE + 1)
                return self._web_service.save_attachment(
                    session_id=session_id,
                    filename=file.filename or "attachment",
                    content=content,
                    mime_type=file.content_type,
                )
            except WebServiceError as e:
                raise self._to_http_exception(e) from e

        @self.app.post("/attachments/validate")
        async def validate_attachments(payload: dict):
            file_ids = payload.get("fileIds")
            session_id = payload.get("sessionId")
            if not isinstance(file_ids, list) or not all(isinstance(item, str) for item in file_ids):
                raise HTTPException(status_code=400, detail="fileIds is required")
            if not isinstance(session_id, str):
                raise HTTPException(status_code=400, detail="sessionId is required")
            try:
                return self._web_service.validate_attachments(
                    session_id=session_id,
                    file_ids=file_ids,
                )
            except WebServiceError as e:
                raise self._to_http_exception(e) from e

        @self.app.websocket("/ws")
        async def ws_endpoint(websocket: WebSocket):
            await self._handle_ws(websocket)

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

                try:
                    prepared = self._web_service.prepare_message(data)
                except (AttachmentError, BadRequestError) as e:
                    await websocket.send_json({"error": str(e)})
                    continue

                session_id = prepared.session_id

                # Register connection
                await self._ws_manager.connect(session_id, websocket)

                # Call base class method to handle message
                await self._handle_message(
                    sender_id=session_id,
                    chat_id=session_id,
                    content=prepared.content,
                    attachments=[self._to_inbound_attachment(item) for item in prepared.attachments],
                    metadata=prepared.metadata,
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
            self._web_service.cleanup_expired_temporary_attachments()
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

    def _to_http_exception(self, error: WebServiceError) -> HTTPException:
        status_code = 400
        if isinstance(error, AttachmentTooLargeError):
            status_code = 413
        elif isinstance(error, NotFoundError):
            status_code = 404
        return HTTPException(status_code=status_code, detail=str(error))

    def _to_inbound_attachment(self, attachment: WebPreparedAttachment) -> InboundAttachment:
        return InboundAttachment(
            file_name=attachment.file_name,
            mime_type=attachment.mime_type,
            extension=attachment.extension,
            size=attachment.size,
            type=attachment.type,
            path=attachment.path,
            file_id=attachment.file_id,
            status=attachment.status,
            uploaded_at=attachment.uploaded_at,
        )
