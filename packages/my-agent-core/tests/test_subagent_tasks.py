"""subagent 委派任务生命周期测试（SubagentTask/SubagentTaskStatus/SubagentTaskManager/工具桥）。"""

import json
from pathlib import Path
import tempfile

import pytest  # pyright: ignore[reportMissingImports]
from my_agent_llm import Response, StreamChunk  # pyright: ignore[reportMissingImports]

from my_agent_core.agent import Agent  # pyright: ignore[reportMissingImports]
from my_agent_core.session import Session  # pyright: ignore[reportMissingImports]
from my_agent_core.subagent_tasks import (  # pyright: ignore[reportMissingImports]
    SubagentTaskManager,
    SubagentTaskStatus,
)
from my_agent_core.subagents import (
    SubagentManager,  # pyright: ignore[reportMissingImports]
)
from my_agent_core.tools import tool  # pyright: ignore[reportMissingImports]
from my_agent_core.tools.builtin import (
    make_task_tool,  # pyright: ignore[reportMissingImports]
)


class FakeLLM:
    def __init__(self, responses: list[Response]):
        self.responses = list(responses)
        self.calls: list[dict] = []

    async def achat(self, *, messages, tools=None, **kwargs) -> Response:
        self.calls.append({"messages": list(messages), "tools": tools, **kwargs})
        return self.responses.pop(0)

    async def achat_stream(self, *, messages, tools=None, **kwargs):
        self.calls.append({"messages": list(messages), "tools": tools, **kwargs})
        resp = self.responses.pop(0)
        yield StreamChunk(
            content=resp.content,
            tool_calls=resp.tool_calls,
            finish_reason=resp.finish_reason,
        )

    def chat(self, *, messages, tools=None, **kwargs) -> Response:
        self.calls.append({"messages": list(messages), "tools": tools, **kwargs})
        return self.responses.pop(0)


class RaisingLLM:
    def __init__(self):
        self.calls = []

    async def achat(self, *, messages, tools=None, **kwargs) -> Response:
        raise RuntimeError("boom")

    async def achat_stream(self, *, messages, tools=None, **kwargs):
        raise RuntimeError("boom")
        yield  # make it a generator

    def chat(self, *, messages, tools=None, **kwargs) -> Response:
        raise RuntimeError("boom")


def _response(content: str = "", tool_calls=None) -> Response:
    return Response(
        content=content,
        model="test",
        tool_calls=tool_calls,
        finish_reason="tool_use" if tool_calls else "end_turn",
    )


def _task_call(prompt: str, agent_type: str = "default") -> dict:
    return {
        "id": "c1",
        "type": "function",
        "function": {
            "name": "task",
            "arguments": json.dumps({"prompt": prompt, "agent_type": agent_type}),
        },
    }


def _write_agent(directory: Path, name: str, **fields) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    content = fields.pop("content", "You are a subagent.")
    lines = ["---"]
    for k, v in fields.items():
        lines.append(f"{k}: {v}")
    lines.extend(["---", "", content])
    (directory / f"{name}.md").write_text("\n".join(lines), encoding="utf-8")


@tool
def multiply(a: int, b: int) -> int:
    """Multiply two integers."""
    return a * b


@pytest.mark.anyio
async def test_start_task_success(tmp_path: Path):
    """start_task 成功 ➔ COMPLETED + result 正确 + id 非空。"""
    _write_agent(
        tmp_path, "code-reviewer", description="d", content="You are a reviewer."
    )
    manager = SubagentManager([tmp_path])
    parent = Agent(
        llm=FakeLLM([_response(content="found issues")]),
        tools=[multiply],
        session=Session(path=Path(tempfile.mkdtemp()) / "s.jsonl"),
    )
    task = await SubagentTaskManager(manager, parent).start_task(
        "review this", "code-reviewer"
    )
    assert task.status is SubagentTaskStatus.COMPLETED
    assert task.result == "found issues"
    assert task.error is None
    assert task.id.startswith("task_")


@pytest.mark.anyio
async def test_start_task_unknown_agent_error(tmp_path: Path):
    """未知名 agent ➔ ERROR + error 包含可用列表提示。"""
    _write_agent(
        tmp_path, "code-reviewer", description="d", content="You are a reviewer."
    )
    manager = SubagentManager([tmp_path])
    parent = Agent(
        llm=FakeLLM([_response(content="")]),
        tools=[multiply],
        session=Session(path=Path(tempfile.mkdtemp()) / "s.jsonl"),
    )
    task = await SubagentTaskManager(manager, parent).start_task("go", "nope")
    assert task.status is SubagentTaskStatus.ERROR
    assert task.result is None
    assert task.error is not None
    assert "Unknown subagent 'nope'" in task.error
    assert "code-reviewer" in task.error


@pytest.mark.anyio
async def test_start_task_default_fallback(tmp_path: Path):
    """默认 agent_type 缺省降级为 DEFAULT_SUBAGENT。"""
    manager = SubagentManager([tmp_path])
    parent = Agent(
        llm=FakeLLM([_response(content="default reply")]),
        tools=[multiply],
        session=Session(path=Path(tempfile.mkdtemp()) / "s.jsonl"),
    )
    task = await SubagentTaskManager(manager, parent).start_task("go", "default")
    assert task.status is SubagentTaskStatus.COMPLETED
    assert task.result == "default reply"


@pytest.mark.anyio
async def test_start_task_subagent_exception(tmp_path: Path):
    """子代理抛出异常 ➔ ERROR + error 包含 'Subagent ... failed: ' 前缀。"""
    _write_agent(
        tmp_path, "code-reviewer", description="d", content="You are a reviewer."
    )
    manager = SubagentManager([tmp_path])
    parent = Agent(
        llm=RaisingLLM(),
        tools=[multiply],
        session=Session(path=Path(tempfile.mkdtemp()) / "s.jsonl"),
    )
    task = await SubagentTaskManager(manager, parent).start_task("go", "code-reviewer")
    assert task.status is SubagentTaskStatus.ERROR
    assert task.error is not None
    assert "Subagent 'code-reviewer' failed: boom" in task.error


@pytest.mark.anyio
async def test_make_task_tool_bridge(tmp_path: Path):
    """工具桥：task 工具成功返回 result。"""
    _write_agent(
        tmp_path, "code-reviewer", description="d", content="You are a reviewer."
    )
    manager = SubagentManager([tmp_path])
    parent = Agent(
        llm=FakeLLM([_response(content="found issues")]),
        tools=[multiply],
        session=Session(path=Path(tempfile.mkdtemp()) / "s.jsonl"),
    )
    task_tool = make_task_tool(manager, parent)
    result = await task_tool.execute(
        {"prompt": "review", "agent_type": "code-reviewer"}
    )
    assert result.ok is True
    assert result.data == "found issues"


@pytest.mark.anyio
async def test_make_task_tool_bridge_error(tmp_path: Path):
    """工具桥：异常时返回错误信息字符串。"""
    _write_agent(
        tmp_path, "code-reviewer", description="d", content="You are a reviewer."
    )
    manager = SubagentManager([tmp_path])
    parent = Agent(
        llm=RaisingLLM(),
        tools=[multiply],
        session=Session(path=Path(tempfile.mkdtemp()) / "s.jsonl"),
    )
    task_tool = make_task_tool(manager, parent)
    result = await task_tool.execute(
        {"prompt": "review", "agent_type": "code-reviewer"}
    )
    assert result.ok is True
    assert "Subagent 'code-reviewer' failed: boom" in str(result.data)


@pytest.mark.anyio
async def test_subagent_session_persists(tmp_path: Path):
    """委派后子代理独立 session 存入 subagents/，且父 session 不受污染。"""
    _write_agent(
        tmp_path, "code-reviewer", description="d", content="You are a reviewer."
    )
    manager = SubagentManager([tmp_path])
    parent_session = Session(path=tmp_path / "parent.jsonl")
    llm = FakeLLM(
        [
            _response(tool_calls=[_task_call("review", "code-reviewer")]),
            _response(content="found issues"),
            _response(content="done"),
        ]
    )
    agent = Agent(llm=llm, tools=[multiply], session=parent_session)
    agent.registry.register(make_task_tool(manager, agent))
    await agent.run("delegate")
    subagents_dir = tmp_path / "subagents"
    assert subagents_dir.is_dir()
    files = list(subagents_dir.glob("agent-*.jsonl"))
    assert len(files) == 1
    # 子代理 session 存子代理对话；父 session 无子代理消息
    child = Session.load(files[0])
    assert any(e.role == "assistant" for e in child.tree.entries.values())
    assert not any(
        e.content == "found issues"
        and e.role == "assistant"
        and "tool_calls" not in e.metadata
        for e in parent_session.tree.entries.values()
    )


@pytest.mark.anyio
async def test_multiple_subagents_parallel_delegation(tmp_path: Path):
    """验证同时派发多个 Subagent 并行执行业务。"""
    _write_agent(tmp_path, "reviewer", description="review", content="Reviewer prompt")
    _write_agent(
        tmp_path, "researcher", description="research", content="Researcher prompt"
    )
    manager = SubagentManager([tmp_path])
    parent_session = Session(path=tmp_path / "parent.jsonl")

    llm = FakeLLM(
        [
            # 1. 父 Agent 发出两条 tool_calls
            _response(
                tool_calls=[
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {
                            "name": "task",
                            "arguments": json.dumps(
                                {
                                    "prompt": "review code",
                                    "agent_type": "reviewer",
                                }
                            ),
                        },
                    },
                    {
                        "id": "c2",
                        "type": "function",
                        "function": {
                            "name": "task",
                            "arguments": json.dumps(
                                {
                                    "prompt": "search docs",
                                    "agent_type": "researcher",
                                }
                            ),
                        },
                    },
                ]
            ),
            # 2. 两个子 Agent 各自的回答
            _response(content="Code looks good"),
            _response(content="Docs found"),
            # 3. 父 Agent 最终总结
            _response(content="All subtasks finished"),
        ]
    )

    agent = Agent(llm=llm, tools=[], session=parent_session)
    agent.registry.register(make_task_tool(manager, agent))

    answer = await agent.run("coordinate")
    assert answer == "All subtasks finished"

    # 验证产生两个独立的 subagent session 文件
    sub_dir = tmp_path / "subagents"
    assert len(list(sub_dir.glob("agent-task_*.jsonl"))) == 2


@pytest.mark.anyio
async def test_subagent_delegation_with_parent_memory_enabled(tmp_path: Path):
    """验证父 Agent 启用 memory 且存在 memory_dir 时，子 Agent 委派不产生冲突。"""
    _write_agent(tmp_path, "worker", description="worker", content="Worker prompt")
    mem_dir = tmp_path / ".my_agent_core" / "memory"
    mem_dir.mkdir(parents=True, exist_ok=True)
    (mem_dir / "MEMORY.md").write_text("Parent memory fact", encoding="utf-8")

    parent_session = Session(path=tmp_path / "parent.jsonl")
    llm = FakeLLM(
        [
            # 1. 父 Agent 发起 task 委派
            _response(
                tool_calls=[
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {
                            "name": "task",
                            "arguments": json.dumps(
                                {
                                    "prompt": "do child work",
                                    "agent_type": "worker",
                                }
                            ),
                        },
                    }
                ]
            ),
            # 2. 子 Agent 回答
            _response(content="Child work completed"),
            # 3. 父 Agent 最终总结
            _response(content="All done"),
        ]
    )

    agent = Agent(
        llm=llm,
        tools=[],
        session=parent_session,
        subagent_dirs=[tmp_path],
        memory_dir=mem_dir,
    )

    assert agent.registry.get("memory") is not None
    assert "<MEMORY_CONTEXT>" in agent.messages[0].content

    answer = await agent.run("start")
    assert answer == "All done"


@pytest.mark.anyio
async def test_task_manager_steer_and_followup_task(tmp_path: Path):
    """验证 SubagentTaskManager 支持按 task_id 动态干预与转向运行中的子代理。"""
    _write_agent(tmp_path, "worker", description="worker", content="Worker prompt")
    manager = SubagentManager([tmp_path])
    parent_session = Session(path=tmp_path / "parent.jsonl")

    tm_holder = {}
    observed_active = {}

    class InterceptingLLM:
        def __init__(self):
            self.calls = 0

        async def achat_stream(self, *, messages, tools=None, **kwargs):
            self.calls += 1
            tm: SubagentTaskManager = tm_holder["tm"]
            active_ids = list(tm._active_agents.keys())
            if active_ids and self.calls == 1:
                tid = active_ids[0]
                child_agent = tm._active_agents[tid]
                observed_active["task_id"] = tid
                s_ok = tm.steer_task(tid, "child steer msg")
                f_ok = tm.follow_up_task(tid, "child followup msg")
                observed_active["steer_ok"] = s_ok
                observed_active["follow_ok"] = f_ok
                observed_active["has_steering"] = child_agent.message_queue.has_steering()
                observed_active["has_followup"] = child_agent.message_queue.has_followup()

            yield StreamChunk(content=f"Child answer {self.calls}", model="fake")

    llm = InterceptingLLM()
    parent = Agent(llm=llm, tools=[], session=parent_session)
    tm = SubagentTaskManager(manager, parent)
    tm_holder["tm"] = tm

    assert tm.steer_task("non_existent", "msg") is False
    assert tm.follow_up_task("non_existent", "msg") is False

    task = await tm.start_task("do work", "worker")
    assert task.status is SubagentTaskStatus.COMPLETED
    assert task.result == "Child answer 3"
    assert observed_active["steer_ok"] is True
    assert observed_active["follow_ok"] is True
    assert observed_active["has_steering"] is True
    assert observed_active["has_followup"] is True
