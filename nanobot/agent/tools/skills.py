"""Load one skill into ordinary tool history."""

from typing import Any
from xml.sax.saxutils import escape

from nanobot.agent.skills import SkillsLoader
from nanobot.agent.tools.base import Tool


class LoadSkillTool(Tool):
    def __init__(self, loader: SkillsLoader):
        self.loader = loader

    @property
    def name(self) -> str:
        return "load_skill"

    @property
    def description(self) -> str:
        return (
            "Use when you need full content of a skill. Load one skill by its listed name. Returns with XML sections"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "Skill name from the summary"}},
            "required": ["name"],
            "additionalProperties": False,
        }

    async def execute(self, name: str) -> str:
        try:
            skill = self.loader.load_skill(name)
        except (OSError, UnicodeError, ValueError) as exc:
            return (
                f"<skill_error>\n  <name>{escape(name)}</name>\n"
                f"  <message>{escape(str(exc))}</message>\n</skill_error>"
            )
        lines = [
            "<skill>", f"  <name>{escape(skill.name)}</name>",
            f"  <directory>{escape(str(skill.directory))}</directory>",
        ]
        if skill.missing_bins or skill.missing_env:
            lines.append("  <missing_requirements>")
            lines.extend(f"    <bin>{escape(b)}</bin>" for b in skill.missing_bins)
            lines.extend(f"    <env>{escape(e)}</env>" for e in skill.missing_env)
            lines.append("  </missing_requirements>")
        lines.extend([f"  <body>{escape(skill.body)}</body>", "</skill>"])
        return "\n".join(lines)
