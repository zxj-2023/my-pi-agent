"""ACP stdio 服务端入口。

编辑器（Zed 等）会以子进程方式拉起本模块，通过 stdin/stdout 进行 JSON-RPC 2.0
通信。用法：

    python -m my_acp_agent.server --workspace /path/to/project

Zed 侧配置示例（``settings.json``）：

    {
      "agent_servers": {
        "my-pi-agent": {
          "command": "python",
          "args": ["-m", "my_acp_agent.server"],
          "env": {}
        }
      }
    }
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from acp import run_agent

from my_acp_agent.agent import AcpAgent

__all__ = ["main", "run"]

logger = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="my-pi-agent-acp",
        description="以 ACP (Agent Client Protocol) Agent 身份运行 my-pi-agent，供 Zed 等编辑器驱动。",
    )
    parser.add_argument(
        "-w",
        "--workspace",
        default=None,
        help="工作区目录（默认：当前目录）",
    )
    parser.add_argument(
        "-m",
        "--model",
        default=None,
        help="指定生效模型（如 deepseek-chat、gemini-3.8-flash）",
    )
    parser.add_argument(
        "--mode",
        default=None,
        choices=["review", "autonomous", "strict", "yolo"],
        help="权限安全模式（默认：读取用户配置，回落 review）",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="输出调试日志到 stderr",
    )
    return parser


async def run(workspace: Path | None = None, model: str | None = None, mode: str | None = None) -> None:
    """构造 ``AcpAgent`` 并挂到 stdio 上开始监听。"""
    agent = AcpAgent(workspace=workspace, model=model, mode=mode)
    await run_agent(agent)


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.WARNING,
        stream=sys.stderr,
        format="[my-pi-agent-acp] %(levelname)s %(name)s: %(message)s",
    )

    workspace = Path(args.workspace).resolve() if args.workspace else None

    try:
        asyncio.run(run(workspace=workspace, model=args.model, mode=args.mode))
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
