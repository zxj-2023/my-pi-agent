"""my-pi-agent Python CLI entrypoint facade.

This module provides the main() entrypoint when my-pi-agent is launched via
Python (e.g. `uvx my-pi-agent`, `uv tool install my-pi-agent`, or `python -m my_coding_agent.cli`).
It detects the system Node.js runtime and bridges to the Pi-TUI frontend.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def find_tui_entry() -> Path | None:
    """Find the my-agent.js TUI entrypoint across dev and packaged locations."""
    # 1. Development workspace tree: <repo_root>/tui/bin/my-agent.js
    repo_root = Path(__file__).resolve().parent.parent.parent
    dev_path = repo_root / "tui" / "bin" / "my-agent.js"
    if dev_path.exists():
        return dev_path

    # 2. Package-bundled data directory: <package_dir>/tui/bin/my-agent.js
    pkg_bundled = Path(__file__).resolve().parent / "tui" / "bin" / "my-agent.js"
    if pkg_bundled.exists():
        return pkg_bundled

    # 3. System prefix share directory: <sys.prefix>/share/my-pi-agent/tui/bin/my-agent.js
    prefix_path = Path(sys.prefix) / "share" / "my-pi-agent" / "tui" / "bin" / "my-agent.js"
    if prefix_path.exists():
        return prefix_path

    return None


def main(argv: list[str] | None = None) -> int:
    """Main CLI entrypoint bridging to the Pi-TUI frontend."""
    if argv is None:
        argv = sys.argv[1:]

    node_bin = shutil.which("node")
    if not node_bin:
        print(
            "\n[my-pi-agent] 错误: 未检测到 Node.js 运行时环境。\n"
            "my-pi-agent 采用像素级 Pi-TUI 呈现层，需要 Node.js (>= 18.0) 运行交互界面。\n\n"
            "请安装 Node.js 后重试:\n"
            "  - 官方网站下载: https://nodejs.org\n"
            "  - 或使用极速版本管理器安装: fnm (https://github.com/Schniz/fnm) 或 nvm\n",
            file=sys.stderr,
        )
        return 1

    tui_entry = find_tui_entry()
    if not tui_entry or not tui_entry.exists():
        print(
            "\n[my-pi-agent] 错误: 未找到 TUI 启动入口脚本 (my-agent.js)。\n"
            "请确保已正确构建前端: npm run build --prefix tui\n",
            file=sys.stderr,
        )
        return 1

    cmd = [node_bin, str(tui_entry), *argv]
    if "--python-executable" not in argv:
        cmd.extend(["--python-executable", sys.executable])

    try:
        proc = subprocess.run(cmd)
        return proc.returncode
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"[my-pi-agent] 启动异常: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
