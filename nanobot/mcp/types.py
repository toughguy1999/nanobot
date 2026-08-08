"""Protocol-independent runtime types for MCP servers and tool calls."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from nanobot.config.schema import MCPServerConfig


class MCPServerStatus(StrEnum):
    """Lifecycle status tracked independently for every configured server."""

    STARTING = "starting"
    READY = "ready"
    UNAVAILABLE = "unavailable"
    CLOSING = "closing"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class DiscoveredMCPTool:
    """A tool descriptor returned by one MCP server."""

    server_name: str
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(slots=True)
class MCPServerState:
    """Mutable lifecycle state belonging to exactly one MCP server."""

    config: MCPServerConfig
    status: MCPServerStatus = MCPServerStatus.STARTING
    session: Any | None = None
    tools: list[DiscoveredMCPTool] = field(default_factory=list)
    last_error: str | None = None
    cleanup: Any | None = None


@dataclass(frozen=True, slots=True)
class NormalizedMCPResult:
    """MCP call result stripped of SDK and binary/resource payload details."""

    is_error: bool = False
    text: list[str] = field(default_factory=list)
    structured_content: Any = None
    unsupported_content: list[str] = field(default_factory=list)
    error: str | None = None


class MCPError(Exception):
    """Base error raised at the MCP integration boundary."""


class MCPConfigurationError(MCPError):
    """A server configuration is not valid for local stdio startup."""


class MCPServerUnavailableError(MCPError):
    """The requested server cannot currently accept calls."""


class MCPCallError(MCPError):
    """An MCP tool call failed before a protocol result was returned."""
