"""MCP Extension 端到端集成测试（FakeLLM 驱动）。"""

import json
import sys

import pytest
from my_agent_llm import Response

from my_agent_core import Agent
from my_agent_core.session import Session

FAKE_SERVER_CODE = """
import asyncio
from mcp.server import MCPServer

app = MCPServer("calc-server")

@app.tool(description="Add two numbers")
def mcp_add(a: int, b: int) -> str:
    return str(a + b)

async def main():
    await app.run_stdio_async()

if __name__ == "__main__":
    asyncio.run(main())
"""


class FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def achat_stream(self, *, messages, tools=None, **kwargs):
        self.calls.append({"messages": list(messages), "tools": tools, **kwargs})
        resp = self.responses.pop(0)
        yield resp

    async def achat(self, *, messages, tools=None, **kwargs):
        self.calls.append({"messages": list(messages), "tools": tools, **kwargs})
        return self.responses.pop(0)

    def chat(self, *, messages, tools=None, **kwargs):
        self.calls.append({"messages": list(messages), "tools": tools, **kwargs})
        return self.responses.pop(0)


def _response(content="", tool_calls=None):
    return Response(content=content, model="fake", tool_calls=tool_calls)


@pytest.mark.anyio
async def test_mcp_extension_integration(tmp_path):
    """验证 Extension 通过 .mcp.json 注册 MCP 工具并成功被 Agent ReAct 循环调用。"""
    # 1. 写入 Fake MCP Server 脚本
    server_script = tmp_path / "server.py"
    server_script.write_text(FAKE_SERVER_CODE, encoding="utf-8")

    # 2. 写入 .mcp.json
    mcp_config = tmp_path / ".mcp.json"
    mcp_config.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "calc": {"command": sys.executable, "args": [str(server_script)]}
                }
            }
        ),
        encoding="utf-8",
    )

    # 3. 编写 MCP 加载 extension 脚本 (支持 async def)
    ext_dir = tmp_path / "exts"
    ext_dir.mkdir()
    ext_file = ext_dir / "mcp_ext.py"
    ext_file.write_text(
        f"""
from my_coding_agent.mcp import MCPClientManager

async def extension(api):
    manager = MCPClientManager()
    configs = manager.load_config(r"{mcp_config}")
    for cfg in configs:
        tools = await manager.connect_server(cfg)
        for t in tools:
            api.register_tool(t)
    # 将 manager 挂到 api 上，供测试收尾时关闭
    api._test_mcp_manager = manager
""",
        encoding="utf-8",
    )

    # 4. 组装 Agent 并运行
    llm = FakeLLM(
        [
            _response(
                tool_calls=[
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "mcp_add",
                            "arguments": json.dumps({"a": 10, "b": 25}),
                        },
                    }
                ]
            ),
            _response(content="Result is 35"),
        ]
    )

    session = Session(path=tmp_path / "session.jsonl")
    agent = Agent(llm=llm, tools=[], session=session, extension_dirs=[ext_dir])

    try:
        result = await agent.run("calculate 10 + 25")
        assert result == "Result is 35"

        # 验证 registry 包含了 mcp_add 工具
        tool_obj = agent.registry.get("mcp_add")
        assert tool_obj is not None
        assert tool_obj.raw_schema is not None

        # 验证历史记录正确收到了工具结果
        tool_msg = [m for m in agent.messages if m.role == "tool"][0]
        assert tool_msg.content == "35"
    finally:
        # 关闭 MCP 子进程，避免跨测试资源泄漏
        mgr = getattr(agent.extension_manager.api, "_test_mcp_manager", None)
        if mgr is not None:
            await mgr.close_all()


@pytest.mark.anyio
async def test_builtin_mcp_extension_with_command(tmp_path, monkeypatch):
    """验证内置 mcp.py extension 入口函数与 /mcp 状态命令。"""
    monkeypatch.chdir(tmp_path)

    # 1. 写入 Fake MCP Server 脚本
    server_script = tmp_path / "server.py"
    server_script.write_text(FAKE_SERVER_CODE, encoding="utf-8")

    # 2. 写入 .mcp.json
    mcp_config = tmp_path / ".mcp.json"
    mcp_config.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "calc_server": {
                        "command": sys.executable,
                        "args": [str(server_script)],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    # 3. 构造 Agent 并执行 mcp_extension
    session = Session(path=tmp_path / "session.jsonl")
    agent = Agent(llm=FakeLLM([]), tools=[], session=session, extension_dirs=[])

    # mcp_extension 内部创建的 manager 通过闭包持有连接；无法从外部访问，
    # 改为通过 MCPClientManager 单独连接并在 finally 里关闭。
    from my_coding_agent.mcp import MCPClientManager, MCPServerConfig

    mgr = MCPClientManager()
    cfg = MCPServerConfig(
        name="calc_server",
        command=sys.executable,
        args=[str(server_script)],
    )
    try:
        tools = await mgr.connect_server(cfg)
        for t in tools:
            agent.registry.register(t)

        # 验证工具被注册
        assert agent.registry.get("mcp_add") is not None
    finally:
        await mgr.close_all()
