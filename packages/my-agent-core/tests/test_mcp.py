"""MCP 客户端核心与连接测试（100% 离线测试）。"""

import sys

from my_agent_core.extensions.builtin.mcp import MCPClientManager, MCPServerConfig

FAKE_SERVER_CODE = """
import asyncio
from mcp.server import MCPServer

app = MCPServer("test-server")

@app.tool(description="Echo input text")
def fake_echo(text: str) -> str:
    return f"ECHO: {text}"

@app.tool(description="Always fail")
def fake_error() -> str:
    raise RuntimeError("Something went wrong")

async def main():
    await app.run_stdio_async()

if __name__ == "__main__":
    asyncio.run(main())
"""


def test_mcp_config_parsing(tmp_path):
    """验证 .mcp.json 配置正确解析。"""
    config_file = tmp_path / ".mcp.json"
    config_file.write_text(
        """
    {
      "mcpServers": {
        "local_srv": {
          "command": "python",
          "args": ["-m", "fake"],
          "env": {"DEBUG": "1"}
        }
      }
    }
    """,
        encoding="utf-8",
    )

    manager = MCPClientManager()
    configs = manager.load_config(config_file)
    assert len(configs) == 1
    assert configs[0].name == "local_srv"
    assert configs[0].command == "python"
    assert configs[0].args == ["-m", "fake"]
    assert configs[0].env == {"DEBUG": "1"}


def test_mcp_connection_lifecycle_and_tools(tmp_path):
    """验证使用 Python 子进程建立 Stdio 连接并调用工具。"""
    server_script = tmp_path / "fake_server.py"
    server_script.write_text(FAKE_SERVER_CODE, encoding="utf-8")

    cfg = MCPServerConfig(
        name="test_server",
        command=sys.executable,
        args=[str(server_script)],
    )

    manager = MCPClientManager()
    tools = manager.connect_server(cfg)
    try:
        assert len(tools) == 2
        tool_map = {t.name: t for t in tools}
        assert "fake_echo" in tool_map
        assert "fake_error" in tool_map

        # 测试正常调用
        echo_tool = tool_map["fake_echo"]
        res = echo_tool.execute({"text": "Hello MCP"})
        assert res.ok is True
        assert res.data == "ECHO: Hello MCP"
        assert res.meta.get("server") == "test_server"

        # 测试错误调用
        err_tool = tool_map["fake_error"]
        err_res = err_tool.execute({})
        assert err_res.ok is False
        assert err_res.error is not None
        assert "Something went wrong" in err_res.error
    finally:
        manager.close_all()
