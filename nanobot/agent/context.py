"""Context builder for assembling agent prompts."""

import base64
import mimetypes
import platform
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.agent.attachments import TEXT_CONTEXT_CHAR_LIMIT
from nanobot.agent.memory import MemoryStore
from nanobot.agent.skills import SkillsLoader
from nanobot.bus.events import InboundAttachment


class ContextBuilder:
    """
    Builds the context (system prompt + messages) for the agent.

    Assembles bootstrap files, memory, skills, and conversation history
    into a coherent prompt for the LLM.
    """

    BOOTSTRAP_FILES = ["AGENTS.md", "SOUL.md", "USER.md", "TOOLS.md", "IDENTITY.md"]

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.memory = MemoryStore(workspace)
        self.skills = SkillsLoader(workspace)

    def build_system_prompt(self, skill_names: list[str] | None = None) -> str:
        """
        Build the system prompt from bootstrap files, memory, and skills.

        Args:
            skill_names: Optional list of skills to include.

        Returns:
            Complete system prompt.
        """
        parts = []

        # Core identity
        parts.append(self._get_identity())

        # Bootstrap files
        bootstrap = self._load_bootstrap_files()
        if bootstrap:
            parts.append(bootstrap)

        # Memory context
        memory = self.memory.get_memory_context()
        if memory:
            parts.append(f"# Memory\n\n{memory}")

        # Skills - progressive loading
        # 1. Always-loaded skills: include full content
        always_skills = self.skills.get_always_skills()
        if always_skills:
            always_content = self.skills.load_skills_for_context(always_skills)
            if always_content:
                parts.append(f"# Active Skills\n\n{always_content}")

        # 2. Available skills: only show summary (agent uses read_file to load)
        skills_summary = self.skills.build_skills_summary()
        if skills_summary:
            parts.append(f"""# Skills

The following skills extend your capabilities. To use a skill, read its SKILL.md file using the read_file tool.
Skills with available="false" need dependencies installed first - you can try installing them with apt/brew.

{skills_summary}""")

        return "\n\n---\n\n".join(parts)

    def _get_identity(self) -> str:
        """Get the core identity section."""
        import time as _time
        from datetime import datetime
        now = datetime.now().strftime("%Y-%m-%d %H:%M (%A)")
        tz = _time.strftime("%Z") or "UTC"
        workspace_path = str(self.workspace.expanduser().resolve())
        system = platform.system()
        runtime = f"{'macOS' if system == 'Darwin' else system} {platform.machine()}, Python {platform.python_version()}"

        return f"""# nanobot 🐈

You are nanobot, a helpful AI assistant. You have access to tools that allow you to:
- Read, write, and edit files
- Execute shell commands
- Search the web and fetch web pages
- Send messages to users on chat channels
- Spawn subagents for complex background tasks

## Current Time
{now} ({tz})

## Runtime
{runtime}

## Workspace
Your workspace is at: {workspace_path}
- Long-term memory: {workspace_path}/memory/MEMORY.md
- History log: {workspace_path}/memory/HISTORY.md (grep-searchable)
- Custom skills: {workspace_path}/skills/{{skill-name}}/SKILL.md

IMPORTANT: When responding to direct questions or conversations, reply directly with your text response.
Only use the 'message' tool when you need to send a message to a specific chat channel (like WhatsApp).
For normal conversation, just respond with text - do not call the message tool.

Always be helpful, accurate, and concise. When using tools, think step by step: what you know, what you need, and why you chose this tool.
When remembering something important, write to {workspace_path}/memory/MEMORY.md
To recall past events, grep {workspace_path}/memory/HISTORY.md"""

    def _load_bootstrap_files(self) -> str:
        """Load all bootstrap files from workspace."""
        parts = []

        for filename in self.BOOTSTRAP_FILES:
            file_path = self.workspace / filename
            if file_path.exists():
                content = file_path.read_text(encoding="utf-8")
                parts.append(f"## {filename}\n\n{content}")

        return "\n\n".join(parts) if parts else ""

    def build_messages(
        self,
        history: list[dict[str, Any]],
        current_message: str,
        skill_names: list[str] | None = None,
        attachments: list[InboundAttachment] | None = None,
        channel: str | None = None,
        chat_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Build the complete message list for an LLM call.

        Args:
            history: Previous conversation messages.
            current_message: The new user message.
            skill_names: Optional skills to include.
            attachments: Optional local inbound attachments.
            channel: Current channel (telegram, feishu, etc.).
            chat_id: Current chat/user ID.

        Returns:
            List of messages including system prompt.
        """
        messages: list[dict[str, Any]] = []

        # System prompt
        system_prompt = self.build_system_prompt(skill_names)
        if channel and chat_id:
            system_prompt += f"\n\n## Current Session\nChannel: {channel}\nChat ID: {chat_id}"
        messages.append({"role": "system", "content": system_prompt})

        # History
        messages.extend(history)

        # Current message (with optional text/image attachments)
        user_content = self._build_user_content(current_message, attachments)
        messages.append({"role": "user", "content": user_content})

        return messages

    def _build_user_content(
        self,
        text: str,
        attachments: list[InboundAttachment] | None,
    ) -> str | list[dict[str, Any]]:
        """Build user message content with optional attachment context."""
        if not attachments:
            return text

        text_sections: list[str] = []
        images = []
        for attachment in attachments:
            if attachment.type == "text":
                section = self._read_text_attachment(attachment)
                if section:
                    text_sections.append(section)
            elif attachment.type == "image":
                image = self._read_image_attachment(attachment)
                if image:
                    images.append(image)
            else:
                logger.warning(f"Skipping unsupported attachment type: {attachment.type}")

        merged_text = text
        if text_sections:
            merged_text = "\n\n".join([text, *text_sections]) if text else "\n\n".join(text_sections)

        if not images:
            return merged_text
        return images + [{"type": "text", "text": merged_text}]

    def _read_text_attachment(self, attachment: InboundAttachment) -> str | None:
        path = Path(attachment.path)
        if not path.is_file():
            logger.warning(f"Skipping text attachment with unavailable path: {path}")
            return None
        try:
            raw = path.read_bytes()
        except OSError as exc:
            logger.warning(f"Failed to read text attachment {attachment.file_name}: {exc}")
            return None

        text = raw.decode("utf-8", errors="replace")
        if "\ufffd" in text:
            logger.warning(f"Text attachment {attachment.file_name} had invalid UTF-8 bytes")
        truncated = len(text) > TEXT_CONTEXT_CHAR_LIMIT
        text = text[:TEXT_CONTEXT_CHAR_LIMIT]
        suffix = "\n\n[Text attachment truncated at 100,000 characters.]" if truncated else ""
        mime = attachment.mime_type or "application/octet-stream"
        return f"[Text attachment: {attachment.file_name}, {mime}]\n{text}{suffix}"

    def _read_image_attachment(self, attachment: InboundAttachment) -> dict[str, Any] | None:
        path = Path(attachment.path)
        if not path.is_file():
            logger.warning(f"Skipping image attachment with unavailable path: {path}")
            return None
        mime = attachment.mime_type or mimetypes.guess_type(str(path))[0]
        if not mime or not mime.startswith("image/"):
            logger.warning(f"Skipping image attachment with unsupported MIME type: {attachment.file_name}")
            return None
        try:
            b64 = base64.b64encode(path.read_bytes()).decode()
        except OSError as exc:
            logger.warning(f"Failed to read image attachment {attachment.file_name}: {exc}")
            return None
        return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}

    def add_tool_result(
        self,
        messages: list[dict[str, Any]],
        tool_call_id: str,
        tool_name: str,
        result: str
    ) -> list[dict[str, Any]]:
        """
        Add a tool result to the message list.

        Args:
            messages: Current message list.
            tool_call_id: ID of the tool call.
            tool_name: Name of the tool.
            result: Tool execution result.

        Returns:
            Updated message list.
        """
        messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": tool_name,
            "content": result
        })
        return messages

    def add_assistant_message(
        self,
        messages: list[dict[str, Any]],
        content: str | None,
        tool_calls: list[dict[str, Any]] | None = None,
        reasoning_content: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Add an assistant message to the message list.

        Args:
            messages: Current message list.
            content: Message content.
            tool_calls: Optional tool calls.
            reasoning_content: Thinking output (Kimi, DeepSeek-R1, etc.).

        Returns:
            Updated message list.
        """
        msg: dict[str, Any] = {"role": "assistant", "content": content or ""}

        if tool_calls:
            msg["tool_calls"] = tool_calls

        # Thinking models reject history without this
        if reasoning_content:
            msg["reasoning_content"] = reasoning_content

        messages.append(msg)
        return messages
