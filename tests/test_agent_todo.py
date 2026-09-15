"""Session-bound Todo behavior through persistence and the main loop."""

import asyncio
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.todo import TodoEditTool
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest
from nanobot.session.manager import SessionManager


def item(content="work", status="in_progress"):
    return {"content": content, "status": status}


def tool_response(*params):
    return LLMResponse(content=None, tool_calls=[
        ToolCallRequest(str(index), "todoEdit", json.dumps(value), value)
        for index, value in enumerate(params)
    ])


class ScriptedProvider(LLMProvider):
    def __init__(self, *responses):
        super().__init__()
        self.responses = list(responses)
        self.calls = []

    def get_default_model(self):
        return "test-model"

    async def chat(self, **kwargs):
        self.calls.append(copy.deepcopy(kwargs))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def setup_loop(test, provider):
    directory = tempfile.TemporaryDirectory()
    test.addCleanup(directory.cleanup)
    root = Path(directory.name)
    with patch("nanobot.session.manager.PROJECT_ROOT", root):
        sessions = SessionManager()
    # Keep context snapshots and all session writes inside this test's lifetime.
    publisher = patch("nanobot.agent.loop.publish_context")
    publisher.start()
    test.addCleanup(publisher.stop)
    loop = AgentLoop(MessageBus(), provider, root, session_manager=sessions)
    return loop, sessions, root


async def process(loop, text="continue", key="one", system=False):
    return await loop._process_message(InboundMessage(
        channel="system" if system else "cli",
        sender_id="worker" if system else "user",
        chat_id=f"cli:{key}" if system else key,
        content=text,
    ), emit_events=False)


class TodoToolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _, self.sessions, self.root = setup_loop(self, ScriptedProvider())
        self.session = self.sessions.get_or_create("cli:one")
        self.registry = ToolRegistry()
        self.registry.register(TodoEditTool(self.session, self.sessions))

    async def update(self, params):
        return await self.registry.execute("todoEdit", params)

    def reload(self):
        with patch("nanobot.session.manager.PROJECT_ROOT", self.root):
            return SessionManager().get("cli:one")

    async def test_replace_reorder_reopen_clear_and_detach_input(self):
        params = {"todos": [item(" first "), item("second")]}
        self.assertEqual(await self.update(params), "Todo list updated: 2 items.")
        params["todos"][0]["content"] = "mutated"
        self.assertEqual(self.session.metadata["todos"], [item("first"), item("second")])
        self.assertEqual(self.reload().metadata, self.session.metadata)
        for todos in [
            [item("second", "completed"), item("first", "pending")],
            [item("second", "pending")],
            [],
        ]:
            self.assertNotIn("Error", await self.update({"todos": todos}))
            self.assertEqual(self.reload().metadata["todos"], todos)

    async def test_invalid_requests_leave_memory_and_disk_unchanged(self):
        await self.update({"todos": [item()]})
        old_bytes = self.sessions._get_session_path(self.session.key).read_bytes()
        for params in [
            {}, {"todos": None}, {"todos": "bad"}, {"todos": [None]},
            {"todos": [{}]}, {"todos": [{"content": "x"}]},
            {"todos": [item(status="invalid")]}, {"todos": [item("  \n ")]},
            {"todos": [item(123)]}, {"todos": [dict(item(), id="x")]},
            {"todos": [], "session_id": "other"},
        ]:
            with self.subTest(params=params):
                self.assertIn("Error", await self.update(params))
                self.assertEqual(self.session.metadata["todos"], [item()])
                self.assertEqual(self.sessions._get_session_path(self.session.key).read_bytes(), old_bytes)

    async def test_save_failure_rolls_back_existing_and_missing_field(self):
        for has_todos in [False, True]:
            self.session.metadata = {"title": "keep"}
            if has_todos:
                self.session.metadata["todos"] = [item("old")]
            self.sessions.save(self.session)
            previous = copy.deepcopy(self.session.metadata)
            # Fail the actual atomic replacement, after temporary data is written.
            with patch("nanobot.session.manager.os.replace", side_effect=OSError("disk failure")):
                self.assertIn("Error", await self.update({"todos": [item("new")]}))
            self.assertEqual(self.session.metadata, previous)
            self.assertEqual(self.reload().metadata, previous)
            self.assertFalse(list(self.sessions.sessions_dir.glob("*.tmp")))

    async def test_interleaved_bound_instances(self):
        other = self.sessions.get_or_create("cli:two")
        second = ToolRegistry()
        second.register(TodoEditTool(other, self.sessions))
        await self.update({"todos": [item("one")]})
        await second.execute("todoEdit", {"todos": [item("two")]})
        await self.update({"todos": [item("one-again")]})
        self.assertEqual(self.reload().metadata["todos"], [item("one-again")])
        self.assertEqual(self.sessions.get("cli:two", refresh=True).metadata["todos"], [item("two")])


class TodoLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_batch_updates_and_system_notification_use_original_session(self):
        provider = ScriptedProvider(
            tool_response({"todos": [item("first")]}, {"todos": [item("last")]}),
            LLMResponse("done"),
            tool_response({"todos": [item("system")]}), LLMResponse("done"),
        )
        loop, sessions, _ = setup_loop(self, provider)
        await process(loop)
        self.assertEqual(sessions.get("cli:one").metadata["todos"], [item("last")])
        await process(loop, system=True)
        self.assertEqual(sessions.get("cli:one").metadata["todos"], [item("system")])
        self.assertFalse(loop.tools.has("todoEdit"))
        for call in provider.calls:
            self.assertIn("todoEdit", [t["function"]["name"] for t in call["tools"]])
        self.assertEqual(sessions.get_or_create("cli:new").metadata, {})

    async def test_turns_on_two_sessions_do_not_overwrite_each_other(self):
        provider = ScriptedProvider(
            tool_response({"todos": [item("one")]}), LLMResponse("done"),
            tool_response({"todos": [item("two")]}), LLMResponse("done"),
            LLMResponse("continue"),
        )
        loop, sessions, _ = setup_loop(self, provider)
        await process(loop)
        await process(loop, key="two")
        await process(loop)
        self.assertEqual(sessions.get("cli:one").metadata["todos"], [item("one")])
        self.assertEqual(sessions.get("cli:two").metadata["todos"], [item("two")])

    async def test_provider_failure_and_cancellation_preserve_saved_todo(self):
        for ending in [RuntimeError("provider down"), asyncio.CancelledError()]:
            with self.subTest(ending=type(ending).__name__):
                provider = ScriptedProvider(tool_response({"todos": [item()]}), ending)
                loop, sessions, root = setup_loop(self, provider)
                if isinstance(ending, asyncio.CancelledError):
                    with self.assertRaises(asyncio.CancelledError):
                        await process(loop)
                else:
                    result = await process(loop)
                    self.assertIn("provider down", result.content)
                with patch("nanobot.session.manager.PROJECT_ROOT", root):
                    self.assertEqual(SessionManager().get("cli:one").metadata["todos"], [item()])
                self.assertEqual(sessions.get("cli:one").metadata["todos"], [item()])

    async def test_new_clears_todo_but_preserves_other_metadata(self):
        loop, sessions, _ = setup_loop(self, ScriptedProvider())
        session = sessions.get_or_create("cli:one")
        session.metadata = {"todos": [item()], "title": "keep"}
        sessions.save(session)
        loop._consolidate_memory = AsyncMock()
        await process(loop, "/new")
        self.assertEqual(sessions.get("cli:one", refresh=True).metadata, {"title": "keep"})

    async def test_subagent_does_not_gain_todo_tool_or_instructions(self):
        provider = ScriptedProvider(LLMResponse("done"))
        loop, _, _ = setup_loop(self, provider)
        await loop.subagents._run_subagent("test", "work", "label", {"channel": "cli", "chat_id": "one"})
        call = provider.calls[0]
        self.assertNotIn("todoEdit", [t["function"]["name"] for t in call["tools"]])
        self.assertNotIn("todoEdit", call["messages"][0]["content"])
