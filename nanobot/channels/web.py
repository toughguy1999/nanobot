"""Web channel using FastAPI + WebSocket."""

from __future__ import annotations

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState
from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import WebConfig


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

        self._setup_routes()

    def _setup_routes(self) -> None:
        """Set up FastAPI routes."""

        @self.app.get("/status")
        async def status():
            return {"status": "ok"}

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
        await self._ws_manager.send_to(session_id, {"content": msg.content})
