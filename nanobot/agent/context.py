"""Context builder for assembling agent prompts."""

from pathlib import Path
from typing import Any

from nanobot.agent.compress.prompts import history_summary_message
from nanobot.agent.memory import MemoryStore
from nanobot.agent.prompts import get_basic_system_prompt
from nanobot.agent.skills import SkillsLoader


class ContextBuilder:
    """
    Builds the context (system prompt + messages) for the agent.

    Assembles bootstrap files, memory, skills, and conversation history
    into a coherent prompt for the LLM.
    """

    def __init__(
        self, workspace: Path, *, restrict_to_workspace: bool = False,
    ):
        self.workspace = workspace.expanduser().resolve()
        self.restrict_to_workspace = restrict_to_workspace
        self.memory = MemoryStore(self.workspace)
        self.skills = SkillsLoader(self.workspace)

    def build_system_prompt(self, channel: str | None = None) -> str:
        """Assemble static instructions and fresh per-turn context."""
        parts = []

        # Basic Prompt
        prompt = get_basic_system_prompt(
            workspace=self.workspace,
            restrict_to_workspace=self.restrict_to_workspace,
            channel=channel
        )
        parts.append(prompt)

        # Memory context
        memory = self.memory.get_memory_context()
        if memory:
            parts.append(f"# Memory\n\n{memory}")

        # Only descriptions enter the system prompt; bodies arrive via load_skill.
        skills_summary = self.skills.build_skills_summary()
        if skills_summary:
            parts.append(f"# Skills List\n\n{skills_summary}")

        return "\n\n---\n\n".join(parts)

    def build_messages_from_llm_history(
        self,
        llm_history: list[dict[str, Any]],
        channel: str | None = None,
        chat_id: str | None = None,
        history_summary: str | None = None,
        system_prompt: str | None = None,
    ) -> list[dict[str, Any]]:
        """Build provider messages from already-converted LLM history."""
        messages: list[dict[str, Any]] = []
        if system_prompt is None:
            system_prompt = self.build_system_prompt(channel=channel)
        messages.append({"role": "system", "content": system_prompt})
        if history_summary is not None:
            messages.append(history_summary_message(history_summary))
        messages.extend(llm_history)
        return messages

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
