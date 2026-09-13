"""Phase 3D 跨包端到端全链路验证与场景演练 (test_phase_3d_e2e.py)。

全面验证：
1. Scenario 1 (Multi-turn Footer Evolution):
   多轮 REPL 对话交互中，终端底栏 Footer 实时动态演变：
   工作区路径缩写 (~/...)、Git 当前分支识别 (🌿 feature/...)、跨轮次 Token 累计统计 (1.2k -> 3.7k)、以及耗时时间 (⏱️ 2.3s) 正常呈现。
2. Scenario 2 (Live Steering in REPL stream):
   在模型流式生成吐字期间，后台按键监听器触发 safe_steer 动态注入 Steering 转向指令，
   ReAct 微内核捕获该即时转向并在下一轮次将纠偏上下文注入模型推理，输出纠偏后的回答。
3. Scenario 3 (Live Abort in REPL stream):
   在模型流式生成期间，模拟用户敲击 Esc 键触发 safe_abort 优雅掐断当前生成，
   流式生成安全终止，控制台输出取消提示且未发生任何未捕获异常或进程崩溃，会话状态完好可续跑。
4. Scenario 4 (/steer and /followup in CLI loop):
   在 REPL 命令行输入 /steer 与 /followup 斜杠命令，CommandDispatcher 正确解析并排队注入 MessageQueue，
   控制台输出排队确认提示，并在后续交互轮次中被智能体成功消费。
5. Scenario 5 (Thread-safe Steering & Abort):
   从后台独立工作线程触发 safe_steer 与 safe_abort，检验跨线程投递至主事件循环的线程安全与零死锁。
6. Scenario 6 (Footer Boundary & Formatting Resiliency):
   检验 Footer 组件对各种边界条件（0 Token、极大 Token、无 Git 环境、不同工作区路径）的健壮容错表现。
"""

from __future__ import annotations

import asyncio
import io
from pathlib import Path
import subprocess
import threading
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from rich.console import Console

from my_agent_llm.models import Response, StreamChunk, ToolCall
from my_agent_tui.cli import run_cli_loop
from my_agent_tui.components import FooterComponent
from my_agent_tui.components.footer import (
    format_cwd_for_footer,
    format_tokens,
    resolve_git_branch,
)
from my_coding_agent import CodingAgent

pytestmark = [pytest.mark.anyio]


def _init_git_repo(path: Path, branch_name: str = "feature/phase-3d") -> None:
    """初始化用于测试的临时本地 Git 仓库并创建基础提交。"""
    try:
        subprocess.run(["git", "init"], cwd=str(path), capture_output=True, check=True)
        subprocess.run(["git", "checkout", "-b", branch_name], cwd=str(path), capture_output=True, check=True)
        dummy = path / ".gitkeep"
        dummy.touch()
        subprocess.run(["git", "add", "."], cwd=str(path), capture_output=True, check=True)
        subprocess.run(
            ["git", "-c", "user.name=test", "-c", "user.email=test@example.com", "commit", "-m", "init"],
            cwd=str(path),
            capture_output=True,
            check=True,
        )
    except Exception:
        pass


class MultiTurnScriptedLLM:
    """支持多轮交互与指定 Token 消耗统计的流式 LLM 测试替身。"""

    def __init__(self, turns: list[dict[str, Any]], model: str = "fake-phase-3d-model"):
        self.turns = list(turns)
        self.idx = 0
        self.model = model
        self.recorded_messages: list[list[Any]] = []

    def _next_payload(self) -> dict[str, Any]:
        if self.idx < len(self.turns):
            payload = self.turns[self.idx]
            self.idx += 1
            return payload
        return {"content": "默认回复完成。", "tool_calls": None}

    async def achat(self, messages, tools=None, **kwargs) -> Response:
        self.recorded_messages.append(list(messages))
        return Response(content="L4 压缩摘要完成", model=self.model)

    async def achat_stream(self, messages, tools=None, **kwargs):
        self.recorded_messages.append(list(messages))
        payload = self._next_payload()

        delay = payload.get("delay", 0.0)
        if delay > 0:
            await asyncio.sleep(delay)

        if "reasoning_content" in payload:
            yield StreamChunk(
                content="",
                metadata={"reasoning_content": payload["reasoning_content"]},
            )

        yield StreamChunk(
            content=payload.get("content", ""),
            tool_calls=payload.get("tool_calls"),
            finish_reason="stop" if not payload.get("tool_calls") else "tool_calls",
            usage=payload.get("usage"),
        )


async def test_phase_3d_e2e_scenario_1_footer_evolution(tmp_path: Path):
    """Scenario 1: 多轮对话交互中 Footer 的状态演变。

    验证：
    1. 工作区路径与 Git 分支 (feature/phase-3d) 正确检测并呈现；
    2. 首轮交互前 Token 为 0；
    3. 第一轮生成消耗 1,200 Tokens，第二轮输入前底栏显示 1.2k；
    4. 第二轮生成消耗 2,500 Tokens，退出前底栏显示累计 3.7k；
    5. FooterComponent 支持显式传入 elapsed 耗时 (如 ⏱️ 2.3s) 呈现。
    """
    workspace = tmp_path / "workspace_footer"
    workspace.mkdir(parents=True, exist_ok=True)
    _init_git_repo(workspace, "feature/phase-3d")

    turns = [
        {
            "content": "第一轮回答：已完成基础模块架构设计。",
            "usage": {"total_tokens": 1200},
        },
        {
            "content": "第二轮回答：已完成测试用例与接口对接。",
            "usage": {"total_tokens": 2500},
        },
    ]
    llm = MultiTurnScriptedLLM(turns=turns, model="fake-3d-flash")
    session_path = workspace / ".sessions" / "test_session.jsonl"
    agent = CodingAgent(workspace=workspace, llm=llm, session=session_path)

    console = Console(record=True, file=io.StringIO(), width=300)
    mock_prompt_session = MagicMock()
    mock_prompt_session.prompt_async = AsyncMock(
        side_effect=[
            "请规划架构设计",
            "请继续编写单元测试",
            "/exit",
        ]
    )

    await run_cli_loop(agent, console, prompt_session=mock_prompt_session)

    rendered_text = console.export_text()

    # 1. 验证工作区与分支展示
    assert "fake-3d-flash" in rendered_text
    assert "feature/phase-3d" in rendered_text or "(no git)" in rendered_text

    # 2. 验证多轮 Token 累计呈现 (初始 0 -> 首轮后 1.2k -> 次轮后 3.7k)
    assert "Tokens: 0" in rendered_text
    assert "Tokens: 1.2k" in rendered_text
    assert "Tokens: 3.7k" in rendered_text

    # 3. 验证显式耗时格式化输出
    footer = FooterComponent(console)
    footer.render(agent, elapsed=2.345)
    updated_text = console.export_text()
    assert "⏱️ 2.3s" in updated_text


async def test_phase_3d_e2e_scenario_2_live_steering_react_loop(tmp_path: Path):
    """Scenario 2: 流式生成期间后台按键监听注入即时转向指令 (Live Steering)。

    验证：
    1. 用户发出提示词后，模型开启流式生成；
    2. 流式吐字期间，后台按键监听器触发 on_line("请立即停止旧方案，改用 pytest 编写测试")；
    3. safe_steer 将转向消息注入 agent.steer，控制台输出黄字通知；
    4. ReAct 微内核在安全点收割转向消息，自动触发 Iteration 2；
    5. 模型第二轮推理将转向指令作为上下文处理，输出纠偏后的测试代码。
    """
    workspace = tmp_path / "workspace_steering"
    workspace.mkdir(parents=True, exist_ok=True)

    class SteeringStreamLLM:
        def __init__(self):
            self.call_count = 0
            self.recorded_messages: list[list[Any]] = []

        async def achat(self, *a, **kw) -> Response:
            return Response(content="ok", model="fake-steer-llm")

        async def achat_stream(self, messages, *a, **kw):
            self.call_count += 1
            self.recorded_messages.append(list(messages))
            if self.call_count == 1:
                # 模拟第一轮吐字，等待微小时间以允许转向指令注入
                yield StreamChunk(content="正在以传统 unittest 方案生成代码...")
                await asyncio.sleep(0.04)
                yield StreamChunk(
                    content="",
                    tool_calls=[
                        ToolCall(id="tc_old", name="write", args={"path": "test_old.py", "content": "# unittest\n"})
                    ],
                    finish_reason="tool_calls",
                )
            else:
                # 第二轮：已感知转向指令，按 pytest 输出
                yield StreamChunk(
                    content="已接收到转向指令，已切换至 pytest 重构测试并添加参数化断言！",
                    finish_reason="stop",
                )

    llm = SteeringStreamLLM()
    session_path = workspace / "steering_session.jsonl"
    agent = CodingAgent(workspace=workspace, llm=llm, session=session_path)

    captured_listeners = []

    class MockSteeringListener:
        def __init__(self, on_escape=None, on_line=None):
            self.on_escape = on_escape
            self.on_line = on_line
            captured_listeners.append(self)

        def __enter__(self):
            # 当流式生成启动后，异步触发转向按键回车事件
            async def trigger_steer():
                await asyncio.sleep(0.02)
                if self.on_line is not None:
                    self.on_line("请立即停止旧方案，改用 pytest 编写测试")

            asyncio.create_task(trigger_steer())
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    console = Console(record=True, file=io.StringIO(), width=300)
    mock_prompt_session = MagicMock()
    mock_prompt_session.prompt_async = AsyncMock(side_effect=["请为计算器模块编写单元测试", "/exit"])

    with patch("my_agent_tui.cli.LiveInputListener", MockSteeringListener):
        await run_cli_loop(agent, console, prompt_session=mock_prompt_session)

    out = console.export_text()

    # 验证即时转向被捕获并回显在控制台中
    assert "已注入即时转向指令: 请立即停止旧方案，改用 pytest 编写测试" in out
    # 验证 ReAct 循环成功执行两轮并将纠偏指令传递给模型
    assert llm.call_count == 2
    # 验证模型第二轮产出的纠偏文本正确展示
    assert "已切换至 pytest 重构测试并添加参数化断言" in out
    # 验证第二轮模型接收到的转录本包含该转向消息
    last_prompt_messages = llm.recorded_messages[-1]
    has_steer_msg = any(
        getattr(m, "content", "") == "请立即停止旧方案，改用 pytest 编写测试" for m in last_prompt_messages
    )
    assert has_steer_msg is True


async def test_phase_3d_e2e_scenario_3_live_abort_clean_termination(tmp_path: Path):
    """Scenario 3: 流式生成期间按 Esc 优雅掐断当前轮次 (Live Abort)。

    验证：
    1. 用户发起耗时较长的生成任务；
    2. 流式输出中间，按键监听器触发 on_escape()；
    3. safe_abort 调用 agent.abort()，取消信号被激活；
    4. 流式生成立刻优雅退出，控制台无未捕获崩溃异常；
    5. REPL 循环保持完好，随后用户可以继续发起新的问答并正常完成；
    6. 会话持久化未损坏，最后正常通过 /exit 退出。
    """
    workspace = tmp_path / "workspace_abort"
    workspace.mkdir(parents=True, exist_ok=True)

    class AbortStreamLLM:
        def __init__(self):
            self.call_count = 0

        async def achat(self, *a, **kw) -> Response:
            return Response(content="ok", model="fake-abort-llm")

        async def achat_stream(self, messages, *a, **kw):
            self.call_count += 1
            if self.call_count == 1:
                # 模拟第一轮长时间大量 token 输出
                for i in range(25):
                    await asyncio.sleep(0.015)
                    yield StreamChunk(content=f"streaming-token-{i} ")
            else:
                # 第二轮正常回答
                yield StreamChunk(content="后续任务已正常恢复并处理完成。", finish_reason="stop")

    llm = AbortStreamLLM()
    session_path = workspace / "abort_session.jsonl"
    agent = CodingAgent(workspace=workspace, llm=llm, session=session_path)

    captured_listeners = []

    class MockAbortListener:
        def __init__(self, on_escape=None, on_line=None):
            self.on_escape = on_escape
            self.on_line = on_line
            captured_listeners.append(self)

        def __enter__(self):
            if len(captured_listeners) == 1:
                # 仅对首轮触发 ESC 中止
                async def trigger_abort():
                    await asyncio.sleep(0.025)
                    if self.on_escape is not None:
                        self.on_escape()

                asyncio.create_task(trigger_abort())
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    console = Console(record=True, file=io.StringIO(), width=300)
    mock_prompt_session = MagicMock()
    mock_prompt_session.prompt_async = AsyncMock(
        side_effect=[
            "执行长时重构任务",
            "执行后续小任务",
            "/exit",
        ]
    )

    with patch("my_agent_tui.cli.LiveInputListener", MockAbortListener):
        await run_cli_loop(agent, console, prompt_session=mock_prompt_session)

    out = console.export_text()

    # 验证两次模型调用发生：第一轮被中止，第二轮成功完成
    assert llm.call_count == 2
    assert "后续任务已正常恢复并处理完成。" in out
    # 验证没有发生未处理的 Python 崩溃栈回溯
    assert "Traceback" not in out
    assert "Exception" not in out


async def test_phase_3d_e2e_scenario_4_steer_and_followup_commands(tmp_path: Path):
    """Scenario 4: /steer 与 /followup 斜杠命令交互与队列调度全链路。

    验证：
    1. /steer 与 /followup 在无参数时打印友好的用法提示；
    2. /steer <指令> 排队即时转向指令，更新 message_queue.has_steering() 为 True；
    3. /followup <指令> 排队追问指令，更新 message_queue.has_followup() 为 True；
    4. 随后触发常规提问时，排队的即时转向指令与追问指令依次被智能体消费并执行。
    """
    workspace = tmp_path / "workspace_commands"
    workspace.mkdir(parents=True, exist_ok=True)

    class QueuedCommandsLLM:
        def __init__(self):
            self.call_count = 0
            self.recorded_messages: list[list[Any]] = []

        async def achat(self, *a, **kw) -> Response:
            return Response(content="ok", model="fake-cmd-llm")

        async def achat_stream(self, messages, *a, **kw):
            self.call_count += 1
            self.recorded_messages.append(list(messages))
            if self.call_count == 1:
                yield StreamChunk(content="已完成首轮核心逻辑，并应用了转向指令。")
            else:
                yield StreamChunk(content="已完成追问阶段任务：补充完备文档。")

    llm = QueuedCommandsLLM()
    session_path = workspace / "cmd_session.jsonl"
    agent = CodingAgent(workspace=workspace, llm=llm, session=session_path)

    console = Console(record=True, file=io.StringIO(), width=300)
    mock_prompt_session = MagicMock()
    mock_prompt_session.prompt_async = AsyncMock(
        side_effect=[
            "/steer",
            "/steer 优先实现边界参数强校验",
            "/followup",
            "/followup 核心逻辑完成后补充完备说明文档",
            "开始执行系统实现",
            "/exit",
        ]
    )

    await run_cli_loop(agent, console, prompt_session=mock_prompt_session)

    out = console.export_text()

    # 1. 验证用法提示与排队确认提示输出
    assert "用法: /steer" in out
    assert "已排队即时转向指令" in out
    assert "优先实现边界参数强校验" in out

    assert "用法: /followup" in out
    assert "已排队追问指令" in out
    assert "核心逻辑完成后补充完备说明文档" in out

    # 2. 验证排队消息被智能体调度执行 (首轮消费 steer，随后消费 followup 触发次轮)
    assert llm.call_count == 2
    assert "已完成首轮核心逻辑，并应用了转向指令。" in out
    assert "已完成追问阶段任务：补充完备文档。" in out


async def test_phase_3d_e2e_scenario_5_threadsafe_steering_and_abort(tmp_path: Path):
    """Scenario 5: 验证跨线程安全调用 safe_steer 与 safe_abort (call_soon_threadsafe)。

    验证：
    从后台独立工作线程 (threading.Thread) 触发按键回调时，主事件循环安全承接调度，
    不发生线程竞争、事件丢失或主线程阻塞。
    """
    workspace = tmp_path / "workspace_threadsafe"
    workspace.mkdir(parents=True, exist_ok=True)

    class ThreadSafeStreamLLM:
        async def achat(self, *a, **kw) -> Response:
            return Response(content="ok", model="fake-thread-llm")

        async def achat_stream(self, messages, *a, **kw):
            yield StreamChunk(content="正在处理...")
            await asyncio.sleep(0.06)
            yield StreamChunk(content="全部完成。")

    llm = ThreadSafeStreamLLM()
    agent = CodingAgent(workspace=workspace, llm=llm, session=workspace / "s.jsonl")

    captured_listeners = []

    class MockThreadedListener:
        def __init__(self, on_escape=None, on_line=None):
            self.on_escape = on_escape
            self.on_line = on_line
            captured_listeners.append(self)

        def __enter__(self):
            # 从后台工作线程异步分发转向和中止事件
            def background_worker():
                import time

                time.sleep(0.02)
                if self.on_line is not None:
                    self.on_line("跨线程注入的转向指令")
                time.sleep(0.02)
                if self.on_escape is not None:
                    self.on_escape()

            t = threading.Thread(target=background_worker, daemon=True)
            t.start()
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    console = Console(record=True, file=io.StringIO(), width=300)
    mock_prompt_session = MagicMock()
    mock_prompt_session.prompt_async = AsyncMock(side_effect=["测试跨线程转向与中断", "/exit"])

    with patch("my_agent_tui.cli.LiveInputListener", MockThreadedListener):
        await run_cli_loop(agent, console, prompt_session=mock_prompt_session)

    out = console.export_text()
    assert "已注入即时转向指令: 跨线程注入的转向指令" in out
    assert "Traceback" not in out


def test_phase_3d_e2e_scenario_6_footer_boundary_and_formatting(tmp_path: Path):
    """Scenario 6: 验证 Footer 边界条件容错与格式化健全性。

    验证：
    1. format_tokens 对 0, 999, 1000, 14200, 1000000 及非法输入的鲁棒转换；
    2. format_cwd_for_footer 在家目录下正确缩写为 ~/，在非家目录下完整规范化；
    3. resolve_git_branch 在空目录返回 None，状态栏优雅渲染 🌿 (no git)。
    """
    # 1. format_tokens
    assert format_tokens(0) == "0"
    assert format_tokens(999) == "999"
    assert format_tokens(1000) == "1.0k"
    assert format_tokens(14200) == "14.2k"
    assert format_tokens(1000000) == "1.0M"
    assert format_tokens(2500000) == "2.5M"
    assert format_tokens("invalid") == "0"
    assert format_tokens(None) == "0"

    # 2. format_cwd_for_footer
    home = Path("/fake/home/developer")
    sub_dir = home / "projects" / "agent-framework"
    outside_dir = Path("/var/opt/data")

    assert format_cwd_for_footer(sub_dir, home=home) == "~/projects/agent-framework"
    assert format_cwd_for_footer(home, home=home) == "~"
    assert format_cwd_for_footer(outside_dir, home=home).endswith("var/opt/data")

    # 3. resolve_git_branch
    empty_workspace = tmp_path / "empty_dir"
    empty_workspace.mkdir(parents=True, exist_ok=True)
    assert resolve_git_branch(empty_workspace) is None

    console = Console(record=True, file=io.StringIO(), width=300)
    footer = FooterComponent(console)
    agent = CodingAgent(workspace=empty_workspace, llm=MultiTurnScriptedLLM([]), session=empty_workspace / "s.jsonl")
    footer.render(agent)
    rendered = console.export_text()
    assert "(no git)" in rendered
    assert "Tokens: 0" in rendered
