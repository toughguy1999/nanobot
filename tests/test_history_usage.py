"""Deterministic full-request token estimates."""

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from nanobot.config.schema import HistoryCompressionConfig
from nanobot.harness.compress.service import HistoryCompressionService
from nanobot.harness.compress.token_estimate import (
    IMAGE_TOKEN_ESTIMATE,
    estimate_payload_tokens,
)
from nanobot.harness.session.history import to_llm_messages
from nanobot.harness.session.manager import SessionManager
from nanobot.providers.base import LLMResponse
from tests.test_agent_todo import ScriptedProvider, process, setup_loop


class StructuredEstimateTests(unittest.TestCase):
    def test_images_have_fixed_cost_and_request_components_are_counted(self):
        short = [{
            "role": "user",
            "content": [{"type": "image_url", "image_url": {"url": "data:x,a"}}],
        }]
        long = [{
            "role": "user",
            "content": [{"type": "image_url", "image_url": {"url": "data:x," + "A" * 100000}}],
        }]
        self.assertEqual(estimate_payload_tokens(short), estimate_payload_tokens(long))
        self.assertGreaterEqual(estimate_payload_tokens(short), IMAGE_TOKEN_ESTIMATE)

        tools = [{
            "type": "function",
            "function": {
                "name": "read",
                "description": "read a file",
                "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
            },
        }]
        self.assertGreater(
            estimate_payload_tokens({"messages": short, "tools": tools}),
            estimate_payload_tokens(short),
        )

    def test_raw_history_reuses_provider_projection_without_loading_images(self):
        records = [{
            "id": "user",
            "role": "user",
            "content": [{
                "type": "image_url",
                "image_url": {"blob": {"path": "missing.png"}},
            }],
            "created_at": datetime.now().isoformat(),
            "agent_status": "status",
        }]
        with patch(
            "nanobot.harness.session.history.SessionBlobStore.read_data_url",
            side_effect=AssertionError("estimation must not load blobs"),
        ):
            estimate = estimate_payload_tokens(
                to_llm_messages(records, resolve_images=False),
            )
        self.assertGreaterEqual(estimate, IMAGE_TOKEN_ESTIMATE)


class FullEstimateTests(unittest.TestCase):
    def test_service_always_estimates_the_actual_messages_and_tools(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("nanobot.harness.session.manager.PROJECT_ROOT", Path(directory)):
                sessions = SessionManager()
            service = HistoryCompressionService(HistoryCompressionConfig(), sessions)
            messages = [{"role": "system", "content": "system"}]
            tools = [{"type": "function", "function": {"name": "x", "parameters": {}}}]
            self.assertEqual(
                service.estimate_request(messages=messages, tools=tools),
                estimate_payload_tokens({"messages": messages, "tools": tools}),
            )


class FullEstimateLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_sparse_tool_batch_estimates_actual_projection(self):
        from nanobot.providers.base import ToolCallRequest

        provider = ScriptedProvider(LLMResponse(None, [
            ToolCallRequest(name, "missing", "{}", {}) for name in ["a", "b"]
        ]), LLMResponse("done"))
        loop, _, _ = setup_loop(self, provider)
        with patch.object(
            loop.history_compression, "estimate_request",
            wraps=loop.history_compression.estimate_request,
        ) as estimate:
            await process(loop)
        request = estimate.call_args_list[-1].kwargs
        self.assertEqual(request["messages"], provider.calls[1]["messages"])
        tools = [m for m in request["messages"] if m["role"] == "tool"]
        self.assertEqual(sum(m["content"].count("<agent_status>") for m in tools), 1)
        self.assertEqual(loop.history_compression.estimate_request(**request), estimate_payload_tokens(request))

    async def test_each_main_request_is_fully_estimated(self):
        loop, _, _ = setup_loop(
            self,
            ScriptedProvider(LLMResponse("one"), LLMResponse("two")),
        )
        estimates: list[int] = []
        original = loop.history_compression.estimate_request

        def estimate(**kwargs):
            result = original(**kwargs)
            estimates.append(result)
            return result

        with patch.object(loop.history_compression, "estimate_request", side_effect=estimate):
            await process(loop)
            await process(loop, text="again")
        self.assertEqual(len(estimates), 2)
        self.assertTrue(all(value > 0 for value in estimates))


if __name__ == "__main__":
    unittest.main()
