from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

import pytest
from my_agent_core.events import (
    AgentEnd,
    AgentStart,
    Event,
    ToolExecutionEnd,
    ToolExecutionStart,
)
from my_agent_core.session import Session
from my_agent_llm.models import Response, StreamChunk, ToolCall

from my_coding_agent.agent import CodingAgent

pytestmark = [pytest.mark.anyio]


class ScriptedMultiTurnLLM:
    """按轮次返回预置响应的大模型测试替身，完整记录每轮接收到的 messages。"""

    def __init__(self, turns: list[dict[str, Any]]):
        self.turns = list(turns)
        self.idx = 0
        self.recorded_calls: list[list[Any]] = []

    def _get_turn_payload(self) -> dict[str, Any]:
        if self.idx < len(self.turns):
            payload = self.turns[self.idx]
            self.idx += 1
            return payload
        return {"content": "default finish", "tool_calls": None}

    async def achat(self, messages, tools=None, **kwargs) -> Response:
        self.recorded_calls.append(list(messages))
        payload = self._get_turn_payload()
        return Response(
            content=payload.get("content", ""),
            model="fake-e2e-model",
            tool_calls=payload.get("tool_calls"),
        )

    async def achat_stream(self, messages, tools=None, **kwargs):
        self.recorded_calls.append(list(messages))
        payload = self._get_turn_payload()
        yield StreamChunk(
            content=payload.get("content", ""),
            tool_calls=payload.get("tool_calls"),
        )


def _setup_calc_repository(ws: Path) -> tuple[Path, Path]:
    """在工作区中准备带有 Bug 的计算器源码与验证用 Pytest 测试。"""
    src_dir = ws / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    calc_py = src_dir / "calc.py"
    calc_py.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")

    tests_dir = ws / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    test_calc_py = tests_dir / "test_calc.py"
    test_calc_py.write_text(
        "import sys\nsys.path.insert(0, '.')\nfrom src.calc import add\n\ndef test_add():\n    assert add(1, 2) == 3\n",
        encoding="utf-8",
    )
    return calc_py, test_calc_py


def _build_5_turn_scenario() -> list[dict[str, Any]]:
    """构造 5 轮完整工程协作场景。"""
    return [
        # Turn 1: 发现项目文件
        {
            "content": "Searching for python files in workspace.",
            "tool_calls": [
                ToolCall(
                    id="call_1_find",
                    name="find",
                    args={"pattern": "*.py"},
                )
            ],
        },
        # Turn 2: 阅读待修复代码
        {
            "content": "Reading src/calc.py to diagnose the bug.",
            "tool_calls": [
                ToolCall(
                    id="call_2_read",
                    name="read",
                    args={"path": "src/calc.py"},
                )
            ],
        },
        # Turn 3: 实施精确外科手术式修复
        {
            "content": "Applying surgical edit to fix subtraction bug.",
            "tool_calls": [
                ToolCall(
                    id="call_3_edit",
                    name="edit",
                    args={
                        "path": "src/calc.py",
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
        # Turn 4: 运行自动化测试验证
        {
            "content": "Running pytest to verify fix.",
            "tool_calls": [
                ToolCall(
                    id="call_4_bash",
                    name="bash",
                    args={"command": f'"{sys.executable}" -m pytest'},
                )
            ],
        },
        # Turn 5: 最终反馈确认
        {
            "content": "All tests passed and bug is fixed.",
            "tool_calls": None,
        },
    ]


async def test_coding_agent_e2e_full_workflow_run(tmp_path: Path):
    """端到端场景验证 (agent.run 批处理入口)：

    Turn 1: find("*.py")
    Turn 2: read("src/calc.py")
    Turn 3: edit("src/calc.py", ...)
    Turn 4: bash("pytest")
    Turn 5: "All tests passed and bug is fixed."
    """
    calc_py, _ = _setup_calc_repository(tmp_path)
    assert "return a - b" in calc_py.read_text(encoding="utf-8")

    turns = _build_5_turn_scenario()
    fake_llm = ScriptedMultiTurnLLM(turns)
    session_file = tmp_path / "session_e2e_run.jsonl"
    session = Session(path=session_file)

    agent = CodingAgent(
        workspace=tmp_path,
        llm=fake_llm,
        session=session,
    )

    # 执行批处理 run 入口
    user_prompt = "Locate the bug in calc.py, fix it, and verify with pytest."
    final_output = await agent.run(user_prompt)

    # 1. 最终助手回复校验
    assert final_output == "All tests passed and bug is fixed."

    # 2. 磁盘文件状态已被原子修改校验
    reloaded_calc = calc_py.read_text(encoding="utf-8")
    assert "return a + b" in reloaded_calc
    assert "return a - b" not in reloaded_calc

    # 3. 5 轮交互完整性与转录本上下文校验
    assert len(fake_llm.recorded_calls) == 5

    # 验证 Turn 2 模型接收到的消息包含 find 工具执行产物
    turn2_messages = fake_llm.recorded_calls[1]
    turn2_tool_replies = [m.content for m in turn2_messages if m.role == "tool"]
    assert any("src/calc.py" in rep for rep in turn2_tool_replies)

    # 验证 Turn 3 模型接收到的消息包含 read 源码产物
    turn3_messages = fake_llm.recorded_calls[2]
    turn3_tool_replies = [m.content for m in turn3_messages if m.role == "tool"]
    assert any("def add(a, b):" in rep for rep in turn3_tool_replies)

    # 验证 Turn 4 模型接收到的消息包含 edit 的 unified diff
    turn4_messages = fake_llm.recorded_calls[3]
    turn4_tool_replies = [m.content for m in turn4_messages if m.role == "tool"]
    assert any("Successfully applied 1 edit(s)" in rep for rep in turn4_tool_replies)

    # 验证 Turn 5 模型接收到的消息包含 pytest 通过信息
    turn5_messages = fake_llm.recorded_calls[4]
    turn5_tool_replies = [m.content for m in turn5_messages if m.role == "tool"]
    assert any("passed" in rep.lower() for rep in turn5_tool_replies)

    # 4. 会话持久化校验
    assert session_file.exists()
    loaded_session = Session.load(session_file)
    history = loaded_session.get_full_history_messages()
    assert len(history) > 0
    assert history[-1].role == "assistant"
    assert history[-1].content == "All tests passed and bug is fixed."


async def test_coding_agent_e2e_full_workflow_run_stream(tmp_path: Path):
    """端到端事件流验证 (agent.run_stream 流式入口)：

    验证全生命周期事件广播（AgentStart -> ToolExecutionStart/End -> AgentEnd）。
    """
    calc_py, _ = _setup_calc_repository(tmp_path)
    assert "return a - b" in calc_py.read_text(encoding="utf-8")

    turns = _build_5_turn_scenario()
    fake_llm = ScriptedMultiTurnLLM(turns)
    session_file = tmp_path / "session_e2e_stream.jsonl"
    session = Session(path=session_file)

    agent = CodingAgent(
        workspace=tmp_path,
        llm=fake_llm,
        session=session,
    )

    events: list[Event] = []
    async for ev in agent.run_stream("Fix the bug and run tests."):
        events.append(ev)

    # 1. 首尾生命周期事件校验
    assert isinstance(events[0], AgentStart)
    assert isinstance(events[-1], AgentEnd)
    assert events[-1].final_text == "All tests passed and bug is fixed."

    # 2. 4 大工具执行顺序校验
    tool_start_events = [e for e in events if isinstance(e, ToolExecutionStart)]
    tool_end_events = [e for e in events if isinstance(e, ToolExecutionEnd)]

    called_tool_names = [e.tool_name for e in tool_start_events]
    assert called_tool_names == ["find", "read", "edit", "bash"]

    # 3. 各工具执行结果无错误并且数据正确
    assert len(tool_end_events) == 4
    for te in tool_end_events:
        assert te.is_error is False

    find_result = tool_end_events[0].result
    assert "src/calc.py" in find_result
    assert "tests/test_calc.py" in find_result

    read_result = tool_end_events[1].result
    assert "def add(a, b):" in read_result

    edit_result = tool_end_events[2].result
    assert "Successfully applied 1 edit(s)" in edit_result
    assert "Diff:" in edit_result

    bash_result = tool_end_events[3].result
    assert "passed" in bash_result.lower()

    # 4. 代码已生效
    assert "return a + b" in calc_py.read_text(encoding="utf-8")
