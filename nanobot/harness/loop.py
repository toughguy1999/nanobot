"""Agent loop: the core processing engine."""

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.harness.attachments import stabilize_user_message
from nanobot.harness.compress import DEFAULT_MAX_TOOL_RESULT_TOKENS, compress_tool_result
from nanobot.harness.compress.service import HistoryCompressionService
from nanobot.harness.context import ContextBuilder
from nanobot.harness.status import AgentStatus
from nanobot.harness.subagent import SubagentManager
from nanobot.harness.tools.cron import CronTool
from nanobot.harness.tools.filesystem import EditFileTool, WriteFileTool
from nanobot.harness.tools.message import MessageTool
from nanobot.harness.tools.rag import AbsurdNovelKnowledgeSearchTool
from nanobot.harness.tools.registry import ToolRegistry
from nanobot.harness.tools.shell import ExecTool
from nanobot.harness.tools.skills import LoadSkillTool
from nanobot.harness.tools.spawn import SpawnTool
from nanobot.harness.tools.todo import TodoEditTool
from nanobot.harness.tools.web import WebFetchTool, WebSearchTool
from nanobot.bus.events import InboundAttachment, InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.utils._debug import publish_context
from nanobot.providers.base import LLMProvider
from nanobot.harness.session.manager import Session, SessionManager

if TYPE_CHECKING:
    from nanobot.config.schema import ExecToolConfig, HistoryCompressionConfig
    from nanobot.cron.service import CronService


class AgentLoop:
    """
    The agent loop is the core processing engine.

    It:
    1. Receives messages from the bus
    2. Builds context with history, memory, skills
    3. Calls the LLM
    4. Executes tool calls
    5. Sends responses back
    """

    def __init__(
        self,
        bus: MessageBus,
        provider: LLMProvider,
        workspace: Path,
        model: str | None = None,
        max_iterations: int = 100,
        max_tool_result_tokens: int = DEFAULT_MAX_TOOL_RESULT_TOKENS,
        brave_api_key: str | None = None,
        exec_config: "ExecToolConfig | None" = None,
        cron_service: "CronService | None" = None,
        restrict_to_workspace: bool = False,
        session_manager: SessionManager | None = None,
        max_tokens: int = 20000,
        history_compression: "HistoryCompressionConfig | None" = None,
        summary_provider: LLMProvider | None = None,
    ):
        from nanobot.config.schema import ExecToolConfig, HistoryCompressionConfig
        self.bus = bus
        self.provider = provider
        self.workspace = workspace
        self.model = model or provider.get_default_model()
        self.max_iterations = max_iterations
        self.max_tokens = max_tokens
        self.max_tool_result_tokens = max_tool_result_tokens
        self.brave_api_key = brave_api_key
        self.exec_config = exec_config or ExecToolConfig()
        self.cron_service = cron_service
        self.restrict_to_workspace = restrict_to_workspace

        self.context = ContextBuilder(
            workspace, restrict_to_workspace=restrict_to_workspace,
        )
        self.sessions = session_manager or SessionManager()
        compression_config = history_compression or HistoryCompressionConfig()
        self.history_compression = HistoryCompressionService(
            compression_config,
            self.sessions,
        )
        self.summary_model = compression_config.summary_model or self.model
        self.summary_provider = (
            provider if compression_config.summary_model is None else summary_provider
        )
        self.tools = ToolRegistry()
        self.subagents = SubagentManager(
            provider=provider,
            workspace=workspace,
            bus=bus,
            max_tool_result_tokens=max_tool_result_tokens,
            model=self.model,
            max_tokens=self.max_tokens,
            brave_api_key=brave_api_key,
            exec_config=self.exec_config,
            restrict_to_workspace=restrict_to_workspace,
        )

        self._running = False
        self._register_default_tools()

    def _register_default_tools(self) -> None:
        """Register the default set of tools."""
        # File tools (restrict to workspace if configured)
        allowed_dir = self.workspace if self.restrict_to_workspace else None
        self.tools.register(LoadSkillTool(self.context.skills))
        self.tools.register(WriteFileTool(allowed_dir=allowed_dir, workspace=self.workspace))
        self.tools.register(EditFileTool(allowed_dir=allowed_dir, workspace=self.workspace))

        # Shell tool
        self.tools.register(ExecTool(
            working_dir=str(self.workspace),
            timeout=self.exec_config.timeout,
            restrict_to_workspace=self.restrict_to_workspace,
        ))

        # Web tools
        self.tools.register(WebSearchTool(api_key=self.brave_api_key))
        self.tools.register(WebFetchTool())

        # Local RAG tools
        self.tools.register(AbsurdNovelKnowledgeSearchTool())

        # Message tool
        message_tool = MessageTool(send_callback=self.bus.publish_outbound)
        self.tools.register(message_tool)

        # Spawn tool (for subagents)
        spawn_tool = SpawnTool(manager=self.subagents)
        self.tools.register(spawn_tool)

        # Cron tool (for scheduling)
        if self.cron_service:
            self.tools.register(CronTool(self.cron_service))

    async def run(self) -> None:
        """Run the agent loop, processing messages from the bus."""
        self._running = True
        logger.info("Agent loop started")

        while self._running:
            try:
                # Wait for next message
                msg = await asyncio.wait_for(
                    self.bus.consume_inbound(),
                    timeout=1.0
                )

                # Process it
                try:
                    response = await self._process_message(msg)
                    if response:
                        await self.bus.publish_outbound(response)
                except Exception as e:
                    logger.error(f"Error processing message: {e}")
                    # Send error response
                    await self.bus.publish_outbound(OutboundMessage(
                        channel=msg.channel,
                        chat_id=msg.chat_id,
                        content=f"Sorry, I encountered an error: {str(e)}"
                    ))
            except asyncio.TimeoutError:
                continue

    def stop(self) -> None:
        """Stop the agent loop."""
        self._running = False
        logger.info("Agent loop stopping")

    async def _process_message(
        self,
        msg: InboundMessage,
        session_key: str | None = None,
        *,
        emit_events: bool = True,
    ) -> OutboundMessage | None:
        """
        Process a single inbound message.

        Args:
            msg: The inbound message to process.
            session_key: Override session key (used by process_direct).

        Returns:
            The response message, or None if no response needed.
        """
        # Handle system messages (subagent announces)
        # The chat_id contains the original "channel:chat_id" to route back to
        if msg.channel == "system":
            return await self._process_system_message(msg, emit_events=emit_events)

        status = AgentStatus()
        preview = msg.content[:80] + "..." if len(msg.content) > 80 else msg.content
        logger.info(f"Processing message from {msg.channel}:{msg.sender_id}: {preview}")

        # Get or create session
        key = session_key or msg.session_key
        session = self.sessions.get_or_create(key)

        # Handle slash commands
        cmd = msg.content.strip().lower()
        if cmd == "/new":
            session.clear()
            session.metadata.pop("todos", None)
            self.sessions.save(session)
            return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                                  content="🐈 New session started.")
        if cmd == "/help":
            return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                                  content="🐈 nanobot commands:\n/new — Start a new conversation\n/help — Show available commands")

        # Update tool contexts
        message_tool = self.tools.get("message")
        if isinstance(message_tool, MessageTool):
            message_tool.set_context(msg.channel, msg.chat_id)

        spawn_tool = self.tools.get("spawn")
        if isinstance(spawn_tool, SpawnTool):
            spawn_tool.set_context(msg.channel, msg.chat_id)

        cron_tool = self.tools.get("cron")
        if isinstance(cron_tool, CronTool):
            cron_tool.set_context(msg.channel, msg.chat_id)

        # Stabilize and persist the accepted user message before calling the provider.
        display_content = msg.metadata.get("display_content") if msg.metadata else None
        stable_user = stabilize_user_message(
            session_key=key,
            text=msg.content,
            attachments=msg.attachments if msg.attachments else None
        )
        if key.startswith("web:") and not session.metadata.get("sessionTitle"):
            session.metadata["sessionTitle"] = display_content
            self.sessions.save(session)
        user_record = session.add_user_message(
            stable_user["content"],
            agent_status=status.snapshot(session),
            display_content=display_content,
            attachments=_attachment_history_metadata(msg.attachments),
            **({"id": msg.metadata["message_id"]} if msg.metadata.get("message_id") else {}),
        )
        self.sessions.append(session, user_record)

        return await self._run_turn(
            session=session,
            status=status,
            channel=msg.channel,
            chat_id=msg.chat_id,
            metadata=msg.metadata or {},
            emit_events=emit_events,
            empty_response="I've completed processing but have no response to give.",
        )

    async def _process_system_message(
        self,
        msg: InboundMessage,
        *,
        emit_events: bool = True,
    ) -> OutboundMessage | None:
        """
        Process a system message (e.g., subagent announce).

        The chat_id field contains "original_channel:original_chat_id" to route
        the response back to the correct destination.
        """
        status = AgentStatus()
        logger.info(f"Processing system message from {msg.sender_id}")

        # Parse origin from chat_id (format: "channel:chat_id")
        if ":" in msg.chat_id:
            parts = msg.chat_id.split(":", 1)
            origin_channel = parts[0]
            origin_chat_id = parts[1]
        else:
            # Fallback
            origin_channel = "cli"
            origin_chat_id = msg.chat_id

        # Use the origin session for context
        session_key = f"{origin_channel}:{origin_chat_id}"
        session = self.sessions.get_or_create(session_key)

        # Update tool contexts
        message_tool = self.tools.get("message")
        if isinstance(message_tool, MessageTool):
            message_tool.set_context(origin_channel, origin_chat_id)

        spawn_tool = self.tools.get("spawn")
        if isinstance(spawn_tool, SpawnTool):
            spawn_tool.set_context(origin_channel, origin_chat_id)

        cron_tool = self.tools.get("cron")
        if isinstance(cron_tool, CronTool):
            cron_tool.set_context(origin_channel, origin_chat_id)

        # Build messages with the announce content
        system_record = session.add_system_message(
            f"[System: {msg.sender_id}] {msg.content}",
            agent_status=status.snapshot(session),
        )
        self.sessions.append(session, system_record)
        return await self._run_turn(
            session=session,
            channel=origin_channel,
            chat_id=origin_chat_id,
            emit_events=emit_events,
            empty_response="Background task completed.",
            status=status,
        )

    async def _run_turn(
        self,
        *,
        session: Session,
        status: AgentStatus,
        channel: str,
        chat_id: str,
        emit_events: bool,
        empty_response: str,
        metadata: dict[str, Any] | None = None,
    ) -> OutboundMessage:
        """Run the shared role-based assistant/tool state machine."""
        turn_tools = ToolRegistry()
        for name in self.tools.tool_names:
            tool = self.tools.get(name)
            if tool is not None:
                turn_tools.register(tool)
        turn_tools.register(TodoEditTool(session, self.sessions))
        system_prompt = self.context.build_system_prompt(channel=channel)
        tools = turn_tools.get_definitions()
        for _ in range(self.max_iterations):
            try:
                messages = await self._prepare_main_request(
                    session,
                    channel=channel,
                    chat_id=chat_id,
                    system_prompt=system_prompt,
                    tools=tools,
                )
                publish_context(model=self.model, messages=messages, tools=tools)
                response = await self.provider.chat(
                    messages=messages,
                    tools=tools,
                    model=self.model,
                    max_tokens=self.max_tokens,
                )
            except Exception as exc:
                return self._persist_final(
                    session=session,
                    channel=channel,
                    chat_id=chat_id,
                    content=f"Sorry, I encountered an error: {str(exc)}",
                    metadata=metadata,
                )

            tool_calls = [
                {
                    "id": tool_call.id,
                    "type": "function",
                    "function": {
                        "name": tool_call.name,
                        "arguments": tool_call.raw_arguments,
                    },
                }
                for tool_call in response.tool_calls
            ]
            response_content = response.content or ""
            if not response.has_tool_calls and not response_content:
                response_content = empty_response
            assistant_record = session.add_assistant_message(
                response_content,
                reasoning_content=response.reasoning_content,
                tool_calls=tool_calls,
            )
            self.sessions.append(session, assistant_record)
            messages = self._build_main_messages(
                session,
                channel=channel,
                chat_id=chat_id,
                system_prompt=system_prompt,
            )

            publish_context(model=self.model, messages=messages, tools=tools)

            if not response.has_tool_calls:
                return OutboundMessage(
                    channel=channel,
                    chat_id=chat_id,
                    content=response_content,
                    kind="assistant_final",
                    assistant_record=assistant_record,
                    metadata=metadata or {},
                )

            if emit_events:
                await self.bus.publish_outbound(
                    OutboundMessage(
                        channel=channel,
                        chat_id=chat_id,
                        content=response.content or "",
                        kind="assistant_stage",
                        assistant_record=assistant_record,
                        metadata=metadata or {},
                    )
                )

            for tool_call in response.tool_calls:
                args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
                logger.info(f"Tool call: {tool_call.name}({args_str[:200]})")
                try:
                    result = await turn_tools.execute(tool_call.name, tool_call.arguments)
                except Exception as exc:
                    result = f"Error executing {tool_call.name}: {str(exc)}"
                result = compress_tool_result(result, self.max_tool_result_tokens)
                logger.info(f"Tool result: {tool_call.name}({result})")
                tool_record = session.add_tool_result(
                    tool_call_id=tool_call.id,
                    name=tool_call.name,
                    content=result,
                    agent_status=status.snapshot(session),
                )
                self.sessions.append(session, tool_record)
                messages = self._build_main_messages(
                    session,
                    channel=channel,
                    chat_id=chat_id,
                    system_prompt=system_prompt,
                )
                publish_context(model=self.model, messages=messages, tools=tools)

        return self._persist_final(
            session=session,
            channel=channel,
            chat_id=chat_id,
            content=f"Reached {self.max_iterations} iterations without completion.",
            metadata=metadata,
        )

    def _build_main_messages(
        self,
        session: Session,
        *,
        channel: str,
        chat_id: str,
        system_prompt: str,
    ) -> list[dict[str, Any]]:
        """Rebuild the actual main-model context from committed session state."""
        return self.context.build_messages_from_llm_history(
            session.get_llm_history(),
            channel=channel,
            chat_id=chat_id,
            history_summary=session.compression.summary,
            system_prompt=system_prompt,
        )

    async def _prepare_main_request(
        self,
        session: Session,
        *,
        channel: str,
        chat_id: str,
        system_prompt: str,
        tools: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        self.history_compression.prepare_for_request(session)
        messages = self._build_main_messages(
            session,
            channel=channel,
            chat_id=chat_id,
            system_prompt=system_prompt,
        )
        request_tokens = self.history_compression.estimate_request(
            messages=messages,
            tools=tools,
        )
        if await self.history_compression.maybe_summarize(
            session,
            request_tokens=request_tokens,
            summary_provider=self.summary_provider,
            summary_model=self.summary_model,
        ):
            messages = self._build_main_messages(
                session,
                channel=channel,
                chat_id=chat_id,
                system_prompt=system_prompt,
            )
            request_tokens = self.history_compression.estimate_request(
                messages=messages,
                tools=tools,
            )
        self.history_compression.warn_if_still_over_threshold(request_tokens)
        return messages

    def _persist_final(
        self,
        *,
        session: Session,
        channel: str,
        chat_id: str,
        content: str,
        metadata: dict[str, Any] | None,
    ) -> OutboundMessage:
        record = session.add_assistant_message(content)
        self.sessions.append(session, record)
        return OutboundMessage(
            channel=channel,
            chat_id=chat_id,
            content=content,
            kind="assistant_final",
            assistant_record=record,
            metadata=metadata or {},
        )

    async def process_direct(
        self,
        content: str,
        session_key: str = "cli:direct",
        channel: str = "cli",
        chat_id: str = "direct",
    ) -> str:
        """
        Process a message directly (for CLI or cron usage).

        Args:
            content: The message content.
            session_key: Session identifier (overrides channel:chat_id for session lookup).
            channel: Source channel (for tool context routing).
            chat_id: Source chat ID (for tool context routing).

        Returns:
            The agent's response.
        """
        msg = InboundMessage(
            channel=channel,
            sender_id="user",
            chat_id=chat_id,
            content=content
        )

        response = await self._process_message(
            msg,
            session_key=session_key,
            emit_events=False,
        )
        return response.content if response else ""


def _attachment_history_metadata(attachments: list[InboundAttachment]) -> list[dict[str, object]]:
    """Return JSON-serializable attachment metadata for session history."""
    return [attachment.to_history_metadata() for attachment in attachments]
