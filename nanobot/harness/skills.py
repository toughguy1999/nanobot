"""Discover skills and load their instructions on demand."""

import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

BUILTIN_SKILLS_DIR = Path(__file__).parent.parent / "skills"


@dataclass
class LoadedSkill:
    name: str
    directory: Path
    body: str
    missing_bins: list[str]
    missing_env: list[str]


class SkillsLoader:
    """Discover workspace skills before builtins, without caching loaded state."""

    def __init__(self, workspace: Path, builtin_skills_dir: Path | None = None):
        self.workspace = workspace.expanduser().resolve()
        self.workspace_skills = self.workspace / "skills"
        self.builtin_skills = (
            builtin_skills_dir if builtin_skills_dir is not None else BUILTIN_SKILLS_DIR
        ).expanduser().resolve()

    def list_skills(self) -> list[dict[str, str]]:
        """Discover direct child directories, regardless of missing dependencies."""
        skills: dict[str, dict[str, str]] = {}
        for root, source in (
            (self.workspace_skills, "workspace"), (self.builtin_skills, "builtin"),
        ):
            if not root.exists():
                continue
            for directory in sorted(root.iterdir()):
                skill_file = directory / "SKILL.md"
                if directory.is_dir() and skill_file.exists():
                    skills.setdefault(directory.name, {
                        "name": directory.name, "path": str(skill_file), "source": source,
                    })
        return list(skills.values())

    def _read_skill(self, skill: dict[str, str]) -> tuple[Path, str]:
        root = self.workspace_skills if skill["source"] == "workspace" else self.builtin_skills
        path = Path(skill["path"]).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError(f"Skill path is outside its skills directory: {skill['name']}")
        return path, path.read_text(encoding="utf-8")

    @staticmethod
    def _split_frontmatter(content: str) -> tuple[dict[str, str], str]:
        match = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)", content, re.DOTALL)
        if not match:
            return {}, content
        metadata = {}
        for line in match.group(1).splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                metadata[key.strip()] = value.strip().strip("\"'")
        return metadata, content[match.end():]

    @staticmethod
    def _parse_nanobot_metadata(raw: str) -> dict:
        try:
            data = json.loads(raw)
            metadata = data.get("nanobot", {}) if isinstance(data, dict) else {}
            return metadata if isinstance(metadata, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}

    def load_skill(self, name: str) -> LoadedSkill:
        """Resolve an exact discovered name and check its current dependencies."""
        skill = next((s for s in self.list_skills() if s["name"] == name), None)
        if skill is None:
            raise ValueError(f"Skill not found: {name}")
        path, content = self._read_skill(skill)
        metadata, body = self._split_frontmatter(content)
        requires = self._parse_nanobot_metadata(metadata.get("metadata", "")).get("requires", {})
        return LoadedSkill(
            name=name, directory=path.parent, body=body,
            missing_bins=[b for b in requires.get("bins", []) if not shutil.which(b)],
            missing_env=[e for e in requires.get("env", []) if not os.environ.get(e)],
        )

    def build_skills_summary(self) -> str:
        """Return only names and descriptions; never check dependencies."""
        lines = []
        for skill in self.list_skills():
            try:
                _, content = self._read_skill(skill)
                metadata, _ = self._split_frontmatter(content)
            except (OSError, UnicodeError, ValueError):
                # Keep unreadable skills visible; loading reports the failure.
                metadata = {}
            name = " ".join(skill["name"].splitlines())
            description = " ".join((metadata.get("description") or name).splitlines())
            lines.append(f"-{name}： {description}")
        return f"# Skills List\n\n{"\n".join(lines)}"
