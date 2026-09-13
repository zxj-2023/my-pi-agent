"""工作区 .mcp.json 自动扫描与即插即用挂载测试。"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from my_agent_core.tools import Tool, ToolResult
from my_agent_llm.models import Response

from my_coding_agent.agent import CodingAgent


class FakeLLM:
    def __init__(self, response_text: str = "ok"):
        self.response_text = response_text
        self.calls = []

    async def achat(self, *a, **kw):
        self.calls.append({"args": a, "kwargs": kw})
        return Response(content=self.response_text, model="fake")

    async def achat_stream(self, *a, **kw):
        self.calls.append({"args": a, "kwargs": kw})
        yield Response(content=self.response_text, model="fake")


@pytest.mark.anyio
async def test_coding_agent_autoloads_mcp_if_configured(tmp_path: Path):
    """验证工作区存在 .mcp.json 时自动挂载外部 MCP 工具。"""
    mcp_config_file = tmp_path / ".mcp.json"
    mcp_config = {
        "mcpServers": {
            "demo": {
                "command": "python",
                "args": ["-c", "print('mock server')"],
            }
        }
    }
    mcp_config_file.write_text(json.dumps(mcp_config), encoding="utf-8")

    mock_tool = Tool(func=lambda: ToolResult(ok=True, data="mcp ok"), name="demo_tool")
    setattr(mock_tool, "is_mcp", True)

    with (
        patch(
            "my_coding_agent.mcp.MCPClientManager.connect_all",
            new_callable=AsyncMock,
        ) as mock_connect,
        patch(
            "my_coding_agent.mcp.MCPClientManager.get_all_tools",
            return_value=[mock_tool],
        ),
    ):
        agent = CodingAgent(
            workspace=tmp_path,
            llm=FakeLLM(),
            session=tmp_path / "s.jsonl",
            auto_load_mcp=True,
        )
        # 初始化时触发挂载
        await agent.ensure_mcp_loaded()

        assert "demo_tool" in agent.agent.registry._tools
        tool_entry = agent.agent.registry._tools["demo_tool"]
        assert getattr(tool_entry, "is_mcp", False) is True
        mock_connect.assert_awaited_once()

        await agent.close_mcp()


@pytest.mark.anyio
async def test_coding_agent_auto_load_mcp_disabled(tmp_path: Path):
    """验证 auto_load_mcp=False 时不扫描也不挂载 MCP 工具。"""
    mcp_config_file = tmp_path / ".mcp.json"
    mcp_config = {
        "mcpServers": {
            "demo": {"command": "python", "args": ["-c", "pass"]},
        }
    }
    mcp_config_file.write_text(json.dumps(mcp_config), encoding="utf-8")

    with patch(
        "my_coding_agent.mcp.MCPClientManager.connect_all",
        new_callable=AsyncMock,
    ) as mock_connect:
        agent = CodingAgent(
            workspace=tmp_path,
            llm=FakeLLM(),
            session=tmp_path / "s.jsonl",
            auto_load_mcp=False,
        )
        await agent.ensure_mcp_loaded()

        assert agent.mcp_manager is None
        mock_connect.assert_not_called()


@pytest.mark.anyio
async def test_coding_agent_no_mcp_file(tmp_path: Path):
    """验证工作区无 .mcp.json 时静默跳过挂载。"""
    agent = CodingAgent(
        workspace=tmp_path,
        llm=FakeLLM(),
        session=tmp_path / "s.jsonl",
        auto_load_mcp=True,
    )
    await agent.ensure_mcp_loaded()
    assert agent.mcp_manager is None


@pytest.mark.anyio
async def test_coding_agent_run_triggers_autoload(tmp_path: Path):
    """验证 agent.run() 会在首次执行时自动触发挂载。"""
    mcp_config_file = tmp_path / ".mcp.json"
    mcp_config = {
        "mcpServers": {
            "demo": {"command": "python", "args": ["-c", "pass"]},
        }
    }
    mcp_config_file.write_text(json.dumps(mcp_config), encoding="utf-8")

    mock_tool = Tool(func=lambda: ToolResult(ok=True, data="mcp ok"), name="demo_tool")
    setattr(mock_tool, "is_mcp", True)

    with (
        patch(
            "my_coding_agent.mcp.MCPClientManager.connect_all",
            new_callable=AsyncMock,
        ),
        patch(
            "my_coding_agent.mcp.MCPClientManager.get_all_tools",
            return_value=[mock_tool],
        ),
    ):
        agent = CodingAgent(
            workspace=tmp_path,
            llm=FakeLLM("response from fake llm"),
            session=tmp_path / "s.jsonl",
            auto_load_mcp=True,
        )
        res = await agent.run("hello")
        assert res == "response from fake llm"
        assert "demo_tool" in agent.agent.registry._tools
        await agent.close_mcp()


@pytest.mark.anyio
async def test_coding_agent_run_stream_triggers_autoload(tmp_path: Path):
    """验证 agent.run_stream() 会在首次执行时自动触发挂载。"""
    mcp_config_file = tmp_path / ".mcp.json"
    mcp_config = {
        "mcpServers": {
            "demo": {"command": "python", "args": ["-c", "pass"]},
        }
    }
    mcp_config_file.write_text(json.dumps(mcp_config), encoding="utf-8")

    mock_tool = Tool(func=lambda: ToolResult(ok=True, data="mcp ok"), name="demo_tool")
    setattr(mock_tool, "is_mcp", True)

    with (
        patch(
            "my_coding_agent.mcp.MCPClientManager.connect_all",
            new_callable=AsyncMock,
        ),
        patch(
            "my_coding_agent.mcp.MCPClientManager.get_all_tools",
            return_value=[mock_tool],
        ),
    ):
        agent = CodingAgent(
            workspace=tmp_path,
            llm=FakeLLM("stream response"),
            session=tmp_path / "s.jsonl",
            auto_load_mcp=True,
        )
        events = []
        async for ev in agent.run_stream("hello"):
            events.append(ev)

        assert len(events) > 0
        assert "demo_tool" in agent.agent.registry._tools
        await agent.close_mcp()


@pytest.mark.anyio
async def test_coding_agent_async_context_manager(tmp_path: Path):
    """验证 CodingAgent 异步上下文管理器模式（自动挂载与优雅回收）。"""
    mcp_config_file = tmp_path / ".mcp.json"
    mcp_config = {
        "mcpServers": {
            "demo": {"command": "python", "args": ["-c", "pass"]},
        }
    }
    mcp_config_file.write_text(json.dumps(mcp_config), encoding="utf-8")

    mock_tool = Tool(func=lambda: ToolResult(ok=True, data="mcp ok"), name="demo_tool")
    setattr(mock_tool, "is_mcp", True)

    with (
        patch(
            "my_coding_agent.mcp.MCPClientManager.connect_all",
            new_callable=AsyncMock,
        ),
        patch(
            "my_coding_agent.mcp.MCPClientManager.get_all_tools",
            return_value=[mock_tool],
        ),
        patch(
            "my_coding_agent.mcp.MCPClientManager.close_all",
            new_callable=AsyncMock,
        ) as mock_close,
    ):
        async with CodingAgent(
            workspace=tmp_path,
            llm=FakeLLM(),
            session=tmp_path / "s.jsonl",
            auto_load_mcp=True,
        ) as agent:
            assert "demo_tool" in agent.agent.registry._tools

        mock_close.assert_awaited_once()
        assert agent.mcp_manager is None


@pytest.mark.anyio
async def test_coding_agent_ensure_mcp_loaded_corrupted_json(tmp_path: Path):
    """验证 .mcp.json 非法 JSON 时优雅跳过不崩溃。"""
    mcp_config_file = tmp_path / ".mcp.json"
    mcp_config_file.write_text("invalid json content {{{", encoding="utf-8")

    agent = CodingAgent(
        workspace=tmp_path,
        llm=FakeLLM(),
        session=tmp_path / "s.jsonl",
        auto_load_mcp=True,
    )
    # 不应抛出异常
    await agent.ensure_mcp_loaded()
    assert agent.mcp_manager is None or len(agent.mcp_manager.connections) == 0


@pytest.mark.anyio
async def test_coding_agent_close_mcp_idempotent(tmp_path: Path):
    """验证 close_mcp 幂等性，多次调用或未加载时调用均安全。"""
    agent = CodingAgent(
        workspace=tmp_path,
        llm=FakeLLM(),
        session=tmp_path / "s.jsonl",
        auto_load_mcp=True,
    )
    await agent.close_mcp()
    await agent.close_mcp()
    assert agent.mcp_manager is None


@pytest.mark.anyio
async def test_coding_agent_only_loads_once(tmp_path: Path):
    """验证 ensure_mcp_loaded 多次调用仅执行一次连接加载。"""
    mcp_config_file = tmp_path / ".mcp.json"
    mcp_config = {
        "mcpServers": {
            "demo": {"command": "python", "args": ["-c", "pass"]},
        }
    }
    mcp_config_file.write_text(json.dumps(mcp_config), encoding="utf-8")

    mock_tool = Tool(func=lambda: ToolResult(ok=True, data="mcp ok"), name="demo_tool")
    setattr(mock_tool, "is_mcp", True)

    with (
        patch(
            "my_coding_agent.mcp.MCPClientManager.connect_all",
            new_callable=AsyncMock,
        ) as mock_connect,
        patch(
            "my_coding_agent.mcp.MCPClientManager.get_all_tools",
            return_value=[mock_tool],
        ),
    ):
        agent = CodingAgent(
            workspace=tmp_path,
            llm=FakeLLM(),
            session=tmp_path / "s.jsonl",
            auto_load_mcp=True,
        )
        await agent.ensure_mcp_loaded()
        await agent.ensure_mcp_loaded()

        mock_connect.assert_awaited_once()
        await agent.close_mcp()


@pytest.mark.anyio
async def test_coding_agent_connect_failure_graceful(tmp_path: Path):
    """验证 MCP 连接抛出异常时优雅降级并不影响 Agent。"""
    mcp_config_file = tmp_path / ".mcp.json"
    mcp_config = {
        "mcpServers": {
            "demo": {"command": "python", "args": ["-c", "pass"]},
        }
    }
    mcp_config_file.write_text(json.dumps(mcp_config), encoding="utf-8")

    with patch(
        "my_coding_agent.mcp.MCPClientManager.connect_all",
        side_effect=RuntimeError("connection failed"),
    ):
        agent = CodingAgent(
            workspace=tmp_path,
            llm=FakeLLM("still working"),
            session=tmp_path / "s.jsonl",
            auto_load_mcp=True,
        )
        res = await agent.run("test input")
        assert res == "still working"
        await agent.close_mcp()
