from pathlib import Path

from nanobot.session.manager import Session, SessionManager


def make_manager(tmp_path: Path) -> SessionManager:
    manager = SessionManager()
    tmp_path.mkdir(parents=True, exist_ok=True)
    manager.sessions_dir = tmp_path
    return manager


def test_session_manager_lists_web_metadata_without_loading_messages(tmp_path: Path):
    manager = make_manager(tmp_path)

    web_session = Session(key="web:session_one")
    web_session.metadata["sessionTitle"] = "hello from web"
    web_session.add_message("user", "hello from web")
    web_session.add_message("assistant", "hi")
    manager.save(web_session)

    cli_session = Session(key="cli:direct")
    cli_session.add_message("user", "ignore me")
    manager.save(cli_session)

    sessions = manager.list_sessions(channel="web")

    assert len(sessions) == 1
    assert sessions[0]["key"] == "web:session_one"
    assert sessions[0]["metadata"]["sessionTitle"] == "hello from web"
    assert sessions[0]["updated_at"] == web_session.updated_at.isoformat()

    loaded = manager.get("web:session_one", refresh=True)
    assert loaded is not None
    assert loaded.updated_at == web_session.updated_at


def test_session_manager_lists_pinned_sessions_first(tmp_path: Path):
    manager = make_manager(tmp_path)

    regular_session = Session(key="web:regular")
    regular_session.metadata["sessionTitle"] = "regular"
    regular_session.add_message("user", "regular")
    manager.save(regular_session)

    pinned_session = Session(key="web:pinned")
    pinned_session.metadata["sessionTitle"] = "pinned"
    pinned_session.add_message("user", "pinned")
    pinned_session.metadata["pinned"] = True
    manager.save(pinned_session)

    sessions = manager.list_sessions(channel="web")

    assert [session["key"] for session in sessions] == ["web:pinned", "web:regular"]
