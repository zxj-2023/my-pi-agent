from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from my_agent_core.session import Session
from my_agent_llm.models import Response, StreamChunk, ToolCall

from my_coding_agent.agent import CodingAgent
from my_coding_agent.settings import Settings

pytestmark = [pytest.mark.anyio]


class FakeCodingLLM:
    """可记录每轮传入 tools 的测试用大模型替身。"""

    def __init__(self, responses: list[Response]):
        self.responses = list(responses)
        self.idx = 0
        self.recorded_tools: list[list[dict[str, Any]] | None] = []
        self.recorded_messages: list[list[Any]] = []

    async def achat(self, messages, tools=None, **kwargs) -> Response:
        self.recorded_tools.append(tools)
        self.recorded_messages.append(list(messages))
        if self.idx < len(self.responses):
            resp = self.responses[self.idx]
            self.idx += 1
            return resp
        return Response(content="done", model="fake")

    async def achat_stream(self, messages, tools=None, **kwargs):
        resp = await self.achat(messages, tools=tools, **kwargs)
        yield StreamChunk(content=resp.content, tool_calls=resp.tool_calls)


async def test_codemode_e2e_write_and_read(tmp_path: Path):
    """Test 1: Agent 收到用户请求，模型调用 codemode 执行 JS 代码写入并读取文件，最终输出格式化文本。"""
    script = (
        'const f1 = await tools.write({ path: "test.txt", content: "hello world" });\n'
        'const content = await tools.read({ path: "test.txt" });\n'
        'text("Read: " + content);\n'
    )
    responses = [
        Response(
            content="",
            model="fake",
            tool_calls=[
                ToolCall(
                    id="call_codemode_1",
                    name="codemode",
                    args={"code": script},
                )
            ],
        ),
        Response(
            content="Read file successfully: hello world",
            model="fake",
        ),
    ]
    fake_llm = FakeCodingLLM(responses)
    session = Session(path=tmp_path / "session.jsonl", cwd=str(tmp_path))
    agent = CodingAgent(
        workspace=tmp_path,
        llm=fake_llm,
        session=session,
    )

    res = await agent.run("Please write hello world to test.txt and read it back")

    # 1. 验证磁盘上的 test.txt 已被创建且内容正确
    test_file = tmp_path / "test.txt"
    assert test_file.exists()
    assert test_file.read_text(encoding="utf-8") == "hello world"

    # 2. 验证 agent 最终文本输出
    assert res == "Read file successfully: hello world"

    # 3. 验证 session 历史记录中包含 codemode 工具的执行回执
    tool_messages = [m for m in agent.session.get_full_history_messages() if m.role == "tool"]
    assert len(tool_messages) >= 1
    assert "Read: hello world" in str(tool_messages[0].content)


async def test_codemode_mode_only_exposes_only_codemode_schema(tmp_path: Path):
    """Test 2: 测试 codemode_mode == 'only'，验证暴露给大模型的 tools schema 仅有 codemode。"""
    responses = [
        Response(content="I only see codemode", model="fake"),
    ]
    fake_llm = FakeCodingLLM(responses)
    session = Session(path=tmp_path / "session_only.jsonl", cwd=str(tmp_path))
    settings = Settings(codemode_mode="only")
    agent = CodingAgent(
        workspace=tmp_path,
        llm=fake_llm,
        session=session,
        settings=settings,
    )

    await agent.run("What tools do you have?")

    # 验证传递给大模型的 tools 参数中仅且只包含 codemode
    assert len(fake_llm.recorded_tools) > 0
    tools_passed = fake_llm.recorded_tools[0]
    assert tools_passed is not None
    tool_names = [t["function"]["name"] for t in tools_passed]
    assert tool_names == ["codemode"]

    # 验证底层工具依然被 registry 持有，且仍可供沙箱回调
    assert "write" in agent.agent.registry._tools
    assert "read" in agent.agent.registry._tools


async def test_codemode_mode_only_can_still_execute_underlying_tools(tmp_path: Path):
    """Test 2 延伸：在 codemode_mode == 'only' 下，codemode 内部依然可以成功回调底层写和读工具。"""
    script = (
        'const res = await tools.write({ path: "only_mode.txt", content: "only mode content" });\n'
        'const textContent = await tools.read({ path: "only_mode.txt" });\n'
        'text("Content: " + textContent);\n'
    )
    responses = [
        Response(
            content="",
            model="fake",
            tool_calls=[
                ToolCall(
                    id="call_only_1",
                    name="codemode",
                    args={"code": script},
                )
            ],
        ),
        Response(
            content="Only mode completed",
            model="fake",
        ),
    ]
    fake_llm = FakeCodingLLM(responses)
    session = Session(path=tmp_path / "session_only_exec.jsonl", cwd=str(tmp_path))
    settings = Settings(codemode_mode="only")
    agent = CodingAgent(
        workspace=tmp_path,
        llm=fake_llm,
        session=session,
        settings=settings,
    )

    res = await agent.run("Run script in only mode")
    assert res == "Only mode completed"
    created_file = tmp_path / "only_mode.txt"
    assert created_file.exists()
    assert created_file.read_text(encoding="utf-8") == "only mode content"


async def test_codemode_batch_concurrency(tmp_path: Path):
    """Test 3: 测试 codemode 内部通过 Promise.all 进行批量并发写入。"""
    script = (
        "await Promise.all([\n"
        '    tools.write({ path: "a.txt", content: "A" }),\n'
        '    tools.write({ path: "b.txt", content: "B" })\n'
        "]);\n"
        'text("Batch written");\n'
    )
    responses = [
        Response(
            content="",
            model="fake",
            tool_calls=[
                ToolCall(
                    id="call_batch_1",
                    name="codemode",
                    args={"code": script},
                )
            ],
        ),
        Response(
            content="Batch write finished",
            model="fake",
        ),
    ]
    fake_llm = FakeCodingLLM(responses)
    session = Session(path=tmp_path / "session_batch.jsonl", cwd=str(tmp_path))
    agent = CodingAgent(
        workspace=tmp_path,
        llm=fake_llm,
        session=session,
    )

    res = await agent.run("Create a.txt and b.txt in parallel")

    assert (tmp_path / "a.txt").exists()
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "A"
    assert (tmp_path / "b.txt").exists()
    assert (tmp_path / "b.txt").read_text(encoding="utf-8") == "B"
    assert res == "Batch write finished"

    tool_messages = [m for m in agent.session.get_full_history_messages() if m.role == "tool"]
    assert len(tool_messages) >= 1
    assert "Batch written" in str(tool_messages[0].content)


async def test_codemode_mode_off_does_not_register_codemode(tmp_path: Path):
    """验证 codemode_mode == 'off' 时不装配 codemode 工具。"""
    responses = [Response(content="no codemode", model="fake")]
    fake_llm = FakeCodingLLM(responses)
    session = Session(path=tmp_path / "session_off.jsonl", cwd=str(tmp_path))
    settings = Settings(codemode_mode="off")
    agent = CodingAgent(
        workspace=tmp_path,
        llm=fake_llm,
        session=session,
        settings=settings,
    )

    await agent.run("Hello")
    assert "codemode" not in agent.agent.registry._tools


async def test_codemode_disabled_does_not_register_codemode(tmp_path: Path):
    """验证 codemode_enabled == False 时不装配 codemode 工具。"""
    responses = [Response(content="no codemode", model="fake")]
    fake_llm = FakeCodingLLM(responses)
    session = Session(path=tmp_path / "session_disabled.jsonl", cwd=str(tmp_path))
    settings = Settings(codemode_enabled=False)
    agent = CodingAgent(
        workspace=tmp_path,
        llm=fake_llm,
        session=session,
        settings=settings,
    )

    await agent.run("Hello")
    assert "codemode" not in agent.agent.registry._tools
