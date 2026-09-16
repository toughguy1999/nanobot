"""Shell execution tool."""

import asyncio
import os
import re
import shutil
from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import Tool

# Best-effort text checks, not a PowerShell parser or sandbox. Recognize native
# cmdlets, common deletion aliases, and Windows utilities callable from pwsh.
_DENY_PATTERNS = (
    # Recursive/forced deletion, including PowerShell parameter abbreviations.
    r"(?<![\w-])(?:Remove-Item|ri|rm|rmdir|del|erase|rd)\b"
    r"[^;|\r\n]*?\s+-(?:r(?:e(?:c(?:u(?:r(?:s(?:e)?)?)?)?)?)?|f(?:o(?:r(?:c(?:e)?)?)?)?)(?=[:\s;|]|$)",
    # Destructive storage operations (do not block Format-Table/Format-List).
    r"(?<![\w-])(?:Clear-Disk|Initialize-Disk|Format-Volume|Remove-Partition|"
    r"Remove-PhysicalDisk|Reset-PhysicalDisk)(?![\w-])",
    # System shutdown/restart cmdlets and their Windows executable equivalents.
    r"(?<![\w-])(?:Stop-Computer|Restart-Computer)(?![\w-])",
    r"(?<![\w-])(?:diskpart(?:\.exe)?|format(?:\.com|\.exe)?|shutdown(?:\.exe)?)"
    r"(?=[\s\"';|]|$)",
)


def get_execution_shell() -> str:
    """Share the shell executable between execution and prompt rendering."""
    return shutil.which("pwsh") or "pwsh"


class ExecTool(Tool):
    """Tool to execute shell commands."""

    def __init__(
        self,
        timeout: int = 60,
        working_dir: str | None = None,
        restrict_to_workspace: bool = False,
    ):
        self.timeout = timeout
        self.working_dir = working_dir
        self.restrict_to_workspace = restrict_to_workspace

    @property
    def name(self) -> str:
        return "exec_command"

    @property
    def description(self) -> str:
        return (
            "使用 PowerShell 7（pwsh）执行命令，可用于读取文件、列举目录、搜索、运行脚本和测试等。"
            "输出按 UTF-8 解码，先返回标准输出，再以 STDERR: 标记标准错误，不保留两者的交错顺序；"
            "执行前会通过文本规则拦截部分危险命令，如递归或强制删除、磁盘破坏操作、关机和重启。"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": (
                        "必填，非空的 PowerShell 7 命令或多行脚本正文"
                    )
                },
                "working_dir": {
                    "type": "string",
                    "description": (
                        "可选，本次调用的工作目录，建议传入已存在目录的绝对路径；不会自动创建目录。"
                        "省略时默认使用 workspace；本次切换目录不会影响后续调用或文件工具的路径基准。"
                    )
                }
            },
            "required": ["command"]
        }

    async def execute(self, command: str, working_dir: str | None = None, **kwargs: Any) -> str:
        cwd = working_dir or self.working_dir or os.getcwd()
        guard_error = self._guard_command(command, cwd)
        if guard_error:
            return guard_error

        try:
            executable = get_execution_shell()
            if shutil.which(executable) is None:
                return "Error: PowerShell 7 (pwsh) was not found in PATH"
            utf8 = (
                "[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false); "
                "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
                "$OutputEncoding = [System.Text.UTF8Encoding]::new($false);\n"
            )
            process = await asyncio.create_subprocess_exec(
                executable, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command",
                utf8 + command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.communicate()
                return f"Error: Command timed out after {self.timeout} seconds"

            output_parts = []

            if stdout:
                output_parts.append(stdout.decode("utf-8", errors="replace"))

            if stderr:
                stderr_text = stderr.decode("utf-8", errors="replace")
                if stderr_text.strip():
                    output_parts.append(f"STDERR:\n{stderr_text}")

            if process.returncode != 0:
                output_parts.append(f"\nExit code: {process.returncode}")

            result = "\n".join(output_parts) if output_parts else "(no output)"

            return result

        except Exception as e:
            return f"Error executing command: {str(e)}"

    def _guard_command(self, command: str, cwd: str) -> str | None:
        """Best-effort safety guard for potentially destructive commands."""
        cmd = command.strip()
        # Join PowerShell continuation lines and common backtick-escaped names.
        normalized = re.sub(r"`\r?\n", "", cmd).replace("`", "")

        for pattern in _DENY_PATTERNS:
            if re.search(pattern, normalized, re.IGNORECASE):
                return "Error: Command blocked by safety guard (dangerous pattern detected)"

        if self.restrict_to_workspace:
            if "..\\" in cmd or "../" in cmd:
                return "Error: Command blocked by safety guard (path traversal detected)"

            cwd_path = Path(cwd).resolve()

            win_paths = re.findall(r"[A-Za-z]:\\[^\\\"']+", cmd)
            # Only match absolute paths — avoid false positives on relative
            # paths like ".venv/bin/python" where "/bin/python" would be
            # incorrectly extracted by the old pattern.
            posix_paths = re.findall(r"(?:^|[\s|>])(/[^\s\"'>]+)", cmd)

            for raw in win_paths + posix_paths:
                try:
                    p = Path(raw.strip()).resolve()
                except Exception:
                    continue
                if p.is_absolute() and cwd_path not in p.parents and p != cwd_path:
                    return "Error: Command blocked by safety guard (path outside working dir)"

        return None
