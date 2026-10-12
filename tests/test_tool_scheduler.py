"""Event-driven scheduling and Agent integration contracts."""

import asyncio
import inspect
import json
import unittest
from unittest.mock import Mock, patch

from test_agent_todo import ScriptedProvider, process, setup_loop

from nanobot.config.loader import load_config
from nanobot.config.schema import ToolsConfig
from nanobot.harness.compress import compress_tool_result
from nanobot.harness.loop import AgentLoop
from nanobot.harness.tools.base import Tool
from nanobot.harness.tools.mcp import MCPTool
from nanobot.harness.tools.rag import AbsurdNovelKnowledgeSearchTool
from nanobot.harness.tools.registry import ToolRegistry
from nanobot.harness.tools.shell import ExecTool
from nanobot.harness.tools.skills import LoadSkillTool
from nanobot.harness.tools.web import WebFetchTool, WebSearchTool
from nanobot.mcp.types import DiscoveredMCPTool
from nanobot.providers.base import LLMResponse, ToolCallRequest


def call(index, name="controlled", **extra):
    params = {"index": index, **extra}
    return ToolCallRequest(str(index), name, json.dumps(params), params)


async def wait(event):
    await asyncio.wait_for(event.wait(), timeout=5)


class ControlledTool(Tool):
    name = "controlled"
    description = "Event-controlled tool"
    parameters = {"type": "object", "properties": {"index": {"type": "integer"}}, "required": ["index"]}

    def __init__(self, count):
        self.started = [asyncio.Event() for _ in range(count)]
        self.release = [asyncio.Event() for _ in range(count)]
        self.finished = [asyncio.Event() for _ in range(count)]
        self.order = []
        self.tasks = []

    def isConcurrencySafe(self, params):  # noqa: N802
        if params.get("bad_check"):
            raise RuntimeError("check failed")
        return params.get("safe", True)

    async def execute(self, index, **params):
        self.tasks.append(asyncio.current_task())
        self.order.append(index)
        self.started[index].set()
        try:
            await self.release[index].wait()
            if params.get("fail"):
                raise RuntimeError("ordinary failure")
            return str(index) * 1000
        finally:
            self.finished[index].set()


class SchedulerTests(unittest.IsolatedAsyncioTestCase):
    def registry(self, count):
        tool = ControlledTool(count)
        registry = ToolRegistry()
        registry.register(tool)
        return registry, tool

    async def test_dynamic_refill_order_and_duplicate_names(self):
        registry, tool = self.registry(6)
        task = asyncio.create_task(registry.execute_batch([call(i) for i in range(6)], max_concurrency=4))
        for event in tool.started[:4]:
            await wait(event)
        self.assertEqual(tool.order, [0, 1, 2, 3])
        tool.release[2].set()
        await wait(tool.started[4])
        self.assertFalse(tool.started[5].is_set())
        tool.release[4].set()
        await wait(tool.started[5])
        for event in tool.release:
            event.set()
        self.assertEqual(await task, [str(i) * 1000 for i in range(6)])
        self.assertEqual(tool.order, list(range(6)))
        self.assertTrue(all(t.done() for t in tool.tasks))

    async def test_barriers_failure_and_safety_exception(self):
        for serial_params in [{"safe": False}, {"bad_check": True}, {"safe": 1}]:
            registry, tool = self.registry(5)
            task = asyncio.create_task(registry.execute_batch([
                call(0, fail=True), call(1), call(2, **serial_params),
                call(3, safe=False), call(4),
            ], max_concurrency=4))
            await wait(tool.started[1])
            tool.release[0].set()
            await wait(tool.finished[0])
            self.assertFalse(tool.started[2].is_set())
            tool.release[1].set()
            await wait(tool.started[2])
            self.assertFalse(tool.started[3].is_set())
            tool.release[2].set()
            await wait(tool.started[3])
            self.assertFalse(tool.started[4].is_set())
            tool.release[3].set()
            await wait(tool.started[4])
            tool.release[4].set()
            results = await task
            self.assertIn("ordinary failure", results[0])
            self.assertEqual(results[4], "4" * 1000)

    async def test_limit_one_and_cancel_stops_refill(self):
        registry, tool = self.registry(3)
        task = asyncio.create_task(registry.execute_batch([call(i) for i in range(3)], max_concurrency=1))
        await wait(tool.started[0])
        self.assertEqual(tool.order, [0])
        tool.release[0].set()
        await wait(tool.started[1])
        self.assertEqual(tool.order, [0, 1])
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(tool.started[2].is_set())
        self.assertTrue(tool.finished[1].is_set())
        self.assertTrue(all(t.done() for t in tool.tasks))

    async def test_cancel_multiple_active_and_no_partial_results(self):
        registry, tool = self.registry(6)
        task = asyncio.create_task(registry.execute_batch([call(i) for i in range(6)], max_concurrency=4))
        await wait(tool.started[3])
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(tool.order, [0, 1, 2, 3])
        self.assertTrue(all(t.done() for t in tool.tasks))

    async def test_unknown_invalid_and_execute_fallback_continue(self):
        registry, tool = self.registry(1)
        tool.release[0].set()
        invalid = ToolCallRequest("invalid", tool.name, "{}", {})
        results = await registry.execute_batch([call(0, "missing"), invalid, call(0)], max_concurrency=4)
        self.assertIn("not found", results[0])
        self.assertIn("Invalid parameters", results[1])
        self.assertEqual(results[2], "0" * 1000)
        with patch.object(registry, "execute", side_effect=RuntimeError("fallback")):
            results = await registry.execute_batch([call(0), call(0)], max_concurrency=4)
        self.assertEqual(results, ["Error executing controlled: fallback"] * 2)

    async def test_shell_mcp_and_unknown_are_serial_barriers(self):
        for name in ["exec_command", "mcp_test_read", "unknown"]:
            registry, tool = self.registry(3)
            registry.register(ExecTool())
            registry.register(MCPTool(DiscoveredMCPTool("test", "read", "read", {}), Mock()))
            original = registry.execute

            async def execute(tool_name, params):
                if tool_name == tool.name:
                    return await original(tool_name, params)
                # Keep the real safety policy while controlling the barrier's duration.
                return await tool.execute(params["index"])

            with patch.object(registry, "execute", side_effect=execute):
                task = asyncio.create_task(registry.execute_batch(
                    [call(0), call(1, name), call(2)], max_concurrency=4,
                ))
                await wait(tool.started[0])
                self.assertEqual(tool.order, [0])
                tool.release[0].set()
                await wait(tool.started[1])
                self.assertEqual(tool.order, [0, 1])
                tool.release[1].set()
                await wait(tool.started[2])
                tool.release[2].set()
                self.assertEqual(await task, [str(i) * 1000 for i in range(3)])

    async def test_defaults_config_and_empty_batch(self):
        registry = ToolRegistry()
        self.assertEqual(ToolsConfig().max_concurrency, 4)
        for invalid in [0, -1, True, False, 1.5, 2.0, "2", None]:
            with self.assertRaises(ValueError):
                ToolsConfig(max_concurrency=invalid)
            with self.assertRaises(ValueError):
                await registry.execute_batch([], max_concurrency=invalid)
        self.assertEqual(await registry.execute_batch([], max_concurrency=4), [])
        for cls in [ExecTool, MCPTool]:
            self.assertIs(cls.isConcurrencySafe, Tool.isConcurrencySafe)
        self.assertFalse(Tool.isConcurrencySafe(None, {}))
        for cls in [WebSearchTool, WebFetchTool, LoadSkillTool, AbsurdNovelKnowledgeSearchTool]:
            self.assertIs(cls.isConcurrencySafe(None, {}), True)


class AgentBatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_response_adds_no_tool_snapshot(self):
        from nanobot.harness.status import AgentStatus

        loop, sessions, _ = setup_loop(self, ScriptedProvider(LLMResponse("done")))
        with patch.object(AgentStatus, "snapshot", return_value="user status") as snapshot:
            await process(loop)
        self.assertEqual(snapshot.call_count, 1)
        self.assertEqual([r["role"] for r in sessions.get("cli:one").messages], ["user", "assistant"])

    async def test_main_batch_waits_last_finishes_first_and_clips_independently(self):
        provider = ScriptedProvider(LLMResponse(None, [call(0), call(1)]), LLMResponse("done"))
        loop, sessions, _ = setup_loop(self, provider)
        loop.max_tool_result_tokens = 20
        tool = ControlledTool(2)
        loop.tools.register(tool)
        task = asyncio.create_task(process(loop))
        await wait(tool.started[1])
        tool.release[1].set()
        await wait(tool.finished[1])
        self.assertEqual(len(provider.calls), 1)
        self.assertFalse(any(r["role"] == "tool" for r in sessions.get("cli:one").messages))
        tool.release[0].set()
        await task
        records = [r for r in sessions.get("cli:one").messages if r["role"] == "tool"]
        self.assertEqual([r["tool_call_id"] for r in records], ["0", "1"])
        self.assertNotIn("agent_status", records[0])
        self.assertIn("agent_status", records[1])
        projected = [m for m in provider.calls[1]["messages"] if m["role"] == "tool"]
        for index, record in enumerate(records):
            self.assertEqual(record["content"], compress_tool_result(str(index) * 1000, 20))
            self.assertEqual(projected[index]["content"], record["content"] + (
                "\n\n" + record["agent_status"] if index == 1 else ""))

    async def test_main_cancellation_does_not_persist_partial_batch(self):
        provider = ScriptedProvider(LLMResponse(None, [call(0), call(1)]))
        loop, sessions, _ = setup_loop(self, provider)
        tool = ControlledTool(2)
        loop.tools.register(tool)
        task = asyncio.create_task(process(loop))
        await wait(tool.started[1])
        tool.release[0].set()
        await wait(tool.finished[0])
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(any(r["role"] == "tool" for r in sessions.get("cli:one").messages))
        self.assertTrue(all(t.done() for t in tool.tasks))

    async def test_subagents_have_independent_limits_and_ordered_clipped_results(self):
        providers = [ScriptedProvider(LLMResponse(None, [call(0), call(1)]), LLMResponse("done")) for _ in range(2)]
        loops = [setup_loop(self, provider)[0] for provider in providers]
        controls = [ControlledTool(2), ControlledTool(2)]
        registries = []
        for tool in controls:
            registry = ToolRegistry()
            registry.register(tool)
            registries.append(registry)
        for loop in loops:
            loop.subagents.max_tool_concurrency = 1
            loop.subagents.max_tool_result_tokens = 20
        with patch("nanobot.harness.subagent.ToolRegistry", side_effect=registries):
            tasks = [asyncio.create_task(loop.subagents._run_subagent(
                str(i), "work", "label", {"channel": "cli", "chat_id": "one"},
            )) for i, loop in enumerate(loops)]
            for tool in controls:
                await wait(tool.started[0])
                self.assertFalse(tool.started[1].is_set())
            self.assertTrue(all(len(p.calls) == 1 for p in providers))
            for tool in controls:
                tool.release[0].set()
                await wait(tool.started[1])
                tool.release[1].set()
            await asyncio.gather(*tasks)
        for provider in providers:
            results = [m for m in provider.calls[1]["messages"] if m["role"] == "tool"]
            self.assertEqual([m["tool_call_id"] for m in results], ["0", "1"])
            self.assertEqual([m["content"] for m in results], [compress_tool_result(str(i) * 1000, 20) for i in range(2)])
            self.assertNotIn("agent_status", json.dumps(provider.calls))

    async def test_config_loader_and_propagation(self):
        from nanobot.cli import commands

        loop, sessions, root = setup_loop(self, ScriptedProvider())
        path = root / "config.json"
        path.write_text('{"tools":{"maxConcurrency":2}}', encoding="utf-8")
        config = load_config(path)
        configured = AgentLoop(
            loop.bus, loop.provider, root, session_manager=sessions,
            max_tool_concurrency=config.tools.max_concurrency,
        )
        self.assertEqual(configured.max_tool_concurrency, 2)
        self.assertEqual(configured.subagents.max_tool_concurrency, 2)
        for entry in [commands.agent, commands.gateway]:
            self.assertIn("max_tool_concurrency=config.tools.max_concurrency", inspect.getsource(entry))
        path.write_text('{"tools":{"maxConcurrency":true}}', encoding="utf-8")
        self.assertEqual(load_config(path).tools.max_concurrency, 4)
