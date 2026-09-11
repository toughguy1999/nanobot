"""User message IDs survive transport, persistence, and history reload."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.session.manager import SessionManager
from nanobot.webservice.attachments import WebAttachmentStore
from nanobot.webservice.errors import BadRequestError
from nanobot.webservice.service import WebService


class WebMessageIdentityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        with patch("nanobot.session.manager.PROJECT_ROOT", root):
            self.sessions = SessionManager()
        self.service = WebService(self.sessions, WebAttachmentStore(root / "attachments"))
        self.loop = AgentLoop.__new__(AgentLoop)
        self.loop.sessions = self.sessions
        self.loop.memory_window = 100
        self.loop.tools = Mock()
        self.loop.context = Mock()
        self.loop._run_turn = AsyncMock(return_value=None)

    async def process(self, payload):
        prepared = self.service.prepare_message(payload)
        await self.loop._process_message(InboundMessage(
            channel="web", sender_id="browser", chat_id=prepared.session_id,
            content=prepared.content, metadata=prepared.metadata,
        ))

    async def test_repeated_text_keeps_distinct_client_ids_after_disk_reload(self):
        for message_id in ["message-first", "message-second"]:
            await self.process({
                "sessionId": "one", "content": "same text", "messageId": message_id,
            })
        self.sessions._cache.clear()
        messages = self.service.get_session_messages("one")["messages"]
        self.assertEqual([m["id"] for m in messages], ["message-first", "message-second"])
        self.assertEqual([m["content"] for m in messages], ["same text", "same text"])

    async def test_messages_without_client_id_still_get_a_server_id(self):
        await self.process({"sessionId": "one", "content": "hello"})
        message = self.service.get_session_messages("one")["messages"][0]
        self.assertTrue(message["id"].startswith("msg_"))

    def test_rejects_invalid_client_ids(self):
        for message_id in ["", "  ", 123, [], {}]:
            with self.subTest(message_id=message_id), self.assertRaises(BadRequestError):
                self.service.prepare_message({
                    "sessionId": "one", "content": "hello", "messageId": message_id,
                })
