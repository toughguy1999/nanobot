"""Response token limits reach LiteLLM for both agent execution paths."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.loader import load_config
from nanobot.providers.base import LLMResponse
from nanobot.providers.litellm_provider import LiteLLMProvider
from nanobot.session.manager import SessionManager


class MaxTokensTests(unittest.IsolatedAsyncioTestCase):
    async def test_configured_limit_reaches_main_and_subagent_requests(self):
        for limit in (20000, 12345):
            with self.subTest(limit=limit), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                config_path = root / 'config.json'
                config_path.write_text(json.dumps({
                    'agents': {'defaults': {'maxTokens': limit}},
                }), encoding='utf-8')
                config = load_config(config_path)
                provider = LiteLLMProvider(default_model='test-model')
                with patch('nanobot.session.manager.PROJECT_ROOT', root):
                    sessions = SessionManager()
                loop = AgentLoop(
                    MessageBus(), provider, root, session_manager=sessions,
                    max_tokens=config.agents.defaults.max_tokens,
                )
                with (
                    patch('nanobot.agent.loop.publish_context'),
                    patch('nanobot.providers.litellm_provider.acompletion',
                          new_callable=AsyncMock) as completion,
                    patch.object(provider, '_parse_response',
                                 return_value=LLMResponse(content='done')),
                    patch.object(loop.subagents, '_announce_result', new_callable=AsyncMock),
                ):
                    await loop._process_message(InboundMessage(
                        channel='cli', sender_id='user', chat_id='test', content='hello',
                    ), emit_events=False)
                    self.assertEqual(completion.await_count, 1)
                    self.assertEqual(completion.call_args.kwargs['max_tokens'], limit)
                    completion.reset_mock()
                    await loop.subagents._run_subagent(
                        'test', 'hello', 'test', {'channel': 'cli', 'chat_id': 'test'},
                    )
                    self.assertEqual(completion.await_count, 1)
                    self.assertEqual(completion.call_args.kwargs['max_tokens'], limit)
