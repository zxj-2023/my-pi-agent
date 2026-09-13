"""端到端权限审查门禁与词级 Diff 渲染全量测试 (test_permissions_e2e.py)。

全面覆盖：
1. 用户拒绝流程 (User denial flow)：模型尝试 write/bash -> PermissionGate 触发 ConfirmView -> 用户输入 'n' 拒绝
   -> HookResult(block=True) 拦截并注入错误信息至转录本 -> 模型优雅自愈修正且目标文件/危险操作未执行；
2. 用户放行流程 (User approval flow)：模型尝试 edit 工具 -> PermissionGate 触发 ConfirmView -> 用户输入 'y'/回车放行
   -> 磁盘文件真实原子修改 -> EventRenderer 触发 diffWords 词级高亮反色渲染 -> 任务圆满达成；
3. 安全命令白名单流程 (Safe bash bypass flow)：review 模式下 safe_bash (如 pytest / git status) 无感放行且不触发 ConfirmView；
4. 严苛审查模式 (Strict mode flow)：strict 模式下即便 read/find 等只读操作亦触发 ConfirmView 审批；
5. CLI REPL 会话模式动态切换 (/mode yolo -> /mode review -> /mode strict) 与权限闭环全流程。
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from rich.console import Console

from my_agent_core.events import (
    AgentEnd,
    Event,
    ToolExecutionEnd,
)
from my_agent_llm.models import Response, StreamChunk, ToolCall
from my_agent_tui.cli import run_cli_loop
from my_agent_tui.commands import CommandDispatcher
from my_agent_tui.components.confirm import ConfirmView
from my_agent_tui.renderer import EventRenderer
from my_coding_agent.agent import CodingAgent
from my_coding_agent.permissions import PermissionGate, PermissionRequest

pytestmark = [pytest.mark.anyio]


class ScriptedPermissionLLM:
    """按轮次返回预置响应的模型测试替身，模拟多轮推理、工具调用与基于拒绝反馈的自愈修正。"""

    def __init__(self, turns: list[dict[str, Any]]):
        self.turns = list(turns)
        self.idx = 0
        self.recorded_messages: list[list[Any]] = []

    def _get_turn_payload(self) -> dict[str, Any]:
        if self.idx < len(self.turns):
            payload = self.turns[self.idx]
            self.idx += 1
            return payload
        return {"content": "已完成所有操作。", "tool_calls": None}

    async def achat(self, messages, tools=None, **kwargs) -> Response:
        self.recorded_messages.append(list(messages))
        payload = self._get_turn_payload()
        return Response(
            content=payload.get("content", ""),
            model="fake-perm-llm",
            tool_calls=payload.get("tool_calls"),
        )

    async def achat_stream(self, messages, tools=None, **kwargs):
        self.recorded_messages.append(list(messages))
        payload = self._get_turn_payload()

        if "reasoning_content" in payload:
            yield StreamChunk(
                content="",
                metadata={"reasoning_content": payload["reasoning_content"]},
            )

        yield StreamChunk(
            content=payload.get("content", ""),
            tool_calls=payload.get("tool_calls"),
            finish_reason="stop" if not payload.get("tool_calls") else "tool_calls",
        )


async def test_e2e_user_denial_write_flow_and_self_correction(tmp_path: Path):
    """验证用户拒绝写文件流：

    1. 模型第 1 轮调用 write 工具尝试写入 config.py；
    2. PermissionGate 触发 ConfirmView，用户输入 'n' 拒绝；
    3. ToolCallHook 拦截并返回 block=True，转录本记录工具执行被拒绝；
    4. 模型第 2 轮感知被拒原因，优雅自愈：改为直接在文本中输出只读代码，不再调用 write；
    5. 校验：磁盘上 config.py 文件绝未被创建；EventRenderer 正确渲染失败徽标与拒绝原因。
    """
    out_buf = io.StringIO()
    console = Console(file=out_buf, force_terminal=True, record=True, width=120)

    # 1. 模拟 ConfirmView 输入 hook 返回 'n' (拒绝)
    confirm_input_mock = AsyncMock(return_value="n")
    confirm_view = ConfirmView(console=console, input_hook=confirm_input_mock)

    async def confirm_callback(req: PermissionRequest) -> bool:
        details = req.preview or req.target
        return await confirm_view.prompt_confirm(
            prompt_text=f"智能体请求执行工具 [{req.action}]，是否批准？",
            default=True,
            details_text=details,
            title=f"⚠️ 工具权限审查: {req.action}",
        )

    gate = PermissionGate(mode="review", confirm_callback=confirm_callback)

    target_file = tmp_path / "config.py"
    assert not target_file.exists()

    # 2. 构造 2 轮 LLM 交互：第 1 轮写文件，第 2 轮自愈输出只读文本
    turns = [
        {
            "reasoning_content": "准备为用户创建 config.py 配置文件...",
            "content": "",
            "tool_calls": [
                ToolCall(
                    id="call_write_denied",
                    name="write",
                    args={"path": "config.py", "content": "DEBUG = True\nSECRET = 'xyz'\n"},
                )
            ],
        },
        {
            "reasoning_content": "检测到用户拒绝写入文件，改为在终端直接提供配置文本内容...",
            "content": "由于写入权限被您拒绝，以下为建议的配置内容：\n```python\nDEBUG = True\nSECRET = 'xyz'\n```",
            "tool_calls": None,
        },
    ]

    llm = ScriptedPermissionLLM(turns)
    session_file = tmp_path / "session_denial.jsonl"
    agent = CodingAgent(
        workspace=tmp_path,
        llm=llm,
        session=session_file,
        permission_gate=gate,
    )

    renderer = EventRenderer(console=console)
    events: list[Event] = []

    # 3. 运行流式驱动循环
    async for ev in agent.run_stream("请帮我创建 config.py 配置文件"):
        events.append(ev)
        renderer.on_event(ev)

    # 4. 验证断言
    # (a) 磁盘文件绝未被创建
    assert not target_file.exists()

    # (b) ConfirmView 被精确触发一次且拒绝
    assert confirm_input_mock.await_count == 1

    # (c) 工具执行结束事件为 is_error=True
    tool_ends = [e for e in events if isinstance(e, ToolExecutionEnd)]
    assert len(tool_ends) == 1
    assert tool_ends[0].tool_name == "write"
    assert tool_ends[0].is_error is True
    assert "用户拒绝了工具 [write] 的执行请求" in str(tool_ends[0].result)

    # (d) 模型第二轮确实在转录本中接收到了拒绝消息
    assert len(llm.recorded_messages) == 2
    turn2_msgs = llm.recorded_messages[1]
    turn2_tool_msg = next((m for m in turn2_msgs if m.role == "tool"), None)
    assert turn2_tool_msg is not None
    assert "用户拒绝了工具 [write]" in turn2_tool_msg.content

    # (e) 最终助手输出为优雅自愈文本
    agent_end = next(e for e in events if isinstance(e, AgentEnd))
    assert "由于写入权限被您拒绝" in (agent_end.final_text or "")

    # (f) EventRenderer 渲染输出包含失败标记与审查标题
    plain_text = console.export_text()
    assert "⚠️ 工具权限审查: write" in plain_text
    assert "✗ Failed [write]" in plain_text


async def test_e2e_user_approval_edit_flow_with_diff_words_highlight(tmp_path: Path):
    """验证用户批准修改流与词级 Diff 反色高亮：

    1. 工作区预置 calc.py 存在加法 Bug (return a - b)；
    2. 模型调用 edit 工具进行外科手术修复；
    3. PermissionGate 触发 ConfirmView，用户回车放行 (输入 '')；
    4. edit 工具原子应用变更，生成 Unified Diff；
    5. EventRenderer 识别 diffBlock 并调用 render_diff_with_word_highlight 进行词级高亮；
    6. 校验：calc.py 真实写入 return a + b；控制台输出包含反色词级 Diff 标记与 ✓ OK [edit]。
    """
    out_buf = io.StringIO()
    console = Console(file=out_buf, force_terminal=True, record=True, width=120)

    # 1. 预置目标源码
    src_file = tmp_path / "calc.py"
    src_file.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")

    # 2. 模拟 ConfirmView 输入 hook 回车放行 ('')
    confirm_input_mock = AsyncMock(return_value="")
    confirm_view = ConfirmView(console=console, input_hook=confirm_input_mock)

    async def confirm_callback(req: PermissionRequest) -> bool:
        details = req.preview or req.target
        return await confirm_view.prompt_confirm(
            prompt_text=f"智能体请求执行工具 [{req.action}]，是否批准？",
            default=True,
            details_text=details,
            title=f"⚠️ 工具权限审查: {req.action}",
        )

    gate = PermissionGate(mode="review", confirm_callback=confirm_callback)

    # 3. 构造 2 轮 LLM 交互
    turns = [
        {
            "reasoning_content": "分析 calc.py 中的减法错误并使用 edit 工具修复为加法...",
            "content": "",
            "tool_calls": [
                ToolCall(
                    id="call_edit_ok",
                    name="edit",
                    args={
                        "path": "calc.py",
                        "edits": [
                            {
                                "oldText": "def add(a, b):\n    return a - b",
                                "newText": "def add(a, b):\n    return a + b",
                            }
                        ],
                    },
                )
            ],
        },
        {
            "reasoning_content": "代码已成功修改，向用户汇报结果...",
            "content": "已成功修正 calc.py 中的 add 函数为正确加法实现。",
            "tool_calls": None,
        },
    ]

    llm = ScriptedPermissionLLM(turns)
    session_file = tmp_path / "session_approval.jsonl"
    agent = CodingAgent(
        workspace=tmp_path,
        llm=llm,
        session=session_file,
        permission_gate=gate,
    )

    renderer = EventRenderer(console=console)
    events: list[Event] = []

    async for ev in agent.run_stream("请修复 calc.py 中的 Bug"):
        events.append(ev)
        renderer.on_event(ev)

    # 4. 验证断言
    # (a) 磁盘文件真实原子修改
    updated_code = src_file.read_text(encoding="utf-8")
    assert "return a + b" in updated_code
    assert "return a - b" not in updated_code

    # (b) ConfirmView 精确放行
    assert confirm_input_mock.await_count == 1

    # (c) 工具执行状态为 OK
    tool_ends = [e for e in events if isinstance(e, ToolExecutionEnd)]
    assert len(tool_ends) == 1
    assert tool_ends[0].tool_name == "edit"
    assert tool_ends[0].is_error is False
    assert "Successfully applied 1 edit(s)" in str(tool_ends[0].result)

    # (d) 终端渲染包含词级 Diff 格式标记与 OK 状态
    plain_text = console.export_text()
    assert "⚠️ 工具权限审查: edit" in plain_text
    assert "✓ OK [edit]" in plain_text
    assert "--- a/calc.py" in plain_text
    assert "+++ b/calc.py" in plain_text
    assert "-    return a - b" in plain_text
    assert "+    return a + b" in plain_text

    # (d2) 验证包含反色词级高亮 ANSI 样式 (7;31m 与 7;32m)
    raw_output = out_buf.getvalue()
    assert "\x1b[1;7;31m-\x1b[0m" in raw_output or "\x1b[7m" in raw_output or "\x1b[1;7" in raw_output

    # (e) 助手最终回复正确
    agent_end = next(e for e in events if isinstance(e, AgentEnd))
    assert "已成功修正 calc.py" in (agent_end.final_text or "")


async def test_e2e_safe_bash_bypasses_confirm_while_unsafe_prompts(tmp_path: Path):
    """验证 review 模式下 safe_bash 自动放行与 unsafe_bash 严格审批：

    1. Safe bash (如 'pytest')：直接执行，ConfirmView 绝不弹出；
    2. Unsafe bash (如 'rm -rf ...')：PermissionGate 拦截并触发 ConfirmView。
    """
    out_buf = io.StringIO()
    console = Console(file=out_buf, force_terminal=True, width=120)

    confirm_input_mock = AsyncMock(return_value="n")  # 拒绝 unsafe
    confirm_view = ConfirmView(console=console, input_hook=confirm_input_mock)

    async def confirm_callback(req: PermissionRequest) -> bool:
        return await confirm_view.prompt_confirm(
            prompt_text=f"智能体请求执行工具 [{req.action}]，是否批准？",
            default=True,
            details_text=req.preview or req.target,
        )

    gate = PermissionGate(mode="review", confirm_callback=confirm_callback)

    # 1. 模拟执行 safe 命令与 unsafe 命令
    turns = [
        {
            "content": "",
            "tool_calls": [
                ToolCall(
                    id="call_safe_bash",
                    name="bash",
                    args={"command": "pytest --version"},
                )
            ],
        },
        {
            "content": "安全命令执行完毕，准备执行高危命令...",
            "tool_calls": [
                ToolCall(
                    id="call_unsafe_bash",
                    name="bash",
                    args={"command": "rm -rf /tmp/dangerous_dir"},
                )
            ],
        },
        {
            "content": "危险命令已被用户拒绝，取消删除计划。",
            "tool_calls": None,
        },
    ]

    llm = ScriptedPermissionLLM(turns)
    session_file = tmp_path / "session_bash_safe.jsonl"
    agent = CodingAgent(
        workspace=tmp_path,
        llm=llm,
        session=session_file,
        permission_gate=gate,
    )

    events: list[Event] = []
    async for ev in agent.run_stream("测试安全与危险命令"):
        events.append(ev)

    # 验证：ConfirmView 只被 unsafe_bash 触发了 1 次，safe_bash 零等待直通
    assert confirm_input_mock.await_count == 1
    tool_ends = [e for e in events if isinstance(e, ToolExecutionEnd)]
    assert len(tool_ends) == 2

    # 第 1 个 safe bash 工具调用正常完成 (ok)
    assert tool_ends[0].tool_name == "bash"
    # 第 2 个 unsafe bash 工具调用被拦截 (is_error=True)
    assert tool_ends[1].tool_name == "bash"
    assert tool_ends[1].is_error is True
    assert "用户拒绝了工具 [bash]" in str(tool_ends[1].result)


async def test_e2e_strict_mode_intercepts_readonly_tools(tmp_path: Path):
    """验证 strict 模式下即便是只读工具 (read/find/grep) 也必须经由用户审批：

    1. Mode = strict；
    2. 第 1 轮 read('secret.env')，用户输入 'y' -> 放行并读取文件；
    3. 第 2 轮 read('forbidden.txt')，用户输入 'n' -> 拦截并报错。
    """
    secret_file = tmp_path / "secret.env"
    secret_file.write_text("API_KEY=123456\n", encoding="utf-8")

    out_buf = io.StringIO()
    console = Console(file=out_buf, force_terminal=True, width=120)

    # 依次返回 'y' (放行第 1 轮) 和 'n' (拒绝第 2 轮)
    confirm_input_mock = AsyncMock(side_effect=["y", "n"])
    confirm_view = ConfirmView(console=console, input_hook=confirm_input_mock)

    async def confirm_callback(req: PermissionRequest) -> bool:
        return await confirm_view.prompt_confirm(
            prompt_text=f"智能体请求执行工具 [{req.action}]，是否批准？",
            default=True,
            details_text=req.target,
        )

    gate = PermissionGate(mode="strict", confirm_callback=confirm_callback)

    turns = [
        {
            "content": "",
            "tool_calls": [
                ToolCall(
                    id="call_read_1",
                    name="read",
                    args={"path": "secret.env"},
                )
            ],
        },
        {
            "content": "已读取 secret.env，接着尝试读取 forbidden.txt...",
            "tool_calls": [
                ToolCall(
                    id="call_read_2",
                    name="read",
                    args={"path": "forbidden.txt"},
                )
            ],
        },
        {
            "content": "读取 forbidden.txt 被拒，流程结束。",
            "tool_calls": None,
        },
    ]

    llm = ScriptedPermissionLLM(turns)
    agent = CodingAgent(
        workspace=tmp_path,
        llm=llm,
        session=tmp_path / "session_strict.jsonl",
        permission_gate=gate,
    )

    events: list[Event] = []
    async for ev in agent.run_stream("严苛模式读取文件"):
        events.append(ev)

    # 校验 ConfirmView 被触发了两次 (两个只读操作均被审批)
    assert confirm_input_mock.await_count == 2
    tool_ends = [e for e in events if isinstance(e, ToolExecutionEnd)]
    assert len(tool_ends) == 2

    # 第 1 次 read 成功
    assert tool_ends[0].is_error is False
    assert "API_KEY=123456" in str(tool_ends[0].result)

    # 第 2 次 read 被拒
    assert tool_ends[1].is_error is True
    assert "用户拒绝了工具 [read]" in str(tool_ends[1].result)


async def test_e2e_cli_dispatcher_mode_switch_live_integration(tmp_path: Path):
    """验证 CLI CommandDispatcher 动态模式切换与 PermissionGate 实时生效：

    1. 初始为 review 模式：写文件时被用户拒绝；
    2. 用户通过 /mode yolo 切换至 yolo/autonomous 模式；
    3. 再次写文件：无阻拦极速放行，文件真实生成；
    4. 用户通过 /mode review 恢复审查模式。
    """
    out_buf = io.StringIO()
    console = Console(file=out_buf, force_terminal=True, width=120)

    confirm_input_mock = AsyncMock(return_value="n")
    confirm_view = ConfirmView(console=console, input_hook=confirm_input_mock)

    async def confirm_callback(req: PermissionRequest) -> bool:
        return await confirm_view.prompt_confirm(
            prompt_text=f"智能体请求执行工具 [{req.action}]，是否批准？",
            default=True,
            details_text=req.preview or req.target,
        )

    gate = PermissionGate(mode="review", confirm_callback=confirm_callback)

    # 轮次 1：review 模式下写 a.txt -> 被拒 -> 自愈
    turns_1 = [
        {
            "content": "",
            "tool_calls": [
                ToolCall(
                    id="c_w1",
                    name="write",
                    args={"path": "a.txt", "content": "hello a"},
                )
            ],
        },
        {
            "content": "写入 a.txt 被拒绝。",
            "tool_calls": None,
        },
    ]
    # 轮次 2：yolo 模式下写 b.txt -> 直通放行 -> 成功
    turns_2 = [
        {
            "content": "",
            "tool_calls": [
                ToolCall(
                    id="c_w2",
                    name="write",
                    args={"path": "b.txt", "content": "hello b"},
                )
            ],
        },
        {
            "content": "成功写入 b.txt。",
            "tool_calls": None,
        },
    ]

    all_turns = turns_1 + turns_2
    llm = ScriptedPermissionLLM(all_turns)
    agent = CodingAgent(
        workspace=tmp_path,
        llm=llm,  # type: ignore[arg-type]
        session=tmp_path / "session_cli_mode.jsonl",
        permission_gate=gate,
    )
    dispatcher = CommandDispatcher(agent)

    # 阶段 1：review 模式提问 -> 拦截
    await agent.run("请写 a.txt")
    assert not (tmp_path / "a.txt").exists()
    assert confirm_input_mock.await_count == 1

    # 阶段 2：通过斜杠命令切换模式
    await dispatcher.dispatch("/mode yolo", console)
    assert gate.mode == "autonomous"

    # 阶段 3：yolo 模式提问 -> 直接写 (同一 agent 继续消费后续 turns)
    await agent.run("请写 b.txt")
    assert (tmp_path / "b.txt").exists()
    assert (tmp_path / "b.txt").read_text(encoding="utf-8") == "hello b"
    # ConfirmView 没有被二次触发
    assert confirm_input_mock.await_count == 1

    # 阶段 4：切回 review 模式
    await dispatcher.dispatch("/mode review", console)
    assert gate.mode == "review"


async def test_e2e_full_cli_repl_loop_permissions_and_modes(tmp_path: Path):
    """端到端全交互 REPL 循环权限拦截、自愈与模式切换演练：

    1. /mode 查看初始为 review；
    2. 发起写 main.py 提问 -> 触发 ConfirmView -> 用户输入 'n' 拒绝 -> 工具被拦截 -> 模型自愈；
    3. /mode yolo 切换为自主放行模式；
    4. 再次发起写 main.py 提问 -> 无弹窗直接放行 -> main.py 成功创建；
    5. /exit 正常退出 REPL。
    """
    out_buf = io.StringIO()
    console = Console(file=out_buf, force_terminal=True, record=True, width=120)

    confirm_input_mock = AsyncMock(return_value="n")
    confirm_view = ConfirmView(console=console, input_hook=confirm_input_mock)

    async def confirm_callback(req: PermissionRequest) -> bool:
        return await confirm_view.prompt_confirm(
            prompt_text=f"智能体请求执行工具 [{req.action}]，是否批准？",
            default=True,
            details_text=req.preview or req.target,
        )

    gate = PermissionGate(mode="review", confirm_callback=confirm_callback)

    main_py = tmp_path / "main.py"
    assert not main_py.exists()

    turns = [
        # 第 1 轮提问被拒绝的 2 个子回合 (LLM 调用 1: 工具 call, LLM 调用 2: 自愈输出)
        {
            "content": "",
            "tool_calls": [
                ToolCall(
                    id="c_repl_w1",
                    name="write",
                    args={"path": "main.py", "content": "print('hello v1')\n"},
                )
            ],
        },
        {
            "content": "写入 main.py 被拒绝，已取消创建。",
            "tool_calls": None,
        },
        # 第 2 轮提问在 yolo 模式下的 2 个子回合 (LLM 调用 3: 工具 call, LLM 调用 4: 成功输出)
        {
            "content": "",
            "tool_calls": [
                ToolCall(
                    id="c_repl_w2",
                    name="write",
                    args={"path": "main.py", "content": "print('hello v2')\n"},
                )
            ],
        },
        {
            "content": "在 yolo 模式下已成功创建 main.py 文件。",
            "tool_calls": None,
        },
    ]

    llm = ScriptedPermissionLLM(turns)
    agent = CodingAgent(
        workspace=tmp_path,
        llm=llm,  # type: ignore[arg-type]
        session=tmp_path / "session_cli_loop.jsonl",
        permission_gate=gate,
    )

    # 模拟用户在交互 CLI 中的多轮输入
    mock_prompt_session = MagicMock()
    mock_prompt_session.prompt_async = AsyncMock(
        side_effect=[
            "/mode",
            "请帮我创建 main.py",
            "/mode yolo",
            "请帮我创建 main.py",
            "/exit",
        ]
    )

    await run_cli_loop(agent, console, prompt_session=mock_prompt_session)

    plain = console.export_text()

    # 1. 验证横幅与初始 /mode
    assert "my-agent-tui 终端交互助手" in plain
    assert "当前权限模式: review" in plain

    # 2. 验证第一轮被拦截
    assert "操作安全审查" in plain or "工具权限审查" in plain
    assert "✗ Failed [write]" in plain
    assert "写入 main.py 被拒绝，已取消创建。" in plain

    # 3. 验证 /mode yolo 切换
    assert "权限模式已切换为: autonomous" in plain or "autonomous" in plain

    # 4. 验证第二轮放行并成功
    assert "✓ OK [write]" in plain
    assert "在 yolo 模式下已成功创建 main.py 文件。" in plain
    assert main_py.exists()
    assert main_py.read_text(encoding="utf-8") == "print('hello v2')\n"

    # 5. 验证退出
    assert "正在退出... 再见！" in plain
