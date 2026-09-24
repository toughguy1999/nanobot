"""Persistent history-compression state and effective projection behavior."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nanobot.harness.context import ContextBuilder
from nanobot.harness.session.compression import (
    TOOL_RESULT_CLEARED_CONTENT,
    CompressionState,
    compression_state_to_dict,
)
from nanobot.harness.session.manager import SessionManager
from nanobot.webservice.attachments import WebAttachmentStore
from nanobot.webservice.service import WebService


def tool_call(call_id: str, name: str = "read") -> dict[str, object]:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": "{}"},
    }


class CompressionPersistenceTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        with patch("nanobot.harness.session.manager.PROJECT_ROOT", self.root):
            self.sessions = SessionManager()
        self.session = self.sessions.get_or_create("web:one")

    def reload(self):
        with patch("nanobot.harness.session.manager.PROJECT_ROOT", self.root):
            return SessionManager().get("web:one")

    def add_records(self):
        covered_image = self.session.add_user_message([
            {
                "type": "image_url",
                "image_url": {
                    "blob": {"store": "session", "path": "old.png", "mimeType": "image/png"}
                },
            },
            {"type": "text", "text": "old image"},
        ])
        old_assistant = self.session.add_assistant_message(
            "old reply",
            reasoning_content="old reasoning",
            tool_calls=[tool_call("old-call")],
        )
        old_tool = self.session.add_tool_result(
            tool_call_id="old-call",
            name="read",
            content="old tool body",
            agent_status="old tool status",
        )
        current_user = self.session.add_user_message([
            {
                "type": "image_url",
                "image_url": {
                    "blob": {
                        "store": "session",
                        "path": "current.png",
                        "mimeType": "image/png",
                    }
                },
            },
            {"type": "text", "text": "current image"},
        ], agent_status="current user status")
        current_assistant = self.session.add_assistant_message(
            "working",
            reasoning_content="remove this reasoning",
            tool_calls=[tool_call("current-call")],
        )
        current_tool = self.session.add_tool_result(
            tool_call_id="current-call",
            name="read",
            content="remove this tool body",
            agent_status="remove this tool status",
        )
        system = self.session.add_system_message("notice", agent_status="system status")
        return {
            "covered_image": covered_image,
            "old_assistant": old_assistant,
            "old_tool": old_tool,
            "current_user": current_user,
            "current_assistant": current_assistant,
            "current_tool": current_tool,
            "system": system,
        }

    def test_projection_reload_summary_position_and_web_history(self):
        records = self.add_records()
        original = copy.deepcopy(self.session.messages)
        state = CompressionState(
            cleared_tool_through_id=records["current_tool"]["id"],
            cleared_reasoning_through_id=records["current_assistant"]["id"],
            summary="# Prior work\nold details summarized",
            summary_through_id=records["old_tool"]["id"],
        )
        self.sessions.commit_compression(self.session, state)

        with patch(
            "nanobot.harness.session.history.SessionBlobStore.read_data_url",
            return_value="data:image/png;base64,current",
        ) as read_blob:
            projected = self.session.get_llm_history()
        read_blob.assert_called_once()
        self.assertEqual(read_blob.call_args.args[0]["path"], "current.png")
        self.assertEqual(len(projected), 4)
        self.assertNotIn("reasoning_content", projected[1])
        self.assertEqual(projected[2]["content"], TOOL_RESULT_CLEARED_CONTENT)
        self.assertNotIn("remove this tool status", projected[2]["content"])
        self.assertEqual(projected[3]["content"], "[System: notice]\n\nsystem status")
        self.assertEqual(self.session.messages, original)

        reloaded = self.reload()
        self.assertIsNotNone(reloaded)
        self.assertEqual(reloaded.compression, state)
        self.assertEqual(reloaded.messages, original)
        with patch(
            "nanobot.harness.session.history.SessionBlobStore.read_data_url",
            return_value="data:image/png;base64,current",
        ):
            self.assertEqual(reloaded.get_llm_history(), projected)

        context = ContextBuilder(self.root)
        with patch.object(context, "build_system_prompt", return_value="SYSTEM"):
            messages = context.build_messages_from_llm_history(
                projected,
                history_summary=reloaded.compression.summary,
            )
        self.assertEqual(messages[0], {"role": "system", "content": "SYSTEM"})
        self.assertEqual(messages[1]["role"], "user")
        self.assertTrue(messages[1]["content"].startswith("[历史上下文摘要]"))
        self.assertEqual(messages[2:], projected)

        service = WebService(self.sessions, WebAttachmentStore(self.root / "attachments"))
        dto = service.get_session_messages("one")
        self.assertEqual([item["content"] for item in dto["messages"]], [
            "old image",
            "old reply",
            "current image",
            "working",
        ])
        self.assertNotIn("历史上下文摘要", json.dumps(dto, ensure_ascii=False))
        self.assertEqual(self.session.messages, original)

    def test_missing_compression_loads_and_invalid_state_fails_closed(self):
        user = self.session.add_user_message("hello")
        self.sessions.save(self.session)
        self.assertEqual(self.reload().compression, CompressionState())

        path = self.sessions._get_session_path(self.session.key)
        lines = path.read_text(encoding="utf-8").splitlines()
        metadata = json.loads(lines[0])
        invalid_values = [
            {"summary": "only one side"},
            {"summary": "text", "summary_through_id": "missing"},
            {"cleared_tool_through_id": user["id"]},
            {"cleared_reasoning_through_id": 123},
        ]
        for value in invalid_values:
            with self.subTest(value=value):
                changed = copy.deepcopy(metadata)
                changed["metadata"]["compression"] = value
                path.write_text(
                    "\n".join([json.dumps(changed), *lines[1:]]) + "\n",
                    encoding="utf-8",
                )
                with patch("nanobot.harness.session.manager.PROJECT_ROOT", self.root):
                    with self.assertRaises(ValueError):
                        SessionManager().get("web:one")

    def test_monotonic_commit_clear_delete_and_session_isolation(self):
        records = self.add_records()
        first = CompressionState(
            cleared_tool_through_id=records["current_tool"]["id"],
            cleared_reasoning_through_id=records["current_assistant"]["id"],
        )
        self.sessions.commit_compression(self.session, first)
        with self.assertRaises(ValueError):
            self.sessions.commit_compression(self.session, CompressionState())

        covered = CompressionState(
            summary="all summarized",
            summary_through_id=records["system"]["id"],
        )
        self.sessions.commit_compression(self.session, covered)
        self.assertEqual(self.session.get_effective_records(), [])

        other = self.sessions.get_or_create("web:two")
        other.add_user_message("other")
        self.sessions.save(other)
        self.assertEqual(other.compression, CompressionState())

        self.session.clear()
        self.sessions.save(self.session)
        self.assertEqual(self.reload().compression, CompressionState())
        raw_metadata = json.loads(
            self.sessions._get_session_path(self.session.key).read_text(encoding="utf-8").splitlines()[0]
        )["metadata"]
        self.assertNotIn("compression", raw_metadata)
        self.assertTrue(self.sessions.delete("web:one"))
        self.assertFalse(self.sessions._get_session_path("web:one").exists())
        self.assertFalse(list(self.sessions.sessions_dir.glob("*summary*")))

    def test_atomic_failure_restores_memory_and_metadata_refreshes_from_disk(self):
        records = self.add_records()
        self.session.metadata = {"pinned": True, "todos": ["todo"]}
        self.sessions.save(self.session)
        old_bytes = self.sessions._get_session_path(self.session.key).read_bytes()
        candidate = CompressionState(
            cleared_tool_through_id=records["current_tool"]["id"],
        )
        with patch("nanobot.harness.session.manager.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.sessions.commit_compression(self.session, candidate)
        self.assertEqual(self.session.compression, CompressionState())
        self.assertEqual(self.sessions._get_session_path(self.session.key).read_bytes(), old_bytes)
        self.assertFalse(list(self.sessions.sessions_dir.glob("*.tmp")))

        self.sessions.commit_compression(self.session, candidate)
        refreshed = self.sessions.get("web:one", refresh=True)
        self.assertIsNot(refreshed, self.session)
        self.assertEqual(refreshed.compression, candidate)
        self.assertEqual(self.sessions.ensure_session_title("web:one"), "old image")
        self.sessions.update_metadata("web:one", {"pinned": False})
        current = self.sessions.get("web:one")
        self.assertEqual(current.compression, candidate)
        self.assertEqual(current.metadata["todos"], ["todo"])
        self.assertEqual(current.metadata["sessionTitle"], "old image")
        self.assertFalse(current.metadata["pinned"])

    def test_serialized_boundaries_are_compact(self):
        self.session.add_user_message("start")
        self.session.add_assistant_message(
            "one", tool_calls=[tool_call("one")],
        )
        self.session.add_tool_result(tool_call_id="one", name="read", content="1")
        assistant_two = self.session.add_assistant_message(
            "two", reasoning_content="r", tool_calls=[tool_call("two")],
        )
        tool_two = self.session.add_tool_result(tool_call_id="two", name="read", content="2")
        state = CompressionState(
            cleared_tool_through_id=tool_two["id"],
            cleared_reasoning_through_id=assistant_two["id"],
        )
        payload = compression_state_to_dict(state, self.session.messages)
        self.assertEqual(payload["cleared_tool_through_id"], tool_two["id"])
        self.assertEqual(payload["cleared_reasoning_through_id"], assistant_two["id"])


if __name__ == "__main__":
    unittest.main()
