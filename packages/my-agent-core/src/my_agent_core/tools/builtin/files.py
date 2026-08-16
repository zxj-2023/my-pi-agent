"""内置工具：四个文件工具（read/edit/write/bash）工厂 + 路径逃逸防护。"""
import subprocess
from pathlib import Path

from my_agent_core.tools import Tool

_TIMEOUT_SECONDS = 120
_DANGEROUS = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]


def _safe_path(root: Path, p: str) -> Path:
    """把 p（相对或绝对）解析到 root 内，逃逸 → ValueError。"""
    path = (root / p).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"Path escapes workspace: {p}")
    return path


def make_read_tool(root: str | Path) -> Tool:
    """read(path, limit=None)：读文件，limit 行截断 + '... (N more)'。"""
    root = Path(root).resolve()

    def read(path: str, limit: int | None = None) -> str:
        """Read file contents. Use limit for large files."""
        try:
            lines = _safe_path(root, path).read_text(encoding="utf-8").splitlines()
            if limit is not None and limit < len(lines):
                lines = lines[:limit] + [f"... ({len(lines) - limit} more)"]
            return "\n".join(lines)[:50000]
        except Exception as e:
            return f"Error: {e}"

    return Tool(func=read, name="read")


def make_write_tool(root: str | Path) -> Tool:
    """write(path, content)：覆盖写（自动建父目录）。"""
    root = Path(root).resolve()

    def write(path: str, content: str) -> str:
        """Write content to file. Creates/overwrites the file."""
        try:
            fp = _safe_path(root, path)
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(content, encoding="utf-8")
            return f"Wrote {len(content)} bytes"
        except Exception as e:
            return f"Error: {e}"

    return Tool(func=write, name="write")


def make_edit_tool(root: str | Path) -> Tool:
    """edit(path, old_text, new_text)：精确替换一次。"""
    root = Path(root).resolve()

    def edit(path: str, old_text: str, new_text: str) -> str:
        """Replace exact text in file (first occurrence only)."""
        try:
            fp = _safe_path(root, path)
            content = fp.read_text(encoding="utf-8")
            if old_text not in content:
                return f"Error: Text not found in {path}"
            fp.write_text(content.replace(old_text, new_text, 1), encoding="utf-8")
            return f"Edited {path}"
        except Exception as e:
            return f"Error: {e}"

    return Tool(func=edit, name="edit")


def make_bash_tool(root: str | Path) -> Tool:
    """bash(command)：在 root 下执行 shell，危险命令黑名单 + 超时。"""
    root = Path(root).resolve()

    def bash(command: str) -> str:
        """Run a shell command in the workspace root."""
        if any(d in command for d in _DANGEROUS):
            return "Error: Dangerous command blocked"
        try:
            r = subprocess.run(command, shell=True, cwd=root,
                               capture_output=True, text=True, timeout=_TIMEOUT_SECONDS)
            out = (r.stdout + r.stderr).strip()
            return out[:50000] if out else "(no output)"
        except subprocess.TimeoutExpired:
            return f"Error: Timeout ({_TIMEOUT_SECONDS}s)"
        except (FileNotFoundError, OSError) as e:
            return f"Error: {e}"

    return Tool(func=bash, name="bash")
