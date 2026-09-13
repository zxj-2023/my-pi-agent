"""Phase 3C 跨包端到端全链路验证与场景演练 (test_phase_3c_e2e.py)。

全面验证：
1. Scenario 1 (@file reference 1-turn analysis):
   用户在提示词中包含 @src/calculator.py，run_cli_loop 自动展开为 <referenced_files> 快照，
   大模型在首轮直接获取源码完成分析并输出回答，完全省去调用 read 工具的额外往返轮次。
2. Scenario 2 (Turnkey MCP auto-discovery):
   工作区配置 .mcp.json，CodingAgent 启动时自动发现并连接 MCP 服务，
   外部工具动态挂载到 registry 中并被大模型正常调用执行，
   终端交互退出时触发 close_mcp 优雅释放连接与子进程。
3. Scenario 3 (Combined Multi-Turn Flow):
   同一会话中混合进行 @ 引用源码分析与 MCP 外部工具调用，检验协同工作无冲突。
4. Scenario 4 (Graceful Non-Existent Reference & Missing MCP):
   引用不存在的文件或缺失 .mcp.json 时，终端 REPL 保持稳健降级，不发生崩溃。
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from rich.console import Console

from my_agent_core.tools import Tool, ToolResult
from my_agent_llm.models import Response, StreamChunk, ToolCall
from my_agent_tui.cli import run_cli_loop
from my_coding_agent import CodingAgent

pytestmark = [pytest.mark.anyio]


class ScriptedCliLLM:
    """按轮次返回预置响应的测试替身，模拟大模型多轮推理、思考过程和工具调用。"""

    def __init__(self, turns: list[dict[str, Any]], summary_content: str = "已总结历史对话"):
        self.turns = list(turns)
        self.idx = 0
        self.summary_content = summary_content
        self.recorded_messages: list[list[Any]] = []

    def _get_turn_payload(self) -> dict[str, Any]:
        if self.idx < len(self.turns):
            payload = self.turns[self.idx]
            self.idx += 1
            return payload
        return {"content": "默认回复完成。", "tool_calls": None}

    async def achat(self, messages, tools=None, **kwargs) -> Response:
        """用于 L4 上下文压缩摘要。"""
        self.recorded_messages.append(list(messages))
        return Response(content=self.summary_content, model="fake-cli-e2e")

    async def achat_stream(self, messages, tools=None, **kwargs):
        """用于流式交互生成。"""
        self.recorded_messages.append(list(messages))
        payload = self._get_turn_payload()

        # 1. 模拟思考链输出
        if "reasoning_content" in payload:
            yield StreamChunk(
                content="",
                metadata={"reasoning_content": payload["reasoning_content"]},
            )

        # 2. 模拟增量内容与工具调用
        yield StreamChunk(
            content=payload.get("content", ""),
            tool_calls=payload.get("tool_calls"),
            finish_reason="stop" if not payload.get("tool_calls") else "tool_calls",
        )


async def test_scenario_1_file_reference_one_turn_analysis(tmp_path: Path):
    """Scenario 1: @file 引用首轮直达分析。

    验证：
    1. 用户输入带 @src/calculator.py 的提问；
    2. run_cli_loop 自动展开为 <referenced_files> 包含 calculator.py 代码块；
    3. 大模型在 Turn 1 直接感知代码并作答；
    4. 全程未触发 read 工具调用，1 轮完成任务。
    """
    workspace = tmp_path / "workspace_s1"
    workspace.mkdir(parents=True, exist_ok=True)
    src_dir = workspace / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    calc_file = src_dir / "calculator.py"
    calc_code = (
        "class Calculator:\n"
        "    def add(self, a: int, b: int) -> int:\n"
        "        return a + b\n\n"
        "    def multiply(self, a: int, b: int) -> int:\n"
        "        return a * b\n"
    )
    calc_file.write_text(calc_code, encoding="utf-8")

    turns = [
        {
            "reasoning_content": "分析用户提示词中已注入的 @src/calculator.py 源码快照...",
            "content": "Calculator 类定义了两个核心方法：add 用于两数相加，multiply 用于两数相乘。",
            "tool_calls": None,
        }
    ]
    fake_llm = ScriptedCliLLM(turns=turns)
    session_file = workspace / "session.jsonl"

    agent = CodingAgent(
        workspace=workspace,
        llm=fake_llm,
        session=session_file,
    )

    mock_prompt_session = MagicMock()
    mock_prompt_session.prompt_async = AsyncMock(
        side_effect=[
            "请分析 @src/calculator.py 中的核心方法和功能",
            "/exit",
        ]
    )

    console = Console(file=io.StringIO(), force_terminal=True, record=True, width=120)

    # 执行 CLI 主交互循环
    await run_cli_loop(agent, console, prompt_session=mock_prompt_session)

    out = console.export_text()

    # 1. 验证仅发起 1 次大模型交互生成（首轮即得出结论，无额外工具往返）
    assert len(fake_llm.recorded_messages) == 1

    # 2. 验证大模型接收到的第一轮 prompt 中已完整嵌入 <referenced_files> 结构与 calculator.py 源码
    first_call_msgs = fake_llm.recorded_messages[0]
    user_msgs = [m for m in first_call_msgs if getattr(m, "role", "") == "user"]
    assert len(user_msgs) == 1
    user_prompt = user_msgs[0].content

    assert "请分析 @src/calculator.py 中的核心方法和功能" in user_prompt
    assert "<referenced_files>" in user_prompt
    assert '<referenced_file path="src/calculator.py">' in user_prompt
    assert "class Calculator:" in user_prompt
    assert "def add(self, a: int, b: int) -> int:" in user_prompt
    assert "def multiply(self, a: int, b: int) -> int:" in user_prompt
    assert "</referenced_file>" in user_prompt
    assert "</referenced_files>" in user_prompt

    # 3. 验证未调用 read 工具（控制台输出中绝无 [read] 标记）
    assert "[read]" not in out
    assert "✓ OK" not in out

    # 4. 验证控制台正确输出了思考过程与最终分析内容
    assert "思考过程" in out
    assert "源码快照" in out
    assert "Calculator 类定义了两个核心方法" in out
    assert "add 用于两数相加，multiply 用于两数相乘" in out


async def test_scenario_2_turnkey_mcp_discovery_and_execution(tmp_path: Path):
    """Scenario 2: 工作区 .mcp.json 即插即用自发现与外部工具调用。

    验证：
    1. 工作区配置 .mcp.json；
    2. CodingAgent 触发交互时自动发现并连接 MCP 服务；
    3. MCP 工具成功装配到 Agent ToolRegistry；
    4. 大模型下发工具调用指令并获得外部执行结果；
    5. REPL 退出时触发 close_mcp 优雅回收 MCP 连接与反注册工具。
    """
    workspace = tmp_path / "workspace_s2"
    workspace.mkdir(parents=True, exist_ok=True)
    mcp_config_file = workspace / ".mcp.json"
    mcp_config = {
        "mcpServers": {
            "math_service": {
                "command": "python",
                "args": ["-m", "mock_math_service"],
            }
        }
    }
    mcp_config_file.write_text(json.dumps(mcp_config), encoding="utf-8")

    def mock_mcp_eval(expression: str) -> ToolResult:
        return ToolResult(ok=True, data=f"Evaluated result: {expression} = 42")

    mcp_tool = Tool(
        func=mock_mcp_eval,
        name="mcp_calculate",
        description="External MCP calculator service",
    )
    setattr(mcp_tool, "is_mcp", True)

    turns = [
        {
            "reasoning_content": "用户需要计算表达式，调用已挂载的 MCP 工具 mcp_calculate...",
            "content": "",
            "tool_calls": [
                ToolCall(
                    id="call_mcp_calc_1",
                    name="mcp_calculate",
                    args={"expression": "6 * 7"},
                )
            ],
        },
        {
            "reasoning_content": "MCP 计算服务返回了 42，组织最终回复解答...",
            "content": "通过外部 MCP 服务计算，6 * 7 的结果是 42。",
            "tool_calls": None,
        },
    ]
    fake_llm = ScriptedCliLLM(turns=turns)
    session_file = workspace / "session.jsonl"

    with (
        patch(
            "my_coding_agent.mcp.MCPClientManager.connect_all",
            new_callable=AsyncMock,
        ) as mock_connect,
        patch(
            "my_coding_agent.mcp.MCPClientManager.get_all_tools",
            return_value=[mcp_tool],
        ),
        patch(
            "my_coding_agent.mcp.MCPClientManager.close_all",
            new_callable=AsyncMock,
        ) as mock_close,
    ):
        agent = CodingAgent(
            workspace=workspace,
            llm=fake_llm,
            session=session_file,
            auto_load_mcp=True,
        )

        mock_prompt_session = MagicMock()
        mock_prompt_session.prompt_async = AsyncMock(
            side_effect=[
                "请使用 MCP 计算器计算 6 * 7",
                "/exit",
            ]
        )

        console = Console(file=io.StringIO(), force_terminal=True, record=True, width=120)

        # 运行交互 REPL
        await run_cli_loop(agent, console, prompt_session=mock_prompt_session)

        # 1. 验证 MCPClientManager.connect_all 被自动触发
        mock_connect.assert_awaited_once()

        # 2. 验证 MCPClientManager.close_all 在退出交互时被优雅调用
        mock_close.assert_awaited_once()

        # 3. 验证退出后 agent.mcp_manager 已被重置为 None
        assert agent.mcp_manager is None

        # 4. 验证退出后 MCP 工具已被反注册，避免陈旧工具残留
        assert "mcp_calculate" not in agent.agent.registry._tools

    out = console.export_text()

    # 5. 验证事件渲染器捕获了 MCP 工具的调用与执行成功输出
    assert "⚙️" in out
    assert "[mcp_calculate]" in out
    assert "✓ OK" in out
    assert "通过外部 MCP 服务计算，6 * 7 的结果是 42。" in out


async def test_scenario_3_combined_file_reference_and_mcp_flow(tmp_path: Path):
    """Scenario 3: 混合场景多轮交互 (@file 源码快照与 MCP 工具协同)。

    验证：
    1. 第一轮提问包含 @src/logic.py，直接利用源码快照回答；
    2. 第二轮提问请求外部 MCP 工具进行校验计算；
    3. 同一会话生命周期内 MCP 状态持久且随 exit 正常回收。
    """
    workspace = tmp_path / "workspace_s3"
    workspace.mkdir(parents=True, exist_ok=True)
    src_dir = workspace / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    logic_file = src_dir / "logic.py"
    logic_file.write_text("def solve_formula(n: int) -> int:\n    return n ** 2 + 1\n", encoding="utf-8")

    mcp_config_file = workspace / ".mcp.json"
    mcp_config = {
        "mcpServers": {
            "verifier_service": {
                "command": "python",
                "args": ["-m", "verifier"],
            }
        }
    }
    mcp_config_file.write_text(json.dumps(mcp_config), encoding="utf-8")

    def mock_verify(formula_val: int) -> ToolResult:
        return ToolResult(ok=True, data=f"Verified: {formula_val} is prime")

    verify_tool = Tool(
        func=mock_verify,
        name="verify_prime",
        description="Verify if a number is prime via MCP",
    )
    setattr(verify_tool, "is_mcp", True)

    turns = [
        # Turn 1: 解析 @src/logic.py 源码（无需工具调用）
        {
            "reasoning_content": "查看用户带有的 @src/logic.py 源码快照...",
            "content": "solve_formula 函数计算 n 的平方加 1。当 n=4 时，结果为 17。",
            "tool_calls": None,
        },
        # Turn 2: 调用 verify_prime 工具核对 17
        {
            "reasoning_content": "调用 verify_prime 验证 17 是否为质数...",
            "content": "",
            "tool_calls": [
                ToolCall(
                    id="call_verify_1",
                    name="verify_prime",
                    args={"formula_val": 17},
                )
            ],
        },
        # Turn 2 completion
        {
            "reasoning_content": "收到素数校验确认...",
            "content": "MCP 验证服务确认 17 为质数，公式计算结果有效。",
            "tool_calls": None,
        },
    ]
    fake_llm = ScriptedCliLLM(turns=turns)
    session_file = workspace / "session.jsonl"

    with (
        patch("my_coding_agent.mcp.MCPClientManager.connect_all", new_callable=AsyncMock) as mock_connect,
        patch("my_coding_agent.mcp.MCPClientManager.get_all_tools", return_value=[verify_tool]),
        patch("my_coding_agent.mcp.MCPClientManager.close_all", new_callable=AsyncMock) as mock_close,
    ):
        agent = CodingAgent(
            workspace=workspace,
            llm=fake_llm,
            session=session_file,
            auto_load_mcp=True,
        )

        mock_prompt_session = MagicMock()
        mock_prompt_session.prompt_async = AsyncMock(
            side_effect=[
                "请根据 @src/logic.py 计算 n=4 时的取值",
                "请调用 MCP 质数校验服务验证此数值",
                "/exit",
            ]
        )

        console = Console(file=io.StringIO(), force_terminal=True, record=True, width=120)

        await run_cli_loop(agent, console, prompt_session=mock_prompt_session)

        mock_connect.assert_awaited_once()
        mock_close.assert_awaited_once()

    out = console.export_text()
    assert "solve_formula 函数计算 n 的平方加 1" in out
    assert "[verify_prime]" in out
    assert "MCP 验证服务确认 17 为质数" in out


async def test_scenario_4_graceful_missing_file_and_no_mcp(tmp_path: Path):
    """Scenario 4: 容错兜底验证 (引用不存在的文件且工作区无 .mcp.json)。

    验证：
    1. 引用不存在的文件 @nonexistent.py 时保留原字符串不崩溃；
    2. 无 .mcp.json 时静默跳过；
    3. 退出时 close_mcp 幂等执行无异常。
    """
    workspace = tmp_path / "workspace_s4"
    workspace.mkdir(parents=True, exist_ok=True)

    turns = [
        {
            "reasoning_content": "未发现该文件快照，正常作答提示用户...",
            "content": "未找到指定的文件 nonexistent.py，请检查路径。",
            "tool_calls": None,
        }
    ]
    fake_llm = ScriptedCliLLM(turns=turns)
    session_file = workspace / "session.jsonl"

    agent = CodingAgent(
        workspace=workspace,
        llm=fake_llm,
        session=session_file,
        auto_load_mcp=True,
    )

    mock_prompt_session = MagicMock()
    mock_prompt_session.prompt_async = AsyncMock(
        side_effect=[
            "请查看 @nonexistent.py",
            "/exit",
        ]
    )

    console = Console(file=io.StringIO(), force_terminal=True, record=True, width=120)

    await run_cli_loop(agent, console, prompt_session=mock_prompt_session)

    # 验证第一轮大模型收到的 prompt 包含原本的 @nonexistent.py，无 <referenced_files>
    assert len(fake_llm.recorded_messages) == 1
    user_msgs = [m for m in fake_llm.recorded_messages[0] if getattr(m, "role", "") == "user"]
    assert len(user_msgs) == 1
    assert "@nonexistent.py" in user_msgs[0].content
    assert "<referenced_files>" not in user_msgs[0].content

    # 验证未报错且输出了回复
    out = console.export_text()
    assert "未找到指定的文件 nonexistent.py" in out
