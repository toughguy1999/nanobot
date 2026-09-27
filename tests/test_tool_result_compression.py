"""Budget invariants, tool boundaries, persistence, and real PowerShell regression."""
import asyncio
import json
import random
import shutil
import unittest
from unittest.mock import AsyncMock, Mock, patch

from loguru import logger
from test_agent_todo import ScriptedProvider, process, setup_loop

from nanobot.config.loader import load_config
from nanobot.config.schema import AgentDefaults
from nanobot.harness.compress import DEFAULT_MAX_TOOL_RESULT_TOKENS, compress_tool_result
from nanobot.harness.compress.token_estimate import estimate_tokens
from nanobot.harness.compress.tool_result import CLIP_NOTICE
from nanobot.harness.loop import AgentLoop
from nanobot.harness.prompts import get_basic_system_prompt, get_file_command_guidelines
from nanobot.harness.tools.filesystem import EditFileTool, WriteFileTool
from nanobot.harness.tools.shell import ExecTool
from nanobot.providers.base import LLMResponse, ToolCallRequest


class CompressionTests(unittest.TestCase):
    def test_weights_thresholds_and_small_budgets(self):
        for text, expected in [('', 0), ('abcd', 1), ('abcde', 2), ('中文あｶ한ᄀ。𠀀', 8), ('中abc😀', 2)]:
            self.assertEqual(estimate_tokens(text), expected)
            self.assertEqual(compress_tool_result(text, expected), text)
        self.assertEqual(compress_tool_result('anything', 0), '')
        self.assertEqual(compress_tool_result('anything', -1), '')
        for budget in range(1, estimate_tokens(CLIP_NOTICE)):
            result = compress_tool_result('中' * 100, budget)
            self.assertTrue(CLIP_NOTICE.startswith(result))
            self.assertLessEqual(estimate_tokens(result), budget)
        self.assertEqual(AgentDefaults().max_tool_result_tokens, DEFAULT_MAX_TOOL_RESULT_TOKENS)
        self.assertEqual(AgentDefaults(max_tool_result_tokens=-1).max_tool_result_tokens, -1)

    def test_line_boundaries_and_single_line(self):
        for newline in ['\n', '\r\n']:
            text = newline.join(['head'] + ['middle'] * 100 + ['tail'])
            result = compress_tool_result(text, 20)
            head, tail = result.split(CLIP_NOTICE)
            self.assertTrue(head.endswith(newline))
            self.assertTrue(tail.endswith('tail'))
            self.assertTrue(text.startswith(head))
            self.assertTrue(text.endswith(tail))
            self.assertFalse(head.endswith('\r'))
        result = compress_tool_result('A' * 100 + 'Z' * 100, 20)
        self.assertTrue(result.startswith('A'))
        self.assertTrue(result.endswith('Z'))

    def test_random_budget_and_order_invariants(self):
        rng = random.Random(73)
        for _ in range(400):
            text = ''.join(rng.choice(['a', '中', '𠀀', '😀', '\r\n', '\n', '한']) for _ in range(150))
            budget = rng.randrange(1, 160)
            result = compress_tool_result(text, budget)
            self.assertLessEqual(estimate_tokens(result), budget)
            if CLIP_NOTICE in result:
                head, tail = result.split(CLIP_NOTICE)
                self.assertTrue(text.startswith(head))
                self.assertTrue(text.endswith(tail))
                self.assertLess(len(head) + len(tail), len(text))
                self.assertFalse(head.endswith('\r'))
                if tail.startswith('\n'):
                    self.assertNotEqual(text[len(text) - len(tail) - 1], '\r')


class IntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_main_and_subagent_results_errors_logs_and_reload(self):
        raw = 'HEAD\n' + 'x' * 1000 + 'MIDDLE_SECRET' + 'x' * 1000 + '\nTAIL'
        for mode in ['success', 'tool_error', 'invalid', 'missing', 'fallback']:
            with self.subTest(mode=mode):
                name = 'missing' if mode == 'missing' else 'exec_command'
                params = {} if mode == 'invalid' else {'command': 'unused'}
                response = LLMResponse(None, tool_calls=[ToolCallRequest('call-id', name, json.dumps(params), params)])
                provider = ScriptedProvider(response, LLMResponse('done'), response, LLMResponse('done'))
                loop, sessions, root = setup_loop(self, provider)
                loop.max_tool_result_tokens = loop.subagents.max_tool_result_tokens = 16
                logs = []
                sink = logger.add(lambda message: logs.append(str(message)))
                self.addCleanup(logger.remove, sink)
                target = 'nanobot.harness.tools.registry.ToolRegistry.execute' if mode == 'fallback' else 'nanobot.harness.tools.shell.ExecTool.execute'
                options = {'side_effect': RuntimeError(raw)} if mode in ['tool_error', 'fallback'] else {'return_value': raw}
                with patch(target, new_callable=AsyncMock, **options), patch('nanobot.harness.loop.publish_context') as publish:
                    await process(loop)
                    await loop.subagents._run_subagent('id', 'task', 'label', {'channel': 'cli', 'chat_id': 'one'})
                record = next(r for r in sessions.get('cli:one').messages if r['role'] == 'tool')
                body = record['content']
                self.assertLessEqual(estimate_tokens(body), 16)
                self.assertNotIn('MIDDLE_SECRET', body)
                self.assertNotIn('MIDDLE_SECRET', ''.join(logs))
                self.assertNotIn('MIDDLE_SECRET', str(publish.call_args_list))
                self.assertIn('<agent_status>', record['agent_status'])
                main = next(m for m in provider.calls[1]['messages'] if m['role'] == 'tool')
                sub = next(m for m in provider.calls[3]['messages'] if m['role'] == 'tool')
                sub_names = [t['function']['name'] for t in provider.calls[2]['tools']]
                self.assertIn('exec_command', sub_names)
                self.assertTrue(set(sub_names).isdisjoint({'read_file', 'list_dir', 'exec'}))
                self.assertEqual(sub['content'], body)
                self.assertEqual(main['content'], body + '\n\n' + record['agent_status'])
                self.assertEqual(sub['tool_call_id'], 'call-id')
                sessions._cache.clear()
                saved = next(r for r in sessions.get('cli:one').messages if r['role'] == 'tool')
                self.assertEqual(saved, record)
                loop.max_tool_result_tokens = 1
                self.assertEqual(sessions.get('cli:one').get_llm_history()[2]['content'], main['content'])

    async def test_all_history_memory_new_and_tool_guidelines(self):
        provider = ScriptedProvider(LLMResponse('done'))
        loop, sessions, root = setup_loop(self, provider)
        self.assertEqual(loop.max_tool_result_tokens, loop.subagents.max_tool_result_tokens)
        memory = root / 'memory' / 'MEMORY.md'
        memory.write_text('- [user.md](user.md) — USER_INDEX', encoding='utf-8')
        topic = root / 'memory' / 'user.md'
        topic.write_text('USER_BODY_UNCHANGED', encoding='utf-8')
        session = sessions.get_or_create('cli:one')
        for i in range(120):
            session.add_message('user', str(i))
        await process(loop)
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(len(session.get_llm_history()), 122)
        self.assertIn('- [user.md](user.md) — USER_INDEX', provider.calls[0]['messages'][0]['content'])
        self.assertNotIn('USER_BODY_UNCHANGED', provider.calls[0]['messages'][0]['content'])
        await process(loop, '/new')
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(session.messages, [])
        self.assertEqual(memory.read_text(encoding='utf-8'), '- [user.md](user.md) — USER_INDEX')
        self.assertEqual(topic.read_text(encoding='utf-8'), 'USER_BODY_UNCHANGED')
        for prompt in [get_basic_system_prompt(), loop.subagents._build_subagent_prompt('task')]:
            self.assertIn(get_file_command_guidelines(), prompt)
            self.assertIn('PowerShell 7', prompt)
        for name in ['read_file', 'list_dir', 'exec']:
            self.assertNotIn(name, loop.tools.tool_names)
        self.assertIn('exec_command', loop.tools.tool_names)
        self.assertFalse(hasattr(loop, '_consolidate_memory'))

    async def test_custom_configuration_reaches_both_agents(self):
        provider = ScriptedProvider()
        loop, sessions, root = setup_loop(self, provider)
        config_path = root / 'config.json'
        config_path.write_text('{"agents":{"defaults":{"maxToolResultTokens":23}}}')
        config = load_config(config_path)
        configured = AgentLoop(loop.bus, provider, root, session_manager=sessions,
                               max_tool_result_tokens=config.agents.defaults.max_tool_result_tokens)
        self.assertEqual(configured.max_tool_result_tokens, 23)
        self.assertEqual(configured.subagents.max_tool_result_tokens, 23)

    async def test_file_behavior(self):
        _, _, root = setup_loop(self, ScriptedProvider())
        path = root / 'nested' / 'file.txt'
        writer, editor = WriteFileTool(), EditFileTool()
        await writer.execute(str(path), '  a\n  a\n')
        self.assertIn('Warning:', await editor.execute(str(path), '  a', 'b'))
        self.assertIn('Error:', await editor.execute(str(path), 'missing', 'b'))
        await editor.execute(str(path), '  a\n  a\n', '  b\n')
        self.assertEqual(path.read_text(), '  b\n')
        await writer.execute(str(path), 'overwrite')
        self.assertEqual(path.read_text(), 'overwrite')
        self.assertIn('覆盖', writer.description)
        self.assertIn('唯一', editor.description)


class ShellTests(unittest.IsolatedAsyncioTestCase):
    @unittest.skipUnless(shutil.which('pwsh'), 'PowerShell 7 required')
    async def test_real_powershell(self):
        _, _, root = setup_loop(self, ScriptedProvider())
        tool = ExecTool(working_dir=str(root))
        result = await tool.execute("'中文'; 'a\"b';\n(Get-Location).Path; [Console]::Error.WriteLine('错误'); exit 7")
        for expected in ['中文', 'a"b', str(root), 'STDERR:', '错误', 'Exit code: 7']:
            self.assertIn(expected, result)
        output = await tool.execute("'x' * 12000")
        self.assertEqual(output.strip(), 'x' * 12000)
        self.assertIn('timed out', await ExecTool(timeout=0.1).execute('Start-Sleep -Seconds 10'))

    async def test_missing_timeout_and_guards(self):
        with patch('nanobot.harness.tools.shell.shutil.which', return_value=None):
            self.assertIn('not found in PATH', await ExecTool().execute('1'))
        proc = Mock(returncode=0)
        proc.communicate = AsyncMock(side_effect=[asyncio.TimeoutError(), (b'', b'')])
        with patch('nanobot.harness.tools.shell.shutil.which', return_value='pwsh'), patch('asyncio.create_subprocess_exec', AsyncMock(return_value=proc)):
            self.assertIn('timed out', await ExecTool().execute('1'))
        proc.kill.assert_called_once()
        self.assertEqual(proc.communicate.await_count, 2)
        self.assertIn('blocked', await ExecTool().execute('shutdown /s'))
        self.assertIn('blocked', await ExecTool(restrict_to_workspace=True).execute("Get-Content ../outside"))
