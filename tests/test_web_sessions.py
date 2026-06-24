from pathlib import Path

from fastapi.testclient import TestClient

from nanobot.bus.queue import MessageBus
from nanobot.channels.web import WebChannel
from nanobot.config.schema import WebConfig
from nanobot.session.manager import Session, SessionManager


def make_manager(tmp_path: Path) -> SessionManager:
    manager = SessionManager()
    manager.sessions_dir = tmp_path
    return manager


def test_session_manager_lists_web_metadata_without_loading_messages(tmp_path: Path):
    manager = make_manager(tmp_path)

    web_session = Session(key="web:session_one")
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
    regular_session.add_message("user", "regular")
    manager.save(regular_session)

    pinned_session = Session(key="web:pinned")
    pinned_session.add_message("user", "pinned")
    pinned_session.metadata["pinned"] = True
    manager.save(pinned_session)

    sessions = manager.list_sessions(channel="web")

    assert [session["key"] for session in sessions] == ["web:pinned", "web:regular"]


def test_web_channel_session_routes(tmp_path: Path):
    channel = WebChannel(WebConfig(), MessageBus())
    channel._sessions.sessions_dir = tmp_path

    client = TestClient(channel.app)

    created = client.post("/sessions", json={"sessionId": "session-test"})
    assert created.status_code == 200
    assert created.json()["session"]["id"] == "session-test"

    session = channel._sessions.get_or_create("web:session-test")
    session.add_message("user", "first message")
    session.add_message("assistant", "answer", tools_used=[])
    channel._sessions.save(session)

    listed = client.get("/sessions")
    assert listed.status_code == 200
    assert listed.json()["sessions"] == [
        {
            "id": "session-test",
            "key": "web:session-test",
            "sessionTitle": "first message",
            "createdAt": session.created_at.isoformat(),
            "updatedAt": session.updated_at.isoformat(),
            "pinned": False,
        }
    ]

    detail = client.get("/sessions/session-test/messages")
    assert detail.status_code == 200
    body = detail.json()
    assert body["session"]["sessionTitle"] == "first message"
    assert body["messages"][0]["role"] == "user"
    assert body["messages"][0]["createdAt"]
    assert body["messages"][1]["metadata"] == {"toolsUsed": []}


def test_web_channel_session_list_backfills_missing_title(tmp_path: Path):
    channel = WebChannel(WebConfig(), MessageBus())
    channel._sessions.sessions_dir = tmp_path

    session = Session(key="web:legacy-session")
    session.add_message("user", "legacy title")
    session.metadata.pop("sessionTitle")
    channel._sessions.save(session)

    client = TestClient(channel.app)
    listed = client.get("/sessions")

    assert listed.status_code == 200
    assert listed.json()["sessions"][0]["sessionTitle"] == "legacy title"

    reloaded = channel._sessions.get("web:legacy-session", refresh=True)
    assert reloaded is not None
    assert reloaded.metadata["sessionTitle"] == "legacy title"


def test_web_channel_pin_session(tmp_path: Path):
    channel = WebChannel(WebConfig(), MessageBus())
    channel._sessions.sessions_dir = tmp_path

    session = Session(key="web:pin-me")
    channel._sessions.save(session)

    client = TestClient(channel.app)
    response = client.post("/sessions/pin-me/pin")

    assert response.status_code == 200
    assert response.json()["session"]["pinned"] is True

    reloaded = channel._sessions.get("web:pin-me", refresh=True)
    assert reloaded is not None
    assert reloaded.metadata["pinned"] is True


def test_web_channel_unpin_session(tmp_path: Path):
    channel = WebChannel(WebConfig(), MessageBus())
    channel._sessions.sessions_dir = tmp_path

    session = Session(key="web:pin-me", metadata={"pinned": True})
    channel._sessions.save(session)

    client = TestClient(channel.app)
    response = client.post("/sessions/pin-me/unpin")

    assert response.status_code == 200
    assert response.json()["session"]["pinned"] is False

    reloaded = channel._sessions.get("web:pin-me", refresh=True)
    assert reloaded is not None
    assert reloaded.metadata["pinned"] is False


def test_web_channel_pin_missing_session_returns_404(tmp_path: Path):
    channel = WebChannel(WebConfig(), MessageBus())
    channel._sessions.sessions_dir = tmp_path

    client = TestClient(channel.app)
    response = client.post("/sessions/missing/pin")

    assert response.status_code == 404


def test_web_channel_unpin_missing_session_returns_404(tmp_path: Path):
    channel = WebChannel(WebConfig(), MessageBus())
    channel._sessions.sessions_dir = tmp_path

    client = TestClient(channel.app)
    response = client.post("/sessions/missing/unpin")

    assert response.status_code == 404


def test_web_channel_delete_session(tmp_path: Path):
    channel = WebChannel(WebConfig(), MessageBus())
    channel._sessions.sessions_dir = tmp_path

    session = Session(key="web:delete-me")
    channel._sessions.save(session)
    path = channel._sessions._get_session_path("web:delete-me")
    assert path.exists()

    client = TestClient(channel.app)
    response = client.post("/sessions/delete-me/delete")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert not path.exists()
    assert channel._sessions.get("web:delete-me", refresh=True) is None


def test_web_channel_delete_missing_session_returns_404(tmp_path: Path):
    channel = WebChannel(WebConfig(), MessageBus())
    channel._sessions.sessions_dir = tmp_path

    client = TestClient(channel.app)
    response = client.post("/sessions/missing/delete")

    assert response.status_code == 404


def test_web_channel_session_management_rejects_invalid_session_id(tmp_path: Path):
    channel = WebChannel(WebConfig(), MessageBus())
    channel._sessions.sessions_dir = tmp_path

    client = TestClient(channel.app)

    assert client.post("/sessions/bad:id/pin").status_code == 400
    assert client.post("/sessions/bad:id/unpin").status_code == 400
    assert client.post("/sessions/bad:id/delete").status_code == 400
