"""extension 机制离线测试（替身 Agent，不碰真网络）。"""
from pathlib import Path

import pytest

from my_agent_core.events import AgentStart, HookRegistry, HookResult, ToolExecutionStart
from my_agent_core.extensions import ExtensionAPI, ExtensionManager
from my_agent_core.registry import ToolRegistry
from my_agent_core.tools import tool


class _FakeAgent:
    """替身 Agent：只有 extension 需要的 hooks + registry。"""

    def __init__(self):
        self.hooks = HookRegistry()
        self.registry = ToolRegistry()


@pytest.fixture
def agent():
    return _FakeAgent()


@pytest.fixture
def manager(agent):
    return ExtensionManager(agent, extension_dirs=[])


def test_on_register_and_emit(agent):
    """on 注册 + 触发，handler 收 (event, api) 双参（#1）。"""
    api = ExtensionAPI(agent)
    seen = []

    api.on(ToolExecutionStart, lambda e, a: seen.append((e, a is api)))

    agent.hooks.emit(ToolExecutionStart("id1", "t", {"a": 1}))
    assert len(seen) == 1
    assert seen[0][0].tool_name == "t"
    assert seen[0][1] is True


def test_on_decorator(agent):
    """@api.on(EventCls) 装饰器语法（#2）。"""
    api = ExtensionAPI(agent)
    seen = []

    @api.on(AgentStart)
    def handler(event, api):
        seen.append(event)

    agent.hooks.emit(AgentStart())
    assert len(seen) == 1


def test_on_intercept(agent):
    """handler 返回 HookResult 被短路返回（#3）。"""
    api = ExtensionAPI(agent)

    @api.on(ToolExecutionStart)
    def block(event, api):
        return HookResult(block=True, reason="no")

    result = agent.hooks.emit(ToolExecutionStart("id1", "t", {}))
    assert isinstance(result, HookResult)
    assert result.block is True


def test_register_tool(agent):
    """register_tool 委托 registry（#4）。"""
    api = ExtensionAPI(agent)

    @tool
    def double(x: int) -> int:
        """Double x."""
        return x * 2

    api.register_tool(double)
    assert agent.registry.get("double") is double


def test_tool_decorator(agent):
    """@api.tool(description=...) 注册 + schema description 正确（#5）。"""
    api = ExtensionAPI(agent)

    @api.tool(description="Triple a number")
    def triple(x: int) -> int:
        """Triple x."""
        return x * 3

    assert agent.registry.get("triple") is not None
    assert agent.registry.get("triple").description == "Triple a number"


def test_register_command_and_get(agent):
    """register_command + get_commands（#6）。"""
    api = ExtensionAPI(agent)
    api.register_command("hello", lambda: "hi", "Say hi")
    assert api.get_commands()["hello"]() == "hi"


def test_command_decorator(agent):
    """@api.command(name) 装饰器（#7）。"""
    api = ExtensionAPI(agent)

    @api.command("stats")
    def stats():
        return "stats"

    assert "stats" in api.get_commands()


def test_handle_command_no_args(agent):
    """handle_command 调用 0 参 handler（#8）。"""
    manager = ExtensionManager(agent, extension_dirs=[])

    @manager.api.command("zero")
    def zero():
        return "zero"

    assert manager.handle_command("zero") == "zero"


def test_handle_command_with_args(agent):
    """handle_command 调用收 args 的 handler（#9）。"""
    manager = ExtensionManager(agent, extension_dirs=[])

    @manager.api.command("echo")
    def echo(args):
        return f"echo:{args}"

    assert manager.handle_command("echo", "hello") == "echo:hello"


def test_handle_command_unknown(agent):
    """未知命令 → ValueError（#10）。"""
    manager = ExtensionManager(agent, extension_dirs=[])
    with pytest.raises(ValueError, match="Unknown command"):
        manager.handle_command("nope")


def test_load_extension(tmp_path, agent):
    """load_extension 加载 .py，工具进 registry、命令可查（#11）。"""
    manager = ExtensionManager(agent, extension_dirs=[])
    ext = tmp_path / "my_ext.py"
    ext.write_text('''
def extension(api):
    @api.tool(description="Double a number")
    def double(x: int) -> int:
        """Double x."""
        return x * 2

    @api.command("hello")
    def hello_cmd():
        return "Hello!"
''', encoding="utf-8")

    manager.load_extension(ext)
    assert agent.registry.get("double") is not None
    assert manager.handle_command("hello") == "Hello!"


def test_load_extension_missing_func(tmp_path, agent):
    """无 extension 函数 → ValueError（#12）。"""
    manager = ExtensionManager(agent, extension_dirs=[])
    ext = tmp_path / "bad.py"
    ext.write_text("x = 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="extension"):
        manager.load_extension(ext)


def test_discover_skips_private(tmp_path, agent):
    """discover 跳过 _ 开头私有文件（#13）。"""
    manager = ExtensionManager(agent, extension_dirs=[])
    ext_dir = tmp_path / "exts"
    ext_dir.mkdir()
    (ext_dir / "a.py").write_text("def extension(api): pass\n", encoding="utf-8")
    (ext_dir / "_private.py").write_text("def extension(api): pass\n", encoding="utf-8")
    found = manager.discover(ext_dir)
    assert [p.name for p in found] == ["a.py"]


def test_load_isolates_bad(tmp_path, agent, capsys):
    """load 隔离坏扩展：好的照常加载、坏的 print 警告不抛（#14）。"""
    ext_dir = tmp_path / "exts"
    ext_dir.mkdir()
    (ext_dir / "good.py").write_text('''
def extension(api):
    @api.command("ok")
    def ok():
        return "ok"
''', encoding="utf-8")
    (ext_dir / "bad.py").write_text("x = 1\n", encoding="utf-8")  # 无 extension 函数

    manager = ExtensionManager(agent, extension_dirs=[ext_dir])
    manager.load()
    assert manager.handle_command("ok") == "ok"
    assert "Failed to load extension" in capsys.readouterr().out


# ── 端到端（FakeLLM 驱动，extension 经 Agent 装配生效）──────────────

import tempfile

from my_agent_llm import Response

from my_agent_core.agent import Agent
from my_agent_core.session import Session


class _FakeLLM:
    """替身：chat 按脚本返回 Response，记录 tools。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def chat(self, *, messages, tools=None, **kwargs):
        self.calls.append({"tools": tools})
        return self.responses.pop(0)


def _resp(content="", tool_calls=None):
    return Response(content=content, model="fake", tool_calls=tool_calls)


def _make_agent(llm, tmp_path, extension_dirs):
    session = Session(path=tmp_path / "s.jsonl")
    return Agent(llm=llm, tools=[], session=session, extension_dirs=extension_dirs)


def test_extension_tool_end_to_end(tmp_path):
    """extension 注册的工具在 run() 中被模型调用（#15）。"""
    ext_dir = tmp_path / "exts"
    ext_dir.mkdir()
    (ext_dir / "my_ext.py").write_text('''
def extension(api):
    @api.tool(description="Double a number")
    def double(x: int) -> int:
        """Double x."""
        return x * 2
''', encoding="utf-8")

    tc = [{"id": "1", "type": "function", "function": {"name": "double", "arguments": '{"x": 5}'}}]
    llm = _FakeLLM([_resp(tool_calls=tc), _resp(content="10")])
    agent = _make_agent(llm, tmp_path, extension_dirs=[ext_dir])

    answer = agent.run("double 5")
    assert answer == "10"
    # 第一轮 tools 含 extension 工具
    assert any(t["function"]["name"] == "double" for t in llm.calls[0]["tools"])


def test_extension_hook_end_to_end(tmp_path):
    """extension 注册的 ToolExecutionStart hook 在 run() 中拦截工具（#16）。"""
    ext_dir = tmp_path / "exts"
    ext_dir.mkdir()
    (ext_dir / "blocker.py").write_text('''
from my_agent_core.events import HookResult, ToolExecutionStart

def extension(api):
    @api.on(ToolExecutionStart)
    def block(event, api):
        return HookResult(block=True, reason="extension blocked")
''', encoding="utf-8")

    # 工具被拦后模型收到 "blocked" 观察，直接结束
    tc = [{"id": "1", "type": "function", "function": {"name": "double", "arguments": '{"x": 5}'}}]
    llm = _FakeLLM([_resp(tool_calls=tc), _resp(content="done")])
    agent = _make_agent(llm, tmp_path, extension_dirs=[ext_dir])

    answer = agent.run("double 5")
    assert answer == "done"
    # session 里出现被拦观察
    contents = [m.content for m in agent.session.get_full_history_messages()]
    assert any("extension blocked" in c for c in contents)
