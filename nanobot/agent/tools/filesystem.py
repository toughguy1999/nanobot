"""File system tools: write and edit."""

from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import Tool


def _resolve_path(
    path: str, allowed_dir: Path | None = None, workspace: Path | None = None,
) -> Path:
    """Resolve path and optionally enforce directory restriction."""
    resolved = Path(path).expanduser()
    if not resolved.is_absolute() and workspace is not None:
        resolved = workspace / resolved
    resolved = resolved.resolve()
    if allowed_dir and not resolved.is_relative_to(allowed_dir.resolve()):
        raise PermissionError(f"Path {path} is outside allowed directory {allowed_dir}")
    return resolved


class WriteFileTool(Tool):
    """Tool to write content to a file."""

    def __init__(self, allowed_dir: Path | None = None, *, workspace: Path | None = None):
        self._allowed_dir = allowed_dir
        self._workspace = workspace.expanduser().resolve() if workspace is not None else None

    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return "写入文件，按需创建父目录；会覆盖已有文件，覆盖前先读取已有内容。局部修改优先使用 edit_file，新建或完整重写才使用 write_file。"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "要写入的文件路径；相对路径以 workspace 为基准，也可使用绝对路径。"
                },
                "content": {
                    "type": "string",
                    "description": "要写入的完整文件内容"
                }
            },
            "required": ["path", "content"]
        }

    async def execute(self, path: str, content: str, **kwargs: Any) -> str:
        try:
            file_path = _resolve_path(path, self._allowed_dir, self._workspace)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            return f"Successfully wrote {len(content)} bytes to {path}"
        except PermissionError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error writing file: {str(e)}"


class EditFileTool(Tool):
    """Tool to edit a file by replacing text."""

    def __init__(self, allowed_dir: Path | None = None, *, workspace: Path | None = None):
        self._allowed_dir = allowed_dir
        self._workspace = workspace.expanduser().resolve() if workspace is not None else None

    @property
    def name(self) -> str:
        return "edit_file"

    @property
    def description(self) -> str:
        return "替换文件中的文本。修改前先读取相关内容，保留准确缩进；old_text 必须精确匹配且匹配唯一。"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "要编辑的文件路径；相对路径以 workspace 为基准，也可使用绝对路径。"
                },
                "old_text": {
                    "type": "string",
                    "description": "待替换的原文，保留准确缩进，必须精确匹配且唯一"
                },
                "new_text": {
                    "type": "string",
                    "description": "替换后的文本，保留准确缩进"
                }
            },
            "required": ["path", "old_text", "new_text"]
        }

    async def execute(self, path: str, old_text: str, new_text: str, **kwargs: Any) -> str:
        try:
            file_path = _resolve_path(path, self._allowed_dir, self._workspace)
            if not file_path.exists():
                return f"Error: File not found: {path}"

            content = file_path.read_text(encoding="utf-8")

            if old_text not in content:
                return "Error: old_text not found in file. Make sure it matches exactly."

            # Count occurrences
            count = content.count(old_text)
            if count > 1:
                return f"Warning: old_text appears {count} times. Please provide more context to make it unique."

            new_content = content.replace(old_text, new_text, 1)
            file_path.write_text(new_content, encoding="utf-8")

            return f"Successfully edited {path}"
        except PermissionError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error editing file: {str(e)}"
