"""subagent 委派任务生命周期测试（Task/TaskStatus/TaskManager/工具桥）。"""
from my_agent_llm import Response

from my_agent_core.agent import Agent
from my_agent_core.subagents import SubagentManager
from my_agent_core.tasks import Task, TaskManager, TaskStatus
from my_agent_core.tools import tool
from my_agent_core.tools.builtin import make_task_tool


class FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def chat(self, *, messages, tools=None, **kwargs):
        self.calls.append({"messages": list(messages), "tools": tools, **kwargs})
        return self.responses.pop(0)


def _response(content="", tool_calls=None):
    return Response(content=content, model="fake", tool_calls=tool_calls)


@tool
def multiply(a: int, b: int) -> int:
    """Multiply two integers."""
    return a * b


def _write_agent(root, name, description="desc", content="body"):
    p = root / f"{name}.md"
    p.write_text(f"---\ndescription: {description}\n---\n\n{content}", encoding="utf-8")
    return p


def test_task_state_machine():
    """Task 状态机：set_result → COMPLETED，set_error → ERROR（互斥）。"""
    task = Task(id="task_00000001", status=TaskStatus.RUNNING)
    task.set_result("done")
    assert task.status is TaskStatus.COMPLETED
    assert task.result == "done"
    assert task.error is None
    task.set_error("boom")
    assert task.status is TaskStatus.ERROR
    assert task.error == "boom"
    assert task.result is None


def test_start_task_success(tmp_path):
    """start_task 成功 → COMPLETED + result 正确 + id 非空（#1）。"""
    _write_agent(tmp_path, "code-reviewer", description="d", content="You are a reviewer.")
    manager = SubagentManager([tmp_path])
    parent = Agent(llm=FakeLLM([_response(content="found issues")]), tools=[multiply])
    task = TaskManager(manager, parent).start_task("review this", "code-reviewer")
    assert task.status is TaskStatus.COMPLETED
    assert task.result == "found issues"
    assert task.id.startswith("task_")


def test_start_task_unknown_agent_type(tmp_path):
    """未知名 agent_type → ERROR + error 含名单（#2）。"""
    manager = SubagentManager([tmp_path])
    parent = Agent(llm=FakeLLM([]), tools=[multiply])
    task = TaskManager(manager, parent).start_task("go", "nope")
    assert task.status is TaskStatus.ERROR
    assert "Unknown subagent" in task.error
    assert "nope" in task.error


class RaisingLLM:
    def chat(self, *, messages, tools=None, **kwargs):
        raise RuntimeError("boom")


def test_start_task_subagent_exception(tmp_path):
    """子代理抛异常 → ERROR + error 保留 'Subagent ... failed: ' 前缀。"""
    _write_agent(tmp_path, "code-reviewer", description="d", content="You are a reviewer.")
    manager = SubagentManager([tmp_path])
    parent = Agent(llm=RaisingLLM(), tools=[multiply])
    task = TaskManager(manager, parent).start_task("go", "code-reviewer")
    assert task.status is TaskStatus.ERROR
    assert "Subagent 'code-reviewer' failed: boom" in task.error


def test_make_task_tool_bridge(tmp_path):
    """工具桥：task 工具成功返回 result（#4）。"""
    _write_agent(tmp_path, "code-reviewer", description="d", content="You are a reviewer.")
    manager = SubagentManager([tmp_path])
    parent = Agent(llm=FakeLLM([_response(content="found issues")]), tools=[multiply])
    task_tool = make_task_tool(manager, parent)
    result = task_tool.execute({"prompt": "review", "agent_type": "code-reviewer"})
    assert result.ok is True
    assert result.data == "found issues"
