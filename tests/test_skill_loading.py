"""Offline checks: uv run --no-sync python -m unittest discover -s tests."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from xml.etree import ElementTree as ET

from nanobot.agent.context import ContextBuilder
from nanobot.agent.loop import AgentLoop
from nanobot.agent.prompts import get_skill_usage_rules
from nanobot.agent.skills import SkillsLoader
from nanobot.agent.subagent import SubagentManager
from nanobot.agent.tools.filesystem import EditFileTool
from nanobot.agent.tools.skills import LoadSkillTool
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMResponse, ToolCallRequest


class SkillLoadingChecks(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.workspace = self.root / "workspace"
        self.builtin = self.root / "builtin"
        self.workspace.mkdir()
        self.builtin.mkdir()
        self.loader = SkillsLoader(self.workspace, self.builtin)
        self.tool = LoadSkillTool(self.loader)

    def skill(self, name, content, *, builtin=False):
        root = self.builtin if builtin else self.workspace / "skills"
        path = root / name / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    async def test_summary_and_xml_dependencies(self):
        body = '\n# Instructions\n```html\n</body><tag>&\n```\n'
        self.skill('example', '---\nname: alias\ndescription: A & <B>\nalways: true\n'
                   'metadata: {"nanobot":{"requires":{"bins":["missing-cli"],'
                   '"env":["SKILL_TEST_TOKEN"]}}}\n---\n' + body)
        self.skill('fallback', 'plain body')
        with patch('nanobot.agent.skills.shutil.which', side_effect=AssertionError):
            self.assertEqual(self.loader.build_skills_summary(),
                             '-example： A & <B>\n-fallback： fallback')
        with patch.dict(os.environ, {}, clear=True), patch('nanobot.agent.skills.shutil.which', return_value=None):
            result = ET.fromstring(await self.tool.execute('example'))
        self.assertEqual(result.findtext('body'), body)
        self.assertEqual(result.findtext('missing_requirements/bin'), 'missing-cli')
        self.assertEqual(result.findtext('missing_requirements/env'), 'SKILL_TEST_TOKEN')
        self.assertTrue(Path(result.findtext('directory')).is_absolute())
        with patch.dict(os.environ, {'SKILL_TEST_TOKEN': 'secret-value'}), patch('nanobot.agent.skills.shutil.which', return_value='/bin/cli'):
            text = await self.tool.execute('example')
        self.assertNotIn('secret-value', text)
        self.assertIsNone(ET.fromstring(text).find('missing_requirements'))
        self.assertEqual(ET.fromstring(await self.tool.execute('alias')).tag, 'skill_error')

    async def test_precedence_failures_and_dynamic_discovery(self):
        self.assertEqual(self.loader.build_skills_summary(), '')
        self.skill('same', 'builtin', builtin=True)
        path = self.skill('same', 'workspace')
        self.assertEqual(self.loader.load_skill('same').body, 'workspace')
        path.write_bytes(b'\xff')
        self.assertEqual(ET.fromstring(await self.tool.execute('same')).tag, 'skill_error')
        with patch.object(Path, 'read_text', side_effect=PermissionError('denied')):
            self.assertIn('denied', await self.tool.execute('same'))
        records = self.loader.list_skills()
        path.unlink()
        with patch.object(self.loader, 'list_skills', return_value=records):
            self.assertEqual(ET.fromstring(await self.tool.execute('same')).tag, 'skill_error')
        for name in ['../same', str(self.builtin / 'same'), r'C:\skills\same', 'unknown<&']:
            self.assertEqual(ET.fromstring(await self.tool.execute(name)).tag, 'skill_error')
        self.skill('new', 'new body')
        self.assertEqual(self.loader.load_skill('new').body, 'new body')

    async def test_outside_link_and_resource_permissions(self):
        path = self.skill('builtin', 'builtin body', builtin=True)
        self.assertEqual(ET.fromstring(await self.tool.execute('builtin')).findtext('body'), 'builtin body')
        self.assertTrue((await EditFileTool(self.workspace).execute(str(path), "builtin", "changed")).startswith('Error:'))
        local = self.skill('escape', 'local')
        original_resolve = Path.resolve

        def resolve(candidate, *args, **kwargs):
            if candidate == local:
                return path
            return original_resolve(candidate, *args, **kwargs)

        # Exercise resolved-link containment without requiring Windows symlink privileges.
        with patch.object(Path, 'resolve', resolve), patch.object(Path, 'read_text', side_effect=AssertionError):
            self.assertIn('outside its skills directory', await self.tool.execute('escape'))

    async def test_context_memory_and_agent_tool_history(self):
        self.skill('example', '---\ndescription: Example\nalways: true\n---\nBODY_MARKER')
        memory = self.workspace / 'memory'
        memory.mkdir()
        (memory / 'MEMORY.md').write_text('LONG_TERM_MARKER', encoding='utf-8')
        with patch('nanobot.agent.skills.BUILTIN_SKILLS_DIR', self.builtin):
            context = ContextBuilder(self.workspace, restrict_to_workspace=True)
            provider = AsyncMock()
            provider.get_default_model = lambda: 'test-model'
            manager = SubagentManager(provider, self.workspace, MessageBus(), restrict_to_workspace=True)
            main = AgentLoop(MessageBus(), provider, self.workspace, session_manager=object(), restrict_to_workspace=True)
        main_prompt = context.build_system_prompt()
        sub_prompt = manager._build_subagent_prompt('test')
        self.assertIn('LONG_TERM_MARKER', main_prompt)
        self.assertNotIn('LONG_TERM_MARKER', sub_prompt)
        for prompt in [main_prompt, sub_prompt]:
            self.assertIn('-example： Example', prompt)
            self.assertIn(get_skill_usage_rules(), prompt)
            self.assertNotIn('BODY_MARKER', prompt)
            self.assertNotIn('# Active Skills', prompt)
        self.assertIs(main.tools.get('load_skill').loader, main.context.skills)
        result = await main.tools.execute('load_skill', {'name': 'example'})
        messages = context.add_tool_result([], 'call1', 'load_skill', result)
        self.assertEqual(messages[0]['role'], 'tool')
        self.assertIn('BODY_MARKER', messages[0]['content'])

        calls = 0

        async def chat(**kwargs):
            nonlocal calls
            calls += 1
            self.assertIn('load_skill', [t['function']['name'] for t in kwargs['tools']])
            if calls <= 2:
                return LLMResponse(None, [ToolCallRequest(str(calls), 'load_skill', '{"name":"example"}', {'name': 'example'})])
            tool_messages = [m for m in kwargs['messages'] if m['role'] == 'tool']
            self.assertEqual(len(tool_messages), 2)
            self.assertTrue(all('BODY_MARKER' in m['content'] for m in tool_messages))
            return LLMResponse('done')

        provider.chat.side_effect = chat
        manager._announce_result = AsyncMock()
        await manager._run_subagent('test', 'test', 'test', {'channel': 'cli', 'chat_id': 'test'})
        self.assertEqual(calls, 3)
        self.assertEqual(manager._announce_result.call_args.args[-1], 'ok')


if __name__ == '__main__':
    unittest.main(verbosity=2)
