from pathlib import Path
from typing import Any

from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.base import Tool
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest
from nanobot.session.manager import SessionManager


def make_manager(tmp_path: Path) -> SessionManager:
    manager = SessionManager()
    manager.sessions_dir = tmp_path
    return manager


class SequenceProvider(LLMProvider):
    def __init__(self, responses: list[LLMResponse] | None = None, exc: Exception | None = None):
        super().__init__()
        self.responses = responses or []
        self.exc = exc
        self.calls: list[list[dict[str, Any]]] = []

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        self.calls.append(messages)
        if self.exc:
            raise self.exc
        return self.responses.pop(0)

    def get_default_model(self) -> str:
        return "fake-model"


class EchoTool(Tool):
    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "Echo input"

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {"text": {"type": "string"}}}

    async def execute(self, *args: Any, **kwargs: Any) -> str:
        return f"echo:{kwargs.get('text', '')}"


async def test_agent_loop_persists_plain_user_and_assistant(tmp_path: Path):
    manager = make_manager(tmp_path / "sessions")
    loop = AgentLoop(MessageBus(), SequenceProvider([LLMResponse(content="pong")]), tmp_path, session_manager=manager)

    response = await loop._process_message(InboundMessage("cli", "u", "direct", "ping"))

    assert response is not None
    assert response.content == "pong"
    session = manager.get("cli:direct", refresh=True)
    assert session is not None
    assert [record["_type"] for record in session.messages] == ["message", "message"]
    assert [record["role"] for record in session.messages] == ["user", "assistant"]


async def test_agent_loop_persists_multiple_tool_calls_as_flat_stream(tmp_path: Path):
    provider = SequenceProvider([
        LLMResponse(
            content="",
            tool_calls=[
                ToolCallRequest(id="call_1", name="echo", arguments={"text": "a"}),
                ToolCallRequest(id="call_2", name="echo", arguments={"text": "b"}),
            ],
        ),
        LLMResponse(content="done"),
    ])
    manager = make_manager(tmp_path / "sessions")
    loop = AgentLoop(MessageBus(), provider, tmp_path, session_manager=manager)
    loop.tools.register(EchoTool())

    await loop._process_message(InboundMessage("cli", "u", "direct", "use tools"))

    session = manager.get("cli:direct", refresh=True)
    assert session is not None
    assert [record["_type"] for record in session.messages] == [
        "message",
        "tool_call",
        "tool_call",
        "tool_result",
        "tool_result",
        "message",
    ]
    assert "Reflect on the results" not in "\n".join(str(record) for record in session.messages)
    assert all("reasoning_content" not in record for record in session.messages)


async def test_agent_loop_provider_exception_saves_error_final(tmp_path: Path):
    manager = make_manager(tmp_path / "sessions")
    loop = AgentLoop(MessageBus(), SequenceProvider(exc=RuntimeError("boom")), tmp_path, session_manager=manager)

    response = await loop._process_message(InboundMessage("cli", "u", "direct", "hello"))

    assert response is not None
    assert "boom" in response.content
    session = manager.get("cli:direct", refresh=True)
    assert session is not None
    assert [record["role"] for record in session.messages] == ["user", "assistant"]
    assert "boom" in session.messages[-1]["content"]


async def test_system_announce_persists_system_and_assistant(tmp_path: Path):
    manager = make_manager(tmp_path / "sessions")
    loop = AgentLoop(MessageBus(), SequenceProvider([LLMResponse(content="reported")]), tmp_path, session_manager=manager)

    response = await loop._process_message(InboundMessage("system", "worker", "cli:direct", "finished"))

    assert response is not None
    assert response.content == "reported"
    session = manager.get("cli:direct", refresh=True)
    assert session is not None
    assert [record["role"] for record in session.messages] == ["system", "assistant"]
