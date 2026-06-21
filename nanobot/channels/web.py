"""Web channel using FastAPI + WebSocket."""

from __future__ import annotations

from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from starlette.websockets import WebSocketState
from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
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
        }

    def _serialize_session(self, session: Session) -> dict:
        session_id = session.key.removeprefix(f"{self.name}:")
        return {
            "id": session_id,
            "key": session.key,
            "sessionTitle": session.metadata.get("sessionTitle"),
            "createdAt": session.created_at.isoformat(),
            "updatedAt": session.updated_at.isoformat(),
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

                if not content:
                    await websocket.send_json({"error": "content is required"})
                    continue

                if not session_id:
                    await websocket.send_json({"error": "sessionId is required"})
                    continue

                # Register connection
                await self._ws_manager.connect(session_id, websocket)

                # Build session_key
                session_key = f"web:{session_id}"

                # Call base class method to handle message
                await self._handle_message(
                    sender_id=session_id,
                    chat_id=session_id,
                    content=content,
                    metadata={"websocket": websocket, "session_key": session_key}
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
