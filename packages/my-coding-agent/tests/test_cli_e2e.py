"""端到端 CLI 模拟测试与全套回归 (test_cli_e2e.py)。

全面验证：
1. 完整 CLI 交互主线：/help -> 正常对话提问(工具调用与流式渲染) -> /session -> /undo -> /compact -> /exit；
2. 多轮对话与 edit 工具 Diff 代码着色渲染、/tasks 看板、/mcp 工具检查及 /quit 退出；
3. 异常韧性与恢复：空输入、未知命令、自定义故障命令沙箱、生成轮次 CancelledError 中断、运行异常以及 EOF/SIGINT 退出；
4. 顶层公共模块导出契约验证。
"""

from __future__ import annotations

import asyncio
import io
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from rich.console import Console

from my_agent_core.session import Session
from my_agent_core.task_store import TaskStore
from my_agent_core.tools import Tool, ToolResult
from my_agent_llm.models import Response, StreamChunk, ToolCall

import my_coding_agent
from my_coding_agent import (
    CodingAgent,
    CommandDispatcher,
    EventRenderer,
    main,
)
from my_coding_agent.cli import run_cli_loop

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


async def test_cli_e2e_canonical_flow(tmp_path: Path):
    """验证主线端到端交互：

    /help -> 正常对话提问 (写文件) -> /session -> /undo -> /compact -> /exit
    检验 CommandDispatcher 与 EventRenderer 协同无卡死、零未捕获异常。
    """
    console = Console(file=io.StringIO(), force_terminal=True, record=True, width=120)

    # 构造两轮响应：第一轮调用 write 工具，第二轮输出助手正文
    turns = [
        {
            "reasoning_content": "正在思考如何为用户生成 hello.py 脚本...",
            "content": "",
            "tool_calls": [
                ToolCall(
                    id="call_write_1",
                    name="write",
                    args={"path": "hello.py", "content": "print('hello from cli e2e')\n"},
                )
            ],
        },
        {
            "content": "已成功为您创建 hello.py 文件！",
            "tool_calls": None,
        },
    ]
    fake_llm = ScriptedCliLLM(turns=turns, summary_content="历史摘要：创建了 hello.py 文件")
    session_file = tmp_path / "e2e_session.jsonl"
    session = Session(path=session_file)

    agent = CodingAgent(
        workspace=tmp_path,
        llm=fake_llm,
        session=session,
    )

    # 模拟用户顺序输入
    mock_prompt_session = MagicMock()
    mock_prompt_session.prompt_async = AsyncMock(
        side_effect=[
            "/help",
            "请帮我编写一个 hello.py 文件并打印 hello from cli e2e",
            "/session",
            "/undo",
            "/compact",
            "/exit",
        ]
    )

    # 执行完整的交互 REPL 主循环
    await run_cli_loop(agent, console, prompt_session=mock_prompt_session)

    out = console.export_text()

    # 1. 验证启动横幅
    assert "my-coding-agent 终端编程助手" in out
    assert str(tmp_path) in out

    # 2. 验证 /help 命令分发及命令列表输出
    assert "my-coding-agent 可用命令" in out
    assert "/help" in out
    assert "/undo" in out
    assert "/compact" in out
    assert "/session" in out
    assert "/exit" in out

    # 3. 验证正常提问及 EventRenderer 事件流渲染
    # 思考链
    assert "思考过程" in out
    assert "正在思考如何为用户生成 hello.py 脚本" in out
    # 工具调用徽标与成功状态
    assert "⚙️" in out
    assert "[write]" in out
    assert "✓ OK" in out
    # 助手最终文本与单轮耗时统计
    assert "已成功为您创建 hello.py 文件！" in out
    assert "回合: 2" in out

    # 验证工具真实写入工作区文件
    created_file = tmp_path / "hello.py"
    assert created_file.is_file()
    assert "hello from cli e2e" in created_file.read_text(encoding="utf-8")

    # 4. 验证 /session 命令输出
    assert "会话 ID:" in out
    assert "持久化路径:" in out
    assert str(session_file) in out
    assert "消息总节点:" in out

    # 5. 验证 /undo 命令成功回退上一轮对话
    assert "已成功回退" in out
    assert "上一轮对话已安全撤销" in out

    # 6. 验证 /compact 命令执行上下文压缩
    assert "智能上下文压缩" in out
    assert "上下文压缩完成" in out

    # 7. 验证 /exit 命令优雅终止
    assert "正在退出... 再见！" in out


async def test_cli_e2e_multiturn_edit_diff_tasks_and_mcp(tmp_path: Path):
    """验证多轮编辑、彩色 Diff 渲染、任务看板、MCP 检测及退出。"""
    console = Console(file=io.StringIO(), force_terminal=True, record=True, width=120)

    # 准备 TaskStore
    task_store = TaskStore(workspace=tmp_path)
    await task_store.create(subject="实现加法计算器", description="编写加法函数并修复 bug")

    # 准备工作区初始文件
    calc_py = tmp_path / "calc.py"
    calc_py.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")

    # 模拟两轮交互：
    # Turn 1: 提问修复 calc.py -> 触发 edit 工具
    # Turn 2: 编辑完成确认
    turns = [
        {
            "reasoning_content": "分析 calc.py，发现减法错误，准备应用外科手术式修改...",
            "content": "",
            "tool_calls": [
                ToolCall(
                    id="call_edit_1",
                    name="edit",
                    args={
                        "path": "calc.py",
                        "edits": [
                            {
                                "oldText": "    return a - b",
                                "newText": "    return a + b",
                            }
                        ],
                    },
                )
            ],
        },
        {
            "content": "已修复 calc.py 中的减号错误。",
            "tool_calls": None,
        },
    ]

    fake_llm = ScriptedCliLLM(turns=turns)
    session = Session(path=tmp_path / "session_diff.jsonl")

    agent = CodingAgent(
        workspace=tmp_path,
        llm=fake_llm,
        session=session,
        task_store=task_store,
    )

    # 注册一个 mock MCP 工具
    mcp_tool = Tool(
        func=lambda: ToolResult(ok=True, data="database schema"),
        name="db_schema_inspector",
        description="Query PostgreSQL database schema",
    )
    setattr(mcp_tool, "is_mcp", True)
    agent.agent.registry.register(mcp_tool)

    # 模拟用户交互输入
    mock_prompt_session = MagicMock()
    mock_prompt_session.prompt_async = AsyncMock(
        side_effect=[
            "请修复 calc.py 中的 bug",
            "/tasks",
            "/mcp",
            "/quit",
        ]
    )

    await run_cli_loop(agent, console, prompt_session=mock_prompt_session)

    out = console.export_text()

    # 验证 edit 工具调用与 Diff 语法渲染
    assert "⚙️" in out
    assert "[edit]" in out
    assert "✓ OK" in out
    assert "--- a/calc.py" in out or "calc.py" in out
    assert "-    return a - b" in out
    assert "+    return a + b" in out
    assert "已修复 calc.py 中的减号错误。" in out

    # 验证 calc.py 文件内容已被实际修复
    assert "return a + b" in calc_py.read_text(encoding="utf-8")

    # 验证 /tasks 输出看板
    assert "TaskStore 任务看板" in out
    assert "实现加法计算器" in out

    # 验证 /mcp 输出已挂载工具
    assert "已挂载 MCP 工具数: 1" in out
    assert "db_schema_inspector" in out

    # 验证 /quit 正常退出
    assert "正在退出... 再见！" in out


async def test_cli_e2e_resilience_and_error_recovery(tmp_path: Path):
    """验证 CLI 运行过程中的容错与异常恢复韧性：

    - 连续空行与纯空格输入被静默跳过；
    - 未知斜杠命令给出提示且不影响后续交互；
    - 故障命令处理器被沙箱拦截，不造成会话崩溃；
    - 模型流式生成发生 CancelledError 被妥善捕获；
    - 模型流式生成发生通用异常被捕获，下一轮输入依然可用；
    - 最终通过 EOF/Ctrl+D 优雅结束。
    """
    console = Console(file=io.StringIO(), force_terminal=True, record=True, width=120)

    class RecoveringLLM:
        async def achat(self, *a, **kw):
            return Response(content="ok", model="fake")

        async def achat_stream(self, *a, **kw):
            yield StreamChunk(content="恢复正常通信。")

    agent = CodingAgent(workspace=tmp_path, llm=RecoveringLLM(), session=tmp_path / "resilience.jsonl")

    # 注入一个故意的故障命令
    dispatcher = CommandDispatcher(agent)

    def faulty_cmd(ctx):
        raise ValueError("Simulated command error")

    dispatcher.register("bomb", faulty_cmd, "Intentional failure command")

    original_run_stream = agent.run_stream
    turn_counter = 0

    async def simulating_stream(user_input: str):
        nonlocal turn_counter
        turn_counter += 1
        if turn_counter == 1:
            raise asyncio.CancelledError()
            yield
        elif turn_counter == 2:
            raise RuntimeError("Remote server closed connection")
            yield
        else:
            async for ev in original_run_stream(user_input):
                yield ev

    agent.run_stream = simulating_stream  # type: ignore

    mock_prompt_session = MagicMock()
    mock_prompt_session.prompt_async = AsyncMock(
        side_effect=[
            "",  # 空输入
            "    ",  # 纯空格
            "/nonexistent_cmd",  # 未知命令
            "/bomb",  # 抛出异常的命令
            "测试取消生成",  # Step 1: 触发 CancelledError
            "测试连接中断异常",  # Step 2: 触发 RuntimeError
            "正常提问测试自愈",  # Step 3: 恢复正常
            EOFError(),  # 模拟 Ctrl+D 退出
        ]
    )

    await run_cli_loop(agent, console, prompt_session=mock_prompt_session, dispatcher=dispatcher)

    out = console.export_text()

    # 验证未知命令提示
    assert "未知命令: /nonexistent_cmd" in out

    # 验证故障命令处理器沙箱保护提示
    assert "执行命令 /bomb 失败: Simulated command error" in out

    # 验证 CancelledError 处理提示
    assert "已取消当前生成轮次" in out

    # 验证通用异常捕获提示
    assert "运行出错: Remote server closed connection" in out

    # 验证第三轮自愈并正常输出文本
    assert "恢复正常通信。" in out

    # 验证 EOF 退出提示
    assert "再见！" in out


def test_top_level_package_exports():
    """验证 my_coding_agent 顶层导出符合公开规范契约。"""
    # 导出符号存在性与类型可调用性验证
    assert hasattr(my_coding_agent, "CommandDispatcher")
    assert callable(my_coding_agent.CommandDispatcher)

    assert hasattr(my_coding_agent, "EventRenderer")
    assert callable(my_coding_agent.EventRenderer)

    assert hasattr(my_coding_agent, "main")
    assert callable(my_coding_agent.main)

    assert hasattr(my_coding_agent, "CodingAgent")
    assert callable(my_coding_agent.CodingAgent)

    # 顶层 __all__ 契约完整性
    all_exports = set(my_coding_agent.__all__)
    expected_core_exports = {
        "CodingAgent",
        "CommandDispatcher",
        "EventRenderer",
        "main",
        "build_coding_tools",
        "build_default_coding_prompt",
        "FileMutationQueue",
        "MCPServerConfig",
        "MCPConnection",
        "MCPClientManager",
    }
    assert expected_core_exports.issubset(all_exports)

    # 验证直接解构导出
    assert CommandDispatcher is my_coding_agent.CommandDispatcher
    assert EventRenderer is my_coding_agent.EventRenderer
    assert main is my_coding_agent.main
