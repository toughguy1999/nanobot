"""Request-time idle cleanup policy and main-loop context rebuilding."""

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from nanobot.harness.compress.history import build_idle_cleanup_candidate
from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import Config, HistoryCompressionConfig
from nanobot.providers.base import LLMResponse, ToolCallRequest
from nanobot.harness.session.manager import Session
from tests.test_agent_todo import ScriptedProvider, process, setup_loop


def call(call_id: str, name: str = "missing") -> dict[str, object]:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": "{}"},
    }


def stamp(record: dict[str, object], value: datetime) -> None:
    record["created_at"] = value.isoformat()


class CleanupPolicyTests(unittest.TestCase):
    def build_rounds(self, count: int = 4) -> tuple[Session, datetime]:
        session = Session("cli:one")
        start = datetime(2026, 9, 18, 10, 0, 0)
        session.add_user_message("start", agent_status="user status")
        for index in range(count):
            assistant = session.add_assistant_message(
                f"assistant {index}",
                reasoning_content=f"reasoning {index}",
                tool_calls=[call(f"{index}-a"), call(f"{index}-b")],
            )
            stamp(assistant, start + timedelta(seconds=index))
            session.add_tool_result(
                tool_call_id=f"{index}-a",
                name="missing",
                content=f"result {index}-a",
                agent_status=f"tool status {index}-a",
            )
            session.add_tool_result(
                tool_call_id=f"{index}-b",
                name="missing",
                content=f"result {index}-b",
                agent_status=f"tool status {index}-b",
            )
            session.add_system_message(f"notice {index}", agent_status=f"system status {index}")
        return session, start

    def test_idle_boundaries_and_no_assistant(self):
        session = Session("cli:none")
        session.add_user_message("hello")
        now = datetime(2026, 9, 18, 10, 0, 0)
        self.assertIsNone(build_idle_cleanup_candidate(
            session.messages,
            session.compression,
            now=now,
            idle_cleanup_after_seconds=10,
            keep_tool_rounds=0,
            keep_reasoning_blocks=0,
        ))

        session, start = self.build_rounds(1)
        for seconds, expected in [(9.999, False), (10, True)]:
            with self.subTest(seconds=seconds):
                candidate = build_idle_cleanup_candidate(
                    session.messages,
                    session.compression,
                    now=start + timedelta(seconds=seconds),
                    idle_cleanup_after_seconds=10,
                    keep_tool_rounds=0,
                    keep_reasoning_blocks=0,
                )
                self.assertEqual(candidate is not None, expected)

    def test_parallel_batches_retention_zero_and_record_integrity(self):
        session, start = self.build_rounds()
        candidate = build_idle_cleanup_candidate(
            session.messages,
            session.compression,
            now=start + timedelta(hours=1),
            idle_cleanup_after_seconds=10,
            keep_tool_rounds=3,
            keep_reasoning_blocks=1,
        )
        self.assertIsNotNone(candidate)
        tools = [record for record in session.messages if record["role"] == "tool"]
        assistants = [record for record in session.messages if record["role"] == "assistant"]
        self.assertEqual(candidate.cleared_tool_through_id, tools[1]["id"])
        self.assertEqual(candidate.cleared_reasoning_through_id, assistants[2]["id"])
        self.assertIsNone(build_idle_cleanup_candidate(
            session.messages,
            candidate,
            now=start + timedelta(hours=2),
            idle_cleanup_after_seconds=10,
            keep_tool_rounds=3,
            keep_reasoning_blocks=1,
        ))
        self.assertIsNone(build_idle_cleanup_candidate(
            session.messages,
            candidate,
            now=start + timedelta(hours=2),
            idle_cleanup_after_seconds=10,
            keep_tool_rounds=99,
            keep_reasoning_blocks=99,
        ))
        projected = Session(
            "cli:projected",
            messages=session.messages,
            compression=candidate,
        ).get_effective_records()
        original_users_and_system = [
            record for record in session.messages if record["role"] in {"user", "system"}
        ]
        projected_users_and_system = [
            record for record in projected if record["role"] in {"user", "system"}
        ]
        self.assertEqual(projected_users_and_system, original_users_and_system)
        self.assertEqual(projected[2]["content"], "[历史工具结果已清理]")
        self.assertNotIn("agent_status", projected[2])
        self.assertEqual(projected[1]["tool_calls"][0]["id"], projected[2]["tool_call_id"])

        clear_all = build_idle_cleanup_candidate(
            session.messages,
            session.compression,
            now=start + timedelta(hours=1),
            idle_cleanup_after_seconds=10,
            keep_tool_rounds=0,
            keep_reasoning_blocks=0,
        )
        self.assertEqual(clear_all.cleared_tool_through_id, tools[-1]["id"])
        self.assertEqual(clear_all.cleared_reasoning_through_id, assistants[-1]["id"])

    def test_only_existing_results_define_cleanup_boundary(self):
        session, start = self.build_rounds(1)
        last = session.add_assistant_message(
            "partial",
            reasoning_content="latest",
            tool_calls=[call("exists"), call("not-yet")],
        )
        stamp(last, start + timedelta(seconds=5))
        existing = session.add_tool_result(
            tool_call_id="exists", name="missing", content="exists",
        )
        candidate = build_idle_cleanup_candidate(
            session.messages,
            session.compression,
            now=start + timedelta(seconds=15),
            idle_cleanup_after_seconds=10,
            keep_tool_rounds=0,
            keep_reasoning_blocks=1,
        )
        self.assertEqual(candidate.cleared_tool_through_id, existing["id"])


class CompressionConfigTests(unittest.TestCase):
    def test_defaults_camel_case_round_trip_and_invalid_values(self):
        defaults = HistoryCompressionConfig()
        self.assertEqual(defaults.idle_cleanup_after_seconds, 1800)
        self.assertEqual(defaults.keep_tool_rounds, 3)
        self.assertEqual(defaults.keep_reasoning_blocks, 1)
        self.assertEqual(defaults.threshold_tokens, 50000)
        self.assertEqual(defaults.keep_user_turns, 3)
        self.assertEqual(defaults.recent_budget_ratio, 0.30)
        self.assertEqual(defaults.summary_budget_ratio, 0.10)
        self.assertIsNone(defaults.summary_model)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            configured = Config()
            configured.agents.defaults.history_compression = HistoryCompressionConfig(
                idle_cleanup_after_seconds=12,
                keep_tool_rounds=0,
                keep_reasoning_blocks=0,
                threshold_tokens=99,
                keep_user_turns=2,
                recent_budget_ratio=0.4,
                summary_budget_ratio=0.2,
                summary_model="other/model",
            )
            save_config(configured, path)
            raw = json.loads(path.read_text())
            self.assertIn("historyCompression", raw["agents"]["defaults"])
            self.assertEqual(
                raw["agents"]["defaults"]["historyCompression"]["keepToolRounds"],
                0,
            )
            self.assertEqual(
                load_config(path).agents.defaults.history_compression,
                configured.agents.defaults.history_compression,
            )

        invalid = [
            {"idle_cleanup_after_seconds": 0},
            {"keep_tool_rounds": -1},
            {"keep_reasoning_blocks": -1},
            {"threshold_tokens": 0},
            {"keep_user_turns": 0},
            {"recent_budget_ratio": 0},
            {"recent_budget_ratio": 1.1},
            {"summary_budget_ratio": 0},
            {"summary_budget_ratio": 1.1},
            {"summary_model": "  "},
        ]
        for values in invalid:
            with self.subTest(values=values), self.assertRaises(ValueError):
                HistoryCompressionConfig(**values)


class CleanupLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_tool_batch_cleans_only_before_next_request_and_rebuilds_snapshots(self):
        response = LLMResponse(
            content="working",
            reasoning_content="temporary reasoning",
            tool_calls=[
                ToolCallRequest("one", "missing", "{}", {}),
                ToolCallRequest("two", "missing", "{}", {}),
            ],
        )
        provider = ScriptedProvider(response, LLMResponse("done"))
        loop, sessions, _ = setup_loop(self, provider)
        loop.history_compression.config = HistoryCompressionConfig(
            idle_cleanup_after_seconds=10,
            keep_tool_rounds=0,
            keep_reasoning_blocks=0,
        )
        base = datetime.now()
        loop.history_compression.clock = Mock(side_effect=[base, base + timedelta(seconds=20)])

        with patch("nanobot.harness.loop.publish_context") as publish, patch.object(
            loop.history_compression,
            "prepare_for_request",
            wraps=loop.history_compression.prepare_for_request,
        ) as prepare, patch.object(
            loop.context,
            "build_system_prompt",
            wraps=loop.context.build_system_prompt,
        ) as build_system:
            await process(loop)

        self.assertEqual(prepare.call_count, 2)
        self.assertEqual(build_system.call_count, 1)
        self.assertEqual(len(provider.calls), 2)
        first_progress = publish.call_args_list[2].kwargs["messages"]
        second_progress = publish.call_args_list[3].kwargs["messages"]
        self.assertIn("Error: Tool 'missing' not found", first_progress[-1]["content"])
        self.assertIn("Error: Tool 'missing' not found", second_progress[-1]["content"])
        second_request_tools = [
            message for message in provider.calls[1]["messages"] if message["role"] == "tool"
        ]
        self.assertEqual(len(second_request_tools), 2)
        self.assertTrue(all(m["content"] == "[历史工具结果已清理]" for m in second_request_tools))
        second_assistant = next(
            message
            for message in provider.calls[1]["messages"]
            if message["role"] == "assistant" and message["content"] == "working"
        )
        self.assertNotIn("reasoning_content", second_assistant)
        session = sessions.get("cli:one")
        raw_tools = [record for record in session.messages if record["role"] == "tool"]
        self.assertTrue(all("<agent_status>" in r["agent_status"] for r in raw_tools))

    async def test_background_notification_uses_same_cleanup_path(self):
        provider = ScriptedProvider(LLMResponse("done"))
        loop, sessions, _ = setup_loop(self, provider)
        loop.history_compression.config = HistoryCompressionConfig(
            idle_cleanup_after_seconds=10,
            keep_tool_rounds=0,
            keep_reasoning_blocks=0,
        )
        session = sessions.get_or_create("cli:one")
        assistant = session.add_assistant_message(
            "old", tool_calls=[call("old")], reasoning_content="old reasoning",
        )
        stamp(assistant, datetime.now() - timedelta(minutes=1))
        session.add_tool_result(tool_call_id="old", name="missing", content="old result")
        sessions.save(session)
        await process(loop, text="background", system=True)
        tool_message = next(m for m in provider.calls[0]["messages"] if m["role"] == "tool")
        self.assertEqual(tool_message["content"], "[历史工具结果已清理]")

if __name__ == "__main__":
    unittest.main()
