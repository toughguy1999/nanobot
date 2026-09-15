"""Fixed status snapshots survive model conversion, reload, and turn boundaries."""

import asyncio
import copy
import json
import unittest
from unittest.mock import AsyncMock, Mock, patch
from xml.etree import ElementTree

from test_agent_todo import ScriptedProvider, item, process, setup_loop, tool_response

import nanobot.agent.loop as loop_module
from nanobot.agent.status import AgentStatus
from nanobot.agent.tools.base import Tool
from nanobot.bus.events import InboundMessage
from nanobot.providers.base import LLMResponse, ToolCallRequest
from nanobot.session.history import to_llm_messages, validate_history_record
from nanobot.session.manager import Session, SessionManager
from nanobot.webservice.attachments import WebAttachmentStore
from nanobot.webservice.serialization import serialize_assistant_record, serialize_user_record
from nanobot.webservice.service import WebService


class ExplodingTool(Tool):
    name = "explode"
    description = "Fail for testing"
    parameters = {"type": "object", "properties": {}}

    async def execute(self):
        raise RuntimeError("execution failed")


class StatusRecordTests(unittest.TestCase):
    def test_clock_format_empty_todo_labels_and_escaping(self):
        clock = Mock(side_effect=[10.0, 12.9, 52.5])
        status = AgentStatus(clock)
        session = Session("one")
        self.assertEqual(status.snapshot(session),
                         "<agent_status>\n本轮已用时间：2 秒\nTodo：空\n</agent_status>")
        session.metadata["todos"] = [
            item("a</agent_status> & <b>\r\nnext", "pending"),
            item("working"), item("done", "completed"),
        ]
        snapshot = status.snapshot(session)
        self.assertIn("本轮已用时间：42 秒", snapshot)
        self.assertIn("1. [待开始] a&lt;/agent_status&gt; &amp; &lt;b&gt;&#13;&#10;next", snapshot)
        self.assertIn("2. [进行中] working\n3. [已完成] done", snapshot)
        self.assertEqual(ElementTree.fromstring(snapshot).tag, "agent_status")

    def test_string_multimodal_and_system_conversion_preserve_originals(self):
        session = Session("one")
        text = session.add_user_message("hello", agent_status="snapshot")
        image = {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}
        multimodal = session.add_user_message(
            [{"type": "text", "text": "look"}, image], agent_status="snapshot",
        )
        system = session.add_system_message("worker ready", agent_status="snapshot")
        tool = session.add_tool_result(tool_call_id="call", name="test", content="ok", agent_status="snapshot")
        originals = copy.deepcopy(session.messages)
        messages = to_llm_messages(session.messages)
        self.assertEqual(messages[0], {"role": "user", "content": "hello\n\nsnapshot"})
        self.assertEqual(messages[1]["content"], [
            {"type": "text", "text": "look"}, image, {"type": "text", "text": "snapshot"},
        ])
        self.assertEqual(messages[2], {"role": "user", "content": "[System: worker ready]\n\nsnapshot"})
        self.assertEqual(messages[3], {
            "role": "tool", "tool_call_id": "call", "name": "test", "content": "ok\n\nsnapshot",
        })
        self.assertEqual(session.messages, originals)
        self.assertIsNot(messages[1]["content"], multimodal["content"])
        for record in [text, multimodal, system, tool]:
            for value in [None, 0, [], {}]:
                with self.assertRaises(ValueError):
                    validate_history_record(dict(record, agent_status=value))
        with self.assertRaises(ValueError):
            validate_history_record(dict(session.add_assistant_message("final"), agent_status="no"))

    def test_records_without_status_keep_existing_projection(self):
        session = Session("one")
        session.add_user_message("hello")
        session.add_system_message("ready")
        session.add_tool_result(tool_call_id="call", name="test", content="ok")
        session.add_assistant_message("done", reasoning_content="reason")
        self.assertEqual(to_llm_messages(session.messages), [
            {"role": "user", "content": "hello"},
            {"role": "user", "content": "[System: ready]"},
            {"role": "tool", "tool_call_id": "call", "name": "test", "content": "ok"},
            {"role": "assistant", "content": "done", "reasoning_content": "reason"},
        ])


class StatusLoopTests(unittest.IsolatedAsyncioTestCase):
    def clock(self, *times):
        clock = Mock(side_effect=times)
        factory = patch("nanobot.agent.loop.AgentStatus", side_effect=lambda: AgentStatus(clock))
        factory.start()
        self.addCleanup(factory.stop)
        return clock

    async def test_batch_snapshots_are_fixed_and_match_reloaded_messages(self):
        response = tool_response({"todos": [item("first")]}, {"todos": [item("last")]}, {})
        response.tool_calls.extend([
            ToolCallRequest("unknown", "missing", "{}", {}),
            ToolCallRequest("failure", "explode", "{}", {}),
        ])
        provider = ScriptedProvider(response, LLMResponse("done"))
        loop, sessions, root = setup_loop(self, provider)
        loop.tools.register(ExplodingTool())
        self.clock(100, 102.9, 106, 110, 114, 118, 122)
        await process(loop)
        session = sessions.get("cli:one")
        records = [r for r in session.messages if r["role"] != "assistant"]
        for record, seconds in zip(records, [2, 6, 10, 14, 18, 22], strict=True):
            self.assertIn(f"本轮已用时间：{seconds} 秒", record["agent_status"])
            self.assertNotIn("<agent_status>", record["content"])
        self.assertIn("Todo：空", records[0]["agent_status"])
        self.assertIn("first", records[1]["agent_status"])
        for record in records[2:]:
            self.assertIn("last", record["agent_status"])
        for record in records[3:]:
            self.assertIn("Error", record["content"])
        original = copy.deepcopy(records)
        session.metadata["todos"] = [item("future")]
        sessions.save(session)
        with patch("nanobot.session.manager.PROJECT_ROOT", root):
            reloaded = SessionManager().get("cli:one")
        # The provider's second input contains every record except the final reply.
        self.assertEqual(provider.calls[1]["messages"][1:], to_llm_messages(reloaded.messages[:-1]))
        self.assertEqual(records, original)
        self.assertTrue(all("agent_status" not in r for r in session.messages if r["role"] == "assistant"))
        for message in provider.calls[1]["messages"][1:]:
            if message["role"] != "assistant":
                self.assertEqual(message["content"].count("<agent_status>"), 1)
        loop_publish = loop_module.publish_context
        self.assertEqual(loop_publish.call_args.kwargs["messages"][1:], to_llm_messages(session.messages))
        self.assertEqual(loop_publish.call_args.kwargs["tools"], provider.calls[1]["tools"])

    async def test_save_failure_snapshot_displays_old_list(self):
        provider = ScriptedProvider(tool_response({"todos": [item("new")]}), LLMResponse("done"))
        loop, sessions, _ = setup_loop(self, provider)
        session = sessions.get_or_create("cli:one")
        session.metadata["todos"] = [item("old")]
        sessions.save(session)
        self.clock(0, 1, 2)
        with patch("nanobot.session.manager.os.replace", side_effect=OSError("disk full")):
            await process(loop)
        record = next(r for r in session.messages if r["role"] == "tool")
        self.assertIn("Error", record["content"])
        self.assertIn("old", record["agent_status"])
        self.assertNotIn("new", record["agent_status"])
        self.assertEqual(sessions.get("cli:one", refresh=True).metadata["todos"], [item("old")])

    async def test_fresh_clock_across_turns_restart_and_system_notification(self):
        provider = ScriptedProvider(LLMResponse("one"), LLMResponse("two"), LLMResponse("three"))
        loop, sessions, root = setup_loop(self, provider)
        session = sessions.get_or_create("cli:one")
        session.metadata["todos"] = [item("keep")]
        sessions.save(session)
        self.clock(100, 102, 500, 501, 900, 903)
        await process(loop)
        await process(loop, system=True)
        with patch("nanobot.session.manager.PROJECT_ROOT", root):
            loop.sessions = SessionManager()
        await process(loop)
        records = [r for r in loop.sessions.get("cli:one").messages if r["role"] != "assistant"]
        self.assertEqual([r["role"] for r in records], ["user", "system", "user"])
        for record, seconds in zip(records, [2, 1, 3], strict=True):
            self.assertIn(f"本轮已用时间：{seconds} 秒", record["agent_status"])
            self.assertIn("keep", record["agent_status"])
        self.assertTrue(provider.calls[1]["messages"][-1]["content"].endswith(records[1]["agent_status"]))

    async def test_processing_time_included_but_message_age_not_counted(self):
        from nanobot.agent.attachments import stabilize_user_message

        provider = ScriptedProvider(LLMResponse("done"))
        loop, sessions, _ = setup_loop(self, provider)
        now = [10000.0]
        def status_factory():
            return AgentStatus(lambda: now[0])

        def stabilize(**kwargs):
            now[0] += 4.8
            return stabilize_user_message(**kwargs)

        message = InboundMessage("cli", "user", "one", "hello")
        with patch("nanobot.agent.loop.AgentStatus", side_effect=status_factory), patch(
            "nanobot.agent.loop.stabilize_user_message", side_effect=stabilize,
        ):
            await loop._process_message(message, emit_events=False)
        self.assertIn("本轮已用时间：4 秒", sessions.get("cli:one").messages[0]["agent_status"])

    async def test_slash_commands_do_not_generate_snapshots(self):
        loop, sessions, _ = setup_loop(self, ScriptedProvider())
        loop._consolidate_memory = AsyncMock()
        with patch.object(AgentStatus, "snapshot", side_effect=AssertionError("unexpected snapshot")):
            await process(loop, "/help")
            await process(loop, "/new")
        self.assertEqual(sessions.get("cli:one").messages, [])

    async def test_failure_or_cancel_does_not_reuse_timer_next_turn(self):
        for ending in [RuntimeError("failed"), asyncio.CancelledError()]:
            provider = ScriptedProvider(ending, LLMResponse("recovered"))
            loop, sessions, _ = setup_loop(self, provider)
            clock = Mock(side_effect=[10, 11, 500, 502])
            with patch("nanobot.agent.loop.AgentStatus", side_effect=lambda: AgentStatus(clock)):
                if isinstance(ending, asyncio.CancelledError):
                    with self.assertRaises(asyncio.CancelledError):
                        await process(loop)
                else:
                    await process(loop)
                await process(loop)
            users = [r for r in sessions.get("cli:one").messages if r["role"] == "user"]
            self.assertIn("本轮已用时间：1 秒", users[0]["agent_status"])
            self.assertIn("本轮已用时间：2 秒", users[1]["agent_status"])

    async def test_web_projection_excludes_snapshot_and_preserves_identity(self):
        provider = ScriptedProvider(LLMResponse("reply"))
        loop, sessions, root = setup_loop(self, provider)
        self.clock(0, 3)
        await loop._process_message(InboundMessage(
            "web", "browser", "one", "hello",
            metadata={"message_id": "client-id", "display_content": "hello"},
        ), emit_events=False)
        session = sessions.get("web:one")
        self.assertEqual(serialize_user_record(session.messages[0])["id"], "client-id")
        self.assertNotIn("agent_status", serialize_assistant_record(session.messages[-1]))
        service = WebService(sessions, WebAttachmentStore(root / "attachments"))
        dto = service.get_session_messages("one")
        self.assertEqual([m["content"] for m in dto["messages"]], ["hello", "reply"])
        self.assertNotIn("agent_status", json.dumps(dto))
        self.assertEqual(session.messages[0]["content"], "hello")

    async def test_subagent_input_has_no_status_snapshot(self):
        provider = ScriptedProvider(LLMResponse("done"))
        loop, _, _ = setup_loop(self, provider)
        await loop.subagents._run_subagent("test", "work", "label", {"channel": "cli", "chat_id": "one"})
        self.assertNotIn("agent_status", json.dumps(provider.calls))
        self.assertNotIn("状态栏", provider.calls[0]["messages"][0]["content"])
