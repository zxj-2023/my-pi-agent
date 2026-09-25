from __future__ import annotations

from pathlib import Path

import pytest
from my_agent_core import tool
from my_agent_core.events import Event, MessageEnd
from my_agent_core.session import Session
from my_agent_llm.models import Response, StreamChunk

from my_coding_agent.agent import CodingAgent
from my_coding_agent.mutation_queue import FileMutationQueue

pytestmark = [pytest.mark.anyio]


class FakeCodingLLM:
    def __init__(self, responses: list[Response], config=None):
        self.responses = responses
        self.idx = 0
        self.config = config

    async def achat(self, messages, tools=None, **kwargs):
        resp = self.responses[self.idx]
        self.idx += 1
        return resp

    async def achat_stream(self, messages, tools=None, **kwargs):
        resp = await self.achat(messages, tools, **kwargs)
        yield StreamChunk(content=resp.content, tool_calls=resp.tool_calls)


async def test_coding_agent_dual_api_run(tmp_path: Path):
    fake_llm = FakeCodingLLM([Response(content="I am ready to code", model="fake")])
    session = Session(path=tmp_path / "session.jsonl")
    agent = CodingAgent(workspace=tmp_path, llm=fake_llm, session=session)

    # 验证 7 个工具已自动装配
    tool_names = set(agent.agent.registry._tools.keys())
    assert {"read", "write", "edit", "bash", "grep", "find", "ls"}.issubset(tool_names)

    # 验证 run() 返回最终文本
    res = await agent.run("Hello")
    assert res == "I am ready to code"


async def test_coding_agent_file_reference_expansion(tmp_path: Path):
    target_file = tmp_path / "sample.py"
    target_file.write_text("print('hello')", encoding="utf-8")

    captured_prompt: list[str] = []

    class CapturingLLM(FakeCodingLLM):
        async def achat(self, messages, tools=None, **kwargs):
            captured_prompt.append(messages[-1].content)
            return await super().achat(messages, tools, **kwargs)

    fake_llm = CapturingLLM([Response(content="done", model="fake")])
    session = Session(path=tmp_path / "session_ref.jsonl")
    agent = CodingAgent(workspace=tmp_path, llm=fake_llm, session=session)

    await agent.run("Please check @sample.py")
    assert len(captured_prompt) == 1
    assert "Please check @sample.py" in captured_prompt[0]
    assert '<referenced_file path="sample.py">' in captured_prompt[0]
    assert "print('hello')" in captured_prompt[0]


async def test_coding_agent_dual_api_run_stream(tmp_path: Path):
    fake_llm = FakeCodingLLM([Response(content="Streaming code", model="fake")])
    session = Session(path=tmp_path / "session_stream.jsonl")
    agent = CodingAgent(workspace=tmp_path, llm=fake_llm, session=session)

    events: list[Event] = []
    async for ev in agent.run_stream("Start streaming"):
        events.append(ev)

    assert any(isinstance(e, MessageEnd) for e in events)


async def test_coding_agent_merges_extra_tools(tmp_path: Path):
    @tool
    def custom_calc(val: int) -> int:
        """Custom tool."""
        return val + 42

    fake_llm = FakeCodingLLM([Response(content="ok", model="fake")])
    session = Session(path=tmp_path / "session_extra.jsonl")
    agent = CodingAgent(
        workspace=tmp_path,
        llm=fake_llm,
        session=session,
        extra_tools=[custom_calc],
    )

    tool_names = set(agent.agent.registry._tools.keys())
    assert {"read", "write", "edit", "bash", "grep", "find", "custom_calc"}.issubset(tool_names)


async def test_coding_agent_prompt_and_mutation_queue(tmp_path: Path):
    session = Session(path=tmp_path / "session_prompt.jsonl")
    fake_llm = FakeCodingLLM([Response(content="ok", model="fake")])

    # 1. 默认 prompt 自动扫描工作区
    agent_default = CodingAgent(workspace=tmp_path, llm=fake_llm, session=session)
    assert "<cwd>" in (agent_default.agent.system_prompt or "")
    assert str(tmp_path.resolve()).replace("\\", "/") in (agent_default.agent.system_prompt or "")
    assert isinstance(agent_default.mutation_queue, FileMutationQueue)
    assert agent_default.workspace == tmp_path.resolve()

    # 2. 自定义 prompt
    custom_session = Session(path=tmp_path / "session_custom.jsonl")
    agent_custom = CodingAgent(
        workspace=tmp_path,
        llm=fake_llm,
        session=custom_session,
        system_prompt="Custom instructions",
    )
    assert agent_custom.agent.system_prompt == "Custom instructions"

    # 3. 显式空字符串 prompt 不被覆盖
    empty_session = Session(path=tmp_path / "session_empty.jsonl")
    agent_empty = CodingAgent(
        workspace=tmp_path,
        llm=fake_llm,
        session=empty_session,
        system_prompt="",
    )
    assert agent_empty.agent.system_prompt == ""


async def test_coding_agent_session_and_compact(tmp_path: Path):
    session = Session(path=tmp_path / "session_prop.jsonl")
    fake_llm = FakeCodingLLM([Response(content="ok", model="fake")])
    agent = CodingAgent(workspace=tmp_path, llm=fake_llm, session=session)

    assert agent.session is agent.agent.session
    # Compact without crash
    res = await agent.compact()
    assert res is None


async def test_coding_agent_permission_gate(tmp_path: Path):
    from unittest.mock import AsyncMock

    from my_agent_core.hooks import ToolCallHook
    from my_coding_agent.permissions import PermissionGate

    mock_cb = AsyncMock(return_value=False)
    gate = PermissionGate(mode="strict", confirm_callback=mock_cb)

    session = Session(path=tmp_path / "session_gate.jsonl")
    fake_llm = FakeCodingLLM([Response(content="ok", model="fake")])
    agent = CodingAgent(
        workspace=tmp_path,
        llm=fake_llm,
        session=session,
        permission_gate=gate,
    )

    assert agent.permission_gate is gate
    # ToolCallHook should be registered in agent.agent.hooks
    handlers = agent.agent.hooks._handlers.get(ToolCallHook, [])
    assert gate in handlers


async def test_context_budget_follows_model_window(tmp_path: Path):
    """压缩预算 = 当前模型窗口（阀值 = 80%）：不再硬编码 100k。"""
    from my_agent_llm import Config

    fake_llm = FakeCodingLLM(
        [Response(content="ok", model="fake")], config=Config(provider="antigravity", model="gemini-3.8-flash")
    )
    session = Session(path=tmp_path / "session_budget.jsonl")
    agent = CodingAgent(workspace=tmp_path, llm=fake_llm, session=session)

    ctx = agent.agent.context_manager
    assert ctx.budget == 1_048_576
    assert ctx.budget_threshold == 1_048_576 * 4 // 5


async def test_context_budget_explicit_override_wins(tmp_path: Path):
    """显式 context_budget 优先于模型窗口推导。"""
    from my_agent_llm import Config

    fake_llm = FakeCodingLLM(
        [Response(content="ok", model="fake")], config=Config(provider="antigravity", model="gemini-3.8-flash")
    )
    session = Session(path=tmp_path / "session_budget2.jsonl")
    agent = CodingAgent(workspace=tmp_path, llm=fake_llm, session=session, context_budget=1000)

    assert agent.agent.context_manager.budget == 1000
