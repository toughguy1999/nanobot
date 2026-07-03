import json

from nanobot.session.history import to_llm_messages, to_memory_transcript, trim_boundary
from nanobot.session.manager import Session, SessionManager


def test_to_llm_messages_groups_adjacent_tool_calls():
    history = [
        {"_type": "message", "id": "msg_1", "role": "user", "content": "hi", "created_at": "2026-01-01T00:00:00"},
        {
            "_type": "tool_call",
            "id": "call_1",
            "type": "function",
            "function": {"name": "read_file", "arguments": "{\"path\":\"a\"}"},
            "content": "",
            "created_at": "2026-01-01T00:00:01",
        },
        {
            "_type": "tool_call",
            "id": "call_2",
            "type": "function",
            "function": {"name": "list_dir", "arguments": "{}"},
            "content": "",
            "created_at": "2026-01-01T00:00:02",
        },
        {
            "_type": "tool_result",
            "role": "tool",
            "tool_call_id": "call_1",
            "name": "read_file",
            "content": "file text",
            "created_at": "2026-01-01T00:00:03",
        },
    ]

    messages = to_llm_messages(history)

    assert messages[0] == {"role": "user", "content": "hi"}
    assert messages[1]["role"] == "assistant"
    assert [call["id"] for call in messages[1]["tool_calls"]] == ["call_1", "call_2"]
    assert messages[2]["role"] == "tool"
    assert messages[2]["tool_call_id"] == "call_1"


def test_to_memory_transcript_includes_messages_and_tool_summary():
    transcript = to_memory_transcript([
        {"_type": "message", "id": "msg_1", "role": "system", "content": "done", "created_at": "2026-01-01T00:00:00"},
        {
            "_type": "tool_call",
            "id": "call_1",
            "type": "function",
            "function": {"name": "read_file", "arguments": "{\"path\":\"README.md\"}"},
            "content": "",
            "created_at": "2026-01-01T00:00:01",
        },
        {
            "_type": "tool_result",
            "role": "tool",
            "tool_call_id": "call_1",
            "name": "read_file",
            "content": "hello",
            "created_at": "2026-01-01T00:00:02",
        },
    ])

    assert "SYSTEM: done" in transcript
    assert "TOOL_CALL read_file" in transcript
    assert "TOOL_RESULT read_file (call_1): hello" in transcript


def test_trim_boundary_removes_orphaned_tool_records():
    history = [
        {"_type": "message", "id": "msg_1", "role": "user", "content": "hi", "created_at": "1"},
        {
            "_type": "tool_call",
            "id": "call_1",
            "type": "function",
            "function": {"name": "x", "arguments": "{}"},
            "content": "",
            "created_at": "2",
        },
        {
            "_type": "tool_result",
            "role": "tool",
            "tool_call_id": "call_1",
            "name": "x",
            "content": "ok",
            "created_at": "3",
        },
        {
            "_type": "tool_call",
            "id": "call_2",
            "type": "function",
            "function": {"name": "y", "arguments": "{}"},
            "content": "",
            "created_at": "4",
        },
    ]

    assert trim_boundary(history, 1) == []
    assert trim_boundary(history, 2)[0]["_type"] == "tool_call"
    assert trim_boundary(history, 2)[0]["id"] == "call_1"


def test_session_manager_append_round_trips_canonical_history(tmp_path):
    manager = SessionManager()
    manager.sessions_dir = tmp_path
    session = Session(key="cli:test")
    manager.save(session)

    user = session.add_user_message("hello")
    manager.append(session, user)
    call = session.add_tool_call(id="call_1", name="read_file", arguments={"path": "README.md"})
    manager.append(session, call)
    result = session.add_tool_result(tool_call_id="call_1", name="read_file", content="contents")
    manager.append(session, result)

    loaded = manager.get("cli:test", refresh=True)

    assert loaded is not None
    assert loaded.messages == session.messages
    lines = (tmp_path / "cli_test.jsonl").read_text().splitlines()
    assert json.loads(lines[0])["_type"] == "metadata"
    assert [json.loads(line)["_type"] for line in lines[1:]] == ["message", "tool_call", "tool_result"]
