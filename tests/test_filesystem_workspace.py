"""File paths share the shell's workspace in both agent runtimes."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from nanobot.harness.loop import AgentLoop
from nanobot.harness.tools.filesystem import EditFileTool, WriteFileTool
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMResponse, ToolCallRequest


class WorkspacePathTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()

    async def test_relative_paths_with_and_without_restriction(self):
        for restricted in (False, True):
            with self.subTest(restricted=restricted):
                allowed = self.workspace if restricted else None
                writer = WriteFileTool(allowed, workspace=self.workspace)
                editor = EditFileTool(allowed, workspace=self.workspace)
                path = "nested/example.txt"
                self.assertIn("Successfully", await writer.execute(path, "before"))
                self.assertIn("Successfully", await editor.execute(path, "before", "after"))
                self.assertEqual((self.workspace / path).read_text(), "after")

    async def test_absolute_paths_and_directory_boundary(self):
        outside = self.root / "workspace-other" / "example.txt"
        writer = WriteFileTool(workspace=self.workspace)
        editor = EditFileTool(workspace=self.workspace)
        self.assertIn("Successfully", await writer.execute(str(outside), "before"))
        self.assertIn("Successfully", await editor.execute(str(outside), "before", "after"))
        for path in (str(outside), "../workspace-other/example.txt"):
            writer = WriteFileTool(self.workspace, workspace=self.workspace)
            editor = EditFileTool(self.workspace, workspace=self.workspace)
            self.assertTrue((await writer.execute(path, "blocked")).startswith("Error:"))
            self.assertTrue((await editor.execute(path, "after", "blocked")).startswith("Error:"))
        self.assertEqual(outside.read_text(), "after")

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 required")
    async def test_main_and_subagent_write_edit_shell_read(self):
        for restricted in (False, True):
            provider = AsyncMock()
            provider.get_default_model = lambda: "test-model"
            main = AgentLoop(
                MessageBus(), provider, self.workspace,
                session_manager=object(), restrict_to_workspace=restricted,
            )
            for agent in ("main", "subagent"):
                with self.subTest(restricted=restricted, agent=agent):
                    path = f"{agent}-{restricted}.txt"
                    calls = [
                        ("write_file", {"path": path, "content": "before"}),
                        ("edit_file", {"path": path, "old_text": "before", "new_text": "after"}),
                        ("exec_command", {"command": f"Get-Content -LiteralPath '{path}'"}),
                    ]
                    if agent == "main":
                        results = [await main.tools.execute(name, args) for name, args in calls]
                        self.assertEqual(results[-1].strip(), "after")
                    else:
                        provider.chat.side_effect = [
                            LLMResponse(None, [ToolCallRequest(str(i), name, json.dumps(args), args)])
                            for i, (name, args) in enumerate(calls)
                        ] + [LLMResponse("done")]
                        main.subagents._announce_result = AsyncMock()
                        await main.subagents._run_subagent(
                            "test", "test", "test", {"channel": "cli", "chat_id": "test"},
                        )
                        messages = provider.chat.call_args.kwargs["messages"]
                        results = [m["content"] for m in messages if m["role"] == "tool"]
                        self.assertEqual(results[-1].strip(), "after")
                    self.assertEqual((self.workspace / path).read_text(), "after")
