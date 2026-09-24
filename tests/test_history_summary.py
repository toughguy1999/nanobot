"""Third-level history summarization, prompts, and provider assembly."""

import copy
import inspect
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from nanobot.harness.compress.history import build_summary_plan
from nanobot.harness.compress.prompts import build_summary_messages
from nanobot.harness.compress.service import HistoryCompressionService
from nanobot.harness.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.cli import commands
from nanobot.config.schema import Config, HistoryCompressionConfig
from nanobot.providers.base import LLMResponse, ToolCallRequest
from nanobot.harness.session.manager import Session, SessionManager
from tests.test_agent_todo import ScriptedProvider, process, setup_loop


def add_turn(session: Session, label: str, *, size: int = 0) -> list[dict[str, object]]:
    user = session.add_user_message(f"{label}-user" + "x" * size)
    assistant = session.add_assistant_message(f"{label}-assistant")
    return [user, assistant]


class SummaryPlanTests(unittest.TestCase):
    def test_user_turns_budget_current_exception_prelude_and_system_notice(self):
        session = Session("one")
        prelude = session.add_system_message("before first user")
        turns = [add_turn(session, f"turn-{index}", size=300) for index in range(4)]
        session.add_system_message("background belongs to current turn")
        plan = build_summary_plan(
            session.get_effective_records(),
            threshold_tokens=100,
            keep_user_turns=3,
            recent_budget_ratio=0.30,
        )
        self.assertIsNotNone(plan)
        retained_ids = {record["id"] for record in plan.retained_records}
        self.assertIn(turns[-1][0]["id"], retained_ids)
        self.assertIn(turns[-1][1]["id"], retained_ids)
        self.assertEqual(plan.retained_records[-1]["content"], "background belongs to current turn")
        self.assertNotIn(prelude["id"], retained_ids)

        small = Session("small")
        small_prelude = small.add_system_message("prelude")
        add_turn(small, "one")
        add_turn(small, "two")
        small.add_system_message("notice")
        small_plan = build_summary_plan(
            small.get_effective_records(),
            threshold_tokens=1000,
            keep_user_turns=1,
            recent_budget_ratio=1,
        )
        self.assertEqual(small_plan.records_to_summarize[0]["id"], small_prelude["id"])
        self.assertEqual(
            [r["role"] for r in small_plan.retained_records].count("user"),
            1,
        )

    def test_no_user_no_prefix_and_unsafe_tool_boundary_skip(self):
        no_user = Session("none")
        no_user.add_system_message("background")
        self.assertIsNone(build_summary_plan(
            no_user.get_effective_records(),
            threshold_tokens=10,
            keep_user_turns=1,
            recent_budget_ratio=1,
        ))

        one_turn = Session("current")
        add_turn(one_turn, "only")
        self.assertIsNone(build_summary_plan(
            one_turn.get_effective_records(),
            threshold_tokens=10,
            keep_user_turns=1,
            recent_budget_ratio=1,
        ))

        unsafe = Session("unsafe")
        unsafe.add_user_message("old")
        unsafe.add_assistant_message("calling", tool_calls=[{
            "id": "call",
            "type": "function",
            "function": {"name": "read", "arguments": "{}"},
        }])
        unsafe.add_user_message("current")
        unsafe.add_tool_result(tool_call_id="call", name="read", content="late")
        self.assertIsNone(build_summary_plan(
            unsafe.get_effective_records(),
            threshold_tokens=10,
            keep_user_turns=1,
            recent_budget_ratio=1,
        ))

        safe = Session("safe")
        safe.add_user_message("old")
        safe.add_assistant_message("calling", tool_calls=[{
            "id": "call",
            "type": "function",
            "function": {"name": "read", "arguments": "{}"},
        }])
        result = safe.add_tool_result(tool_call_id="call", name="read", content="done")
        safe.add_user_message("current")
        safe_plan = build_summary_plan(
            safe.get_effective_records(),
            threshold_tokens=10,
            keep_user_turns=1,
            recent_budget_ratio=1,
        )
        self.assertEqual(safe_plan.summary_through_id, result["id"])


class SummaryPromptTests(unittest.TestCase):
    def test_material_is_text_only_and_does_not_read_image_blobs(self):
        records = [{
            "id": "user",
            "role": "user",
            "created_at": datetime.now().isoformat(),
            "content": [
                {
                    "type": "image_url",
                    "image_url": {
                        "blob": {
                            "store": "session",
                            "path": "SECRET_IMAGE_PATH.png",
                            "mimeType": "image/png",
                        }
                    },
                },
                {"type": "text", "text": "visible text"},
            ],
            "attachments": [{"fileName": "photo.png", "mimeType": "image/png"}],
            "agent_status": "status",
        }, {
            "id": "assistant",
            "role": "assistant",
            "created_at": datetime.now().isoformat(),
            "content": "working",
            "reasoning_content": "reason",
            "tool_calls": [{
                "id": "call",
                "type": "function",
                "function": {"name": "read", "arguments": '{"path":"a.txt"}'},
            }],
        }, {
            "id": "tool",
            "role": "tool",
            "created_at": datetime.now().isoformat(),
            "tool_call_id": "call",
            "name": "read",
            "content": "[历史工具结果已清理]",
        }]
        with patch(
            "nanobot.harness.session.history.SessionBlobStore.read_data_url",
            side_effect=AssertionError("must not read blobs"),
        ):
            messages = build_summary_messages(
                existing_summary="prior summary",
                records=records,
                summary_budget_tokens=123,
            )
        self.assertEqual([message["role"] for message in messages], ["system", "user"])
        material = messages[1]["content"]
        self.assertIn("prior summary", material)
        self.assertIn("visible text", material)
        self.assertIn("photo.png", material)
        self.assertIn('{"path":"a.txt"}', material)
        self.assertIn("[历史工具结果已清理]", material)
        self.assertIn("图片内容未读取", material)
        self.assertNotIn("SECRET_IMAGE_PATH", material)
        self.assertNotIn("data:image", material)


class SummaryServiceTests(unittest.IsolatedAsyncioTestCase):
    def setup_service(self, response, *, threshold=20):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        with patch("nanobot.harness.session.manager.PROJECT_ROOT", root):
            sessions = SessionManager()
        session = sessions.get_or_create("cli:one")
        add_turn(session, "OLD_RAW", size=80)
        add_turn(session, "current", size=80)
        sessions.save(session)
        provider = ScriptedProvider(response)
        config = HistoryCompressionConfig(
            threshold_tokens=threshold,
            keep_user_turns=1,
            recent_budget_ratio=0.3,
            summary_budget_ratio=0.1,
        )
        return sessions, session, provider, HistoryCompressionService(config, sessions)

    async def test_strict_threshold_failures_and_no_safe_prefix_do_not_commit(self):
        sessions, session, provider, service = self.setup_service(LLMResponse("summary"))
        before = copy.deepcopy(session.compression)
        self.assertFalse(await service.maybe_summarize(
            session,
            request_tokens=20,
            summary_provider=provider,
            summary_model="summary-model",
        ))
        self.assertEqual(provider.calls, [])

        for response in [
            RuntimeError("down"),
            LLMResponse("provider error", finish_reason="error"),
            LLMResponse("   "),
        ]:
            provider.responses = [response]
            with self.subTest(response=repr(response)):
                self.assertFalse(await service.maybe_summarize(
                    session,
                    request_tokens=21,
                    summary_provider=provider,
                    summary_model="summary-model",
                ))
                self.assertEqual(session.compression, before)

        current_only = Session("cli:current")
        add_turn(current_only, "only", size=100)
        sessions.save(current_only)
        provider.responses = [LLMResponse("must not be used")]
        calls_before = len(provider.calls)
        self.assertFalse(await service.maybe_summarize(
            current_only,
            request_tokens=21,
            summary_provider=provider,
            summary_model="summary-model",
        ))
        self.assertEqual(len(provider.calls), calls_before)

    async def test_length_over_budget_commits_once_and_ignores_reasoning_calls_usage(self):
        response = LLMResponse(
            "摘要内容很长很长",
            finish_reason="length",
            usage={"total_tokens": 9999},
            reasoning_content="ignore reasoning",
            tool_calls=[ToolCallRequest("call", "danger", "{}", {})],
        )
        sessions, session, provider, service = self.setup_service(response)
        with patch("nanobot.harness.compress.service.logger.warning") as warning:
            self.assertTrue(await service.maybe_summarize(
                session,
                request_tokens=21,
                summary_provider=provider,
                summary_model="summary-model",
            ))
        self.assertEqual(len(provider.calls), 1)
        summary_call = provider.calls[0]
        self.assertEqual([m["role"] for m in summary_call["messages"]], ["system", "user"])
        self.assertIsNone(summary_call["tools"])
        self.assertEqual(summary_call["model"], "summary-model")
        self.assertEqual(summary_call["max_tokens"], 2)
        self.assertEqual(summary_call["temperature"], 0.2)
        self.assertEqual(session.compression.summary, response.content)
        self.assertGreaterEqual(warning.call_count, 2)
        reloaded = sessions.get("cli:one", refresh=True)
        self.assertEqual(reloaded.compression.summary, response.content)

    async def test_save_failure_keeps_pre_summary_state(self):
        sessions, session, provider, service = self.setup_service(LLMResponse("summary"))
        before = copy.deepcopy(session.compression)
        old_bytes = sessions._get_session_path(session.key).read_bytes()
        with patch.object(sessions, "commit_compression", side_effect=OSError("disk full")):
            self.assertFalse(await service.maybe_summarize(
                session,
                request_tokens=21,
                summary_provider=provider,
                summary_model="summary-model",
            ))
        self.assertEqual(session.compression, before)
        self.assertEqual(sessions._get_session_path(session.key).read_bytes(), old_bytes)

    async def test_repeated_summary_merges_only_existing_summary_and_new_prefix(self):
        sessions, session, provider, service = self.setup_service(LLMResponse("SUMMARY_ONE"))
        self.assertTrue(await service.maybe_summarize(
            session,
            request_tokens=21,
            summary_provider=provider,
            summary_model="summary-model",
        ))
        first_boundary = session.compression.summary_through_id
        add_turn(session, "NEW_RAW", size=80)
        add_turn(session, "latest", size=80)
        sessions.save(session)
        provider.responses = [LLMResponse("SUMMARY_TWO")]
        self.assertTrue(await service.maybe_summarize(
            session,
            request_tokens=21,
            summary_provider=provider,
            summary_model="summary-model",
        ))
        second_material = provider.calls[1]["messages"][1]["content"]
        self.assertIn("SUMMARY_ONE", second_material)
        self.assertIn("NEW_RAW", second_material)
        self.assertNotIn("OLD_RAW-user", second_material)
        self.assertEqual(session.compression.summary, "SUMMARY_TWO")
        positions = {r["id"]: i for i, r in enumerate(session.messages)}
        self.assertGreater(
            positions[session.compression.summary_through_id],
            positions[first_boundary],
        )
        self.assertEqual(
            sum(1 for m in session.get_llm_history() if "SUMMARY" in str(m.get("content"))),
            0,
        )


class SummaryLoopAndProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_successful_summary_rebuilds_and_fully_reestimates_main_context(self):
        main = ScriptedProvider(LLMResponse("done", usage={"total_tokens": 30}))
        summary = ScriptedProvider(LLMResponse("COMPACT SUMMARY", usage={"total_tokens": 999}))
        loop, sessions, _ = setup_loop(self, main)
        loop.history_compression.config = HistoryCompressionConfig(
            idle_cleanup_after_seconds=3600,
            threshold_tokens=1,
            keep_user_turns=1,
            recent_budget_ratio=1,
            summary_budget_ratio=1,
            summary_model="summary-model",
        )
        loop.summary_provider = summary
        loop.summary_model = "summary-model"
        session = sessions.get_or_create("cli:one")
        add_turn(session, "OLD_ONE")
        add_turn(session, "OLD_TWO")
        sessions.save(session)
        estimates = []
        original_estimate = loop.history_compression.estimate_request

        def estimate(*args, **kwargs):
            result = original_estimate(*args, **kwargs)
            estimates.append(result)
            return result

        with patch.object(
            loop.history_compression,
            "estimate_request",
            side_effect=estimate,
        ), patch("nanobot.harness.loop.publish_context") as publish:
            await process(loop, text="CURRENT")
        self.assertEqual(len(summary.calls), 1)
        self.assertEqual(len(estimates), 2)
        self.assertIsInstance(estimates[1], int)
        main_messages = main.calls[0]["messages"]
        self.assertIn("[历史上下文摘要]", main_messages[1]["content"])
        self.assertIn("COMPACT SUMMARY", main_messages[1]["content"])
        self.assertNotIn("OLD_ONE-user", str(main_messages))
        self.assertIn("CURRENT", str(main_messages))
        self.assertEqual(publish.call_args_list[0].kwargs["messages"], main_messages)
        self.assertEqual(session.compression.summary, "COMPACT SUMMARY")

    async def test_summary_failure_keeps_second_level_cleanup_for_main_request(self):
        main = ScriptedProvider(LLMResponse("done", usage={"total_tokens": 30}))
        summary = ScriptedProvider(LLMResponse("failed", finish_reason="error"))
        loop, sessions, _ = setup_loop(self, main)
        loop.history_compression.config = HistoryCompressionConfig(
            idle_cleanup_after_seconds=1,
            keep_tool_rounds=0,
            keep_reasoning_blocks=0,
            threshold_tokens=1,
            keep_user_turns=1,
            recent_budget_ratio=0.3,
            summary_budget_ratio=1,
            summary_model="summary-model",
        )
        loop.summary_provider = summary
        loop.summary_model = "summary-model"
        session = sessions.get_or_create("cli:one")
        old_user = session.add_user_message("old user")
        assistant = session.add_assistant_message(
            "old assistant",
            reasoning_content="old thought",
            tool_calls=[{
                "id": "old-call",
                "type": "function",
                "function": {"name": "missing", "arguments": "{}"},
            }],
        )
        assistant["created_at"] = (datetime.now() - timedelta(minutes=1)).isoformat()
        tool = session.add_tool_result(
            tool_call_id="old-call", name="missing", content="SECRET_TOOL_RESULT",
        )
        sessions.save(session)
        with patch("nanobot.harness.loop.publish_context") as publish:
            await process(loop, text="current")
        self.assertEqual(len(summary.calls), 1)
        self.assertNotIn("SECRET_TOOL_RESULT", str(main.calls[0]["messages"]))
        self.assertIn("[历史工具结果已清理]", str(main.calls[0]["messages"]))
        self.assertEqual(publish.call_args_list[0].kwargs["messages"], main.calls[0]["messages"])
        self.assertEqual(session.compression.cleared_tool_through_id, tool["id"])
        self.assertEqual(session.compression.cleared_reasoning_through_id, assistant["id"])
        self.assertIn(old_user["id"], {r["id"] for r in session.messages})

    def test_provider_factory_target_model_reuse_failure_and_agent_isolation(self):
        config = Config()
        config.agents.defaults.model = "gpt-main"
        config.providers.openai.api_key = "main-key"
        config.providers.openai.api_base = "https://main.example/v1"
        config.providers.deepseek.api_key = "summary-key"
        config.providers.deepseek.api_base = "https://summary.example/v1"
        config.agents.defaults.history_compression.summary_model = "deepseek-chat"
        created = object()
        with patch(
            "nanobot.providers.litellm_provider.LiteLLMProvider",
            return_value=created,
        ) as constructor:
            self.assertIs(commands._make_provider(
                config, "deepseek-chat", required=False,
            ), created)
        kwargs = constructor.call_args.kwargs
        self.assertEqual(kwargs["api_key"], "summary-key")
        self.assertEqual(kwargs["api_base"], "https://summary.example/v1")
        self.assertEqual(kwargs["default_model"], "deepseek-chat")
        self.assertEqual(kwargs["provider_name"], "deepseek")

        main = ScriptedProvider()
        config.agents.defaults.history_compression.summary_model = None
        self.assertIs(commands._make_summary_provider(config, main), main)
        config.agents.defaults.history_compression.summary_model = "deepseek-chat"
        with patch.object(commands, "_make_provider", side_effect=RuntimeError("init failed")):
            self.assertIsNone(commands._make_summary_provider(config, main))

        with tempfile.TemporaryDirectory() as directory:
            loop = AgentLoop(
                MessageBus(),
                main,
                Path(directory),
                history_compression=HistoryCompressionConfig(summary_model="deepseek-chat"),
                summary_provider=created,
            )
        self.assertIs(loop.summary_provider, created)
        self.assertIs(loop.subagents.provider, main)
        self.assertIn("summary_provider=summary_provider", inspect.getsource(commands.gateway))
        self.assertIn("summary_provider=summary_provider", inspect.getsource(commands.agent))


if __name__ == "__main__":
    unittest.main()
