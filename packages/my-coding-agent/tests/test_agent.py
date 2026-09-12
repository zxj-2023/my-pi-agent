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
    def __init__(self, responses: list[Response]):
        self.responses = responses
        self.idx = 0

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

    # 验证 6 个工具已自动装配
    tool_names = set(agent.agent.registry._tools.keys())
    assert {"read", "write", "edit", "bash", "grep", "find"}.issubset(tool_names)

    # 验证 run() 返回最终文本
    res = await agent.run("Hello")
    assert res == "I am ready to code"


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
    assert "Workspace Directory:" in (agent_default.agent.system_prompt or "")
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
