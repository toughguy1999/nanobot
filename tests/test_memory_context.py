"""Memory initialization and per-turn index projection contracts."""

import tempfile
import unittest
from pathlib import Path

from nanobot.cli.commands import _create_workspace_templates
from nanobot.harness.context import ContextBuilder
from nanobot.harness.prompts import get_memory_usage_rules, get_user_context
from nanobot.utils.helpers import ensure_memory_workspace


class MemoryContextTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.workspace = Path(temp.name)

    def test_initialization_preserves_index_and_user_files(self):
        for initialize in (ensure_memory_workspace, ContextBuilder, _create_workspace_templates):
            with self.subTest(initialize=initialize.__name__):
                workspace = self.workspace / initialize.__name__
                workspace.mkdir()
                initialize(workspace)
                index = workspace / 'memory' / 'MEMORY.md'
                self.assertEqual(index.read_bytes(), b'')
                self.assertFalse((index.parent / 'HISTORY.md').exists())
                original = '- [user.md](user.md) — 中文偏好\n'
                index.write_text(original, encoding='utf-8')
                instructions = workspace / 'AGENTS.md'
                instructions.write_text('USER_INSTRUCTIONS', encoding='utf-8')
                custom_skill = workspace / 'skills' / 'memory' / 'SKILL.md'
                custom_skill.parent.mkdir(parents=True, exist_ok=True)
                custom_skill.write_text('CUSTOM_SKILL', encoding='utf-8')
                initialize(workspace)
                self.assertEqual(index.read_text(encoding='utf-8'), original)
                self.assertEqual(instructions.read_text(encoding='utf-8'), 'USER_INSTRUCTIONS')
                self.assertEqual(custom_skill.read_text(encoding='utf-8'), 'CUSTOM_SKILL')

    def test_full_index_in_user_context_without_topic_expansion(self):
        context = ContextBuilder(self.workspace)
        index = ''.join(f'- [topic.md](topic.md) — 索引 {i}\n' for i in range(250))
        (self.workspace / 'memory' / 'MEMORY.md').write_text(index, encoding='utf-8')
        (self.workspace / 'memory' / 'topic.md').write_text('TOPIC_BODY', encoding='utf-8')
        messages = context.build_messages_from_llm_history([])
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]['role'], 'system')
        prompt = messages[0]['content']
        self.assertIn(f'<memory_index>\n{index}\n</memory_index>', prompt)
        self.assertEqual(prompt.count('<memory_index>'), 1)
        self.assertLess(prompt.index('# 运行环境'), prompt.index('<memory_index>'))
        self.assertNotIn('TOPIC_BODY', prompt)
        self.assertNotIn('# Memory', prompt)
        self.assertNotIn('Long-term Memory', prompt)

    def test_fresh_reads_and_independent_workspaces(self):
        first = ContextBuilder(self.workspace / 'first')
        second = ContextBuilder(self.workspace / 'second')
        index = first.workspace / 'memory' / 'MEMORY.md'
        for value in ('FIRST_INDEX', 'UPDATED_INDEX'):
            index.write_text(value, encoding='utf-8')
            self.assertIn(f'<memory_index>\n{value}\n</memory_index>', first.build_system_prompt())
            self.assertNotIn(value, second.build_system_prompt())
        self.assertNotIn('FIRST_INDEX', first.build_system_prompt())

    def test_missing_and_blank_index_keep_rules_without_read_side_effects(self):
        context = ContextBuilder(self.workspace)
        index = self.workspace / 'memory' / 'MEMORY.md'
        for content in ('', ' \n\t', None):
            if content is None:
                index.unlink()
            else:
                index.write_text(content, encoding='utf-8')
            prompt = context.build_system_prompt()
            self.assertIn(get_memory_usage_rules(), prompt)
            self.assertNotIn('<memory_index>', prompt)
        self.assertFalse(index.exists())
        ContextBuilder(self.workspace)
        self.assertEqual(index.read_bytes(), b'')
        missing_workspace = self.workspace / 'not_initialized'
        get_user_context(workspace=missing_workspace)
        self.assertFalse(missing_workspace.exists())
