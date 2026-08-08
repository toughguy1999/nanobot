"""Lifecycle owner for local stdio MCP servers."""

import asyncio
import re
import sys
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, Callable, Sequence

from loguru import logger
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from nanobot.config.schema import MCPServerConfig
from nanobot.mcp.results import normalize_call_tool_result
from nanobot.mcp.types import (
    DiscoveredMCPTool,
    MCPServerState,
    MCPServerStatus,
    NormalizedMCPResult,
)
from nanobot.utils.helpers import PROJECT_ROOT

_SERVER_NAME = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_TOOL_NAME = re.compile(r"^[A-Za-z0-9_-]+$")
_MAX_FUNCTION_NAME = 64

ToolsReadyCallback = Callable[[list[DiscoveredMCPTool]], None]


class MCPManager:
    """Start configured servers and expose their fully discovered tool sets."""

    def __init__(
        self,
        servers: Sequence[MCPServerConfig],
        *,
        project_root: Path | None = None,
        stdio_factory: Callable[..., Any] = stdio_client,
        session_factory: Callable[..., Any] = ClientSession,
        close_timeout: float = 5.0,
    ) -> None:
        self._configs = list(servers)
        self._project_root = (project_root or PROJECT_ROOT).resolve()
        self._stdio_factory = stdio_factory
        self._session_factory = session_factory
        self._close_timeout = close_timeout
        self.states: list[MCPServerState] = []
        self._calls: set[asyncio.Task[Any]] = set()
        self._server_tasks: set[asyncio.Task[None]] = set()
        self._startup_task: asyncio.Task[list[DiscoveredMCPTool]] | None = None
        self._shutdown_event = asyncio.Event()
        self._closing = False
        self._closed = False

    @property
    def tools(self) -> list[DiscoveredMCPTool]:
        """Return ready tools in configuration and discovery order."""

        return [
            tool
            for state in self.states
            if state.status is MCPServerStatus.READY
            for tool in state.tools
        ]

    def start_background(
        self,
        on_tools_ready: ToolsReadyCallback | None = None,
    ) -> asyncio.Task[list[DiscoveredMCPTool]]:
        """Start initialization without blocking the caller's runtime startup."""

        if self._startup_task is None:
            self._startup_task = asyncio.create_task(
                self.start(on_tools_ready),
                name="mcp-startup",
            )
        return self._startup_task

    async def start(
        self,
        on_tools_ready: ToolsReadyCallback | None = None,
    ) -> list[DiscoveredMCPTool]:
        """Initialize enabled servers concurrently and publish each ready tool set."""

        if self._closing or self._closed:
            return []
        if self.states:
            return self.tools

        seen: set[str] = set()
        initialized: list[asyncio.Future[None]] = []
        for config in self._configs:
            state = MCPServerState(config=config)
            self.states.append(state)
            if not config.enabled:
                state.status = MCPServerStatus.CLOSED
                logger.debug(f"MCP server '{config.name}' is disabled")
                continue

            if config.name in seen:
                self._unavailable(state, "validation", "duplicate server name")
                continue
            seen.add(config.name)

            try:
                script = self._validate(config)
            except ValueError as exc:
                self._unavailable(state, "validation", str(exc))
                continue

            ready = asyncio.get_running_loop().create_future()
            initialized.append(ready)
            task = asyncio.create_task(
                self._run_server(state, script, ready, on_tools_ready),
                name=f"mcp-server-{config.name}",
            )
            self._server_tasks.add(task)
            task.add_done_callback(self._server_tasks.discard)

        if initialized:
            await asyncio.gather(*initialized)

        return self.tools

    async def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> NormalizedMCPResult:
        """Route one call by its explicit server and original tool names."""

        if self._closing or self._closed:
            return self._error("MCP manager is closing and cannot accept new calls")

        state = next(
            (
                item
                for item in self.states
                if item.config.name == server_name and item.status is MCPServerStatus.READY
            ),
            None,
        )
        if state is None or state.session is None:
            return self._error(f"MCP server '{server_name}' is unavailable")
        if not any(tool.name == tool_name for tool in state.tools):
            return self._error(f"MCP tool '{tool_name}' is unavailable on server '{server_name}'")

        task = asyncio.current_task()
        if task is not None:
            self._calls.add(task)
        try:
            sdk_result = await state.session.call_tool(tool_name, arguments)
            return normalize_call_tool_result(sdk_result)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(f"MCP server '{server_name}' tool '{tool_name}' call failed: {exc}")
            if self._is_connection_error(exc):
                self._unavailable(state, "call", f"connection lost: {exc}")
                return self._error(f"MCP server '{server_name}' is unavailable: connection lost")
            return self._error(f"MCP tool '{tool_name}' call failed: {exc}")
        finally:
            if task is not None:
                self._calls.discard(task)

    async def close(self) -> None:
        """Reject new calls, drain active calls briefly, and close every server."""

        if self._closed:
            return
        self._closing = True
        self._shutdown_event.set()
        current = asyncio.current_task()
        calls = {task for task in self._calls if task is not current and not task.done()}
        if calls:
            _done, pending = await asyncio.wait(calls, timeout=self._close_timeout)
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

        tasks = {task for task in self._server_tasks if task is not current and not task.done()}
        if tasks:
            _done, pending = await asyncio.wait(tasks, timeout=self._close_timeout)
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

        startup_task = self._startup_task
        if startup_task is not None and startup_task is not current and not startup_task.done():
            await asyncio.gather(startup_task, return_exceptions=True)

        for state in self.states:
            state.session = None
            state.cleanup = None
            state.status = MCPServerStatus.CLOSED
        self._closed = True

    @staticmethod
    def _error(message: str) -> NormalizedMCPResult:
        return NormalizedMCPResult(is_error=True, error=message)

    @staticmethod
    def _is_connection_error(exc: Exception) -> bool:
        if isinstance(exc, (ConnectionError, BrokenPipeError, EOFError)):
            return True
        return type(exc).__name__ in {"BrokenResourceError", "ClosedResourceError", "EndOfStream"}

    def _validate(self, config: MCPServerConfig) -> Path:
        if not _SERVER_NAME.fullmatch(config.name):
            raise ValueError("name must match ^[a-z][a-z0-9_]*$ and be at most 32 characters")

        configured_path = Path(config.path)
        if configured_path.is_absolute():
            raise ValueError("path must be relative to PROJECT_ROOT")
        if configured_path.suffix.lower() != ".py":
            raise ValueError("path must reference a .py file")

        script = (self._project_root / configured_path).resolve()
        try:
            script.relative_to(self._project_root)
        except ValueError as exc:
            raise ValueError("resolved path escapes PROJECT_ROOT") from exc
        if not script.is_file():
            raise ValueError("path must reference an existing regular file")
        return script

    async def _run_server(
        self,
        state: MCPServerState,
        script: Path,
        initialized: asyncio.Future[None],
        on_tools_ready: ToolsReadyCallback | None,
    ) -> None:
        """Own one server's async contexts for its complete lifetime."""

        stack = AsyncExitStack()
        state.cleanup = stack
        try:
            parameters = StdioServerParameters(
                command=sys.executable,
                args=[str(script)],
                cwd=self._project_root,
            )
            read_stream, write_stream = await stack.enter_async_context(
                self._stdio_factory(parameters)
            )
            session = await stack.enter_async_context(
                self._session_factory(read_stream, write_stream)
            )
            state.session = session
            await session.initialize()
            state.tools = await self._discover_tools(state.config.name, session)
            if self._closing:
                return
            state.status = MCPServerStatus.READY
            logger.info(f"MCP server '{state.config.name}' ready with {len(state.tools)} tools")
            if on_tools_ready is not None:
                on_tools_ready(list(state.tools))
            if not initialized.done():
                initialized.set_result(None)
            await self._shutdown_event.wait()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            state.tools.clear()
            state.session = None
            self._unavailable(state, "startup/discovery", str(exc))
        finally:
            if not initialized.done():
                initialized.set_result(None)
            if state.status is MCPServerStatus.READY:
                state.status = MCPServerStatus.CLOSING
            state.session = None
            try:
                await stack.aclose()
            except Exception as cleanup_exc:
                state.last_error = f"shutdown: {cleanup_exc}"
                logger.warning(f"MCP server '{state.config.name}' cleanup failed: {cleanup_exc}")
            state.cleanup = None
            if self._closing or state.status is MCPServerStatus.CLOSING:
                state.status = MCPServerStatus.CLOSED

    async def _discover_tools(self, server_name: str, session: Any) -> list[DiscoveredMCPTool]:
        discovered: list[DiscoveredMCPTool] = []
        cursor: str | None = None
        while True:
            page = (
                await session.list_tools(cursor=cursor)
                if cursor is not None
                else await session.list_tools()
            )
            for tool in page.tools:
                final_name = f"mcp_{server_name}_{tool.name}"
                if not _TOOL_NAME.fullmatch(tool.name) or len(final_name) > _MAX_FUNCTION_NAME:
                    logger.warning(
                        f"MCP server '{server_name}' discovery skipped incompatible tool '{tool.name}'"
                    )
                    continue
                discovered.append(
                    DiscoveredMCPTool(
                        server_name=server_name,
                        name=tool.name,
                        description=tool.description or "",
                        input_schema=tool.input_schema,
                    )
                )
            cursor = page.next_cursor
            if not cursor:
                return discovered

    @staticmethod
    def _unavailable(state: MCPServerState, stage: str, reason: str) -> None:
        state.status = MCPServerStatus.UNAVAILABLE
        state.last_error = f"{stage}: {reason}"
        logger.warning(f"MCP server '{state.config.name}' {stage} failed: {reason}")
