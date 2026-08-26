"""产品层装配离线测试：build_coding_tools + CodingAgent 自动装配。"""

import pytest
from my_agent_llm import Response

from my_agent_core import Agent
from my_agent_core.session import Session
from my_coding_agent.agent import CodingAgent, build_coding_tools


class _FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)

    async def achat_stream(self, *, messages, tools=None, **kwargs):
        yield self.responses.pop(0)

    async def achat(self, *, messages, tools=None, **kwargs):
        return self.responses.pop(0)

    def chat(self, *, messages, tools=None, **kwargs):
        return self.responses.pop(0)


def test_build_coding_tools_returns_four(tmp_path):
    tools = build_coding_tools(tmp_path)
    names = sorted(t.name for t in tools)
    assert names == ["bash", "edit", "read", "write"]


def test_coding_agent_auto_registers_file_tools(tmp_path):
    session = Session(path=tmp_path / "s.jsonl")
    agent = CodingAgent(workspace=tmp_path, llm=_FakeLLM([]), session=session)
    names = {t.name for t in agent.agent.registry.list()}
    assert {"read", "write", "edit", "bash"} <= names


def test_coding_agent_merges_extra_tools(tmp_path):
    from my_agent_core import tool

    @tool
    def double(x: int) -> int:
        """Double x."""
        return x * 2

    session = Session(path=tmp_path / "s.jsonl")
    agent = CodingAgent(
        workspace=tmp_path, llm=_FakeLLM([]), session=session, extra_tools=[double]
    )
    names = {t.name for t in agent.agent.registry.list()}
    assert {"read", "write", "edit", "bash", "double"} <= names


@pytest.mark.anyio
async def test_coding_agent_run_delegates(tmp_path):
    session = Session(path=tmp_path / "s.jsonl")
    agent = CodingAgent(workspace=tmp_path, llm=_FakeLLM([Response(content="hi", model="fake")]), session=session)
    result = await agent.run("hello")
    assert result == "hi"