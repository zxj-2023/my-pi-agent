"""extension 机制离线测试（替身 Agent，不碰真网络）。"""

import pytest
from my_agent_llm import Response  # pyright: ignore[reportMissingImports]

from my_agent_core.agent import Agent
from my_agent_core.events import (
    AgentStart,
    HookRegistry,
    HookResult,
    ToolExecutionStart,
)
from my_agent_core.extensions import ExtensionAPI, ExtensionManager
from my_agent_core.registry import ToolRegistry
from my_agent_core.session import Session
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


@pytest.mark.anyio
async def test_on_register_and_emit(agent):
    """on 注册 + 触发，handler 收 (event, api) 双参（#1）。"""
    api = ExtensionAPI(agent)
    seen = []

    api.on(ToolExecutionStart, lambda e, a: seen.append((e, a is api)))

    await agent.hooks.emit(ToolExecutionStart("id1", "t", {"a": 1}))
    assert len(seen) == 1
    assert seen[0][0].tool_name == "t"
    assert seen[0][1] is True


@pytest.mark.anyio
async def test_on_decorator(agent):
    """@api.on(EventCls) 装饰器语法（#2）。"""
    api = ExtensionAPI(agent)
    seen = []

    @api.on(AgentStart)
    def handler(event, api):
        seen.append(event)

    await agent.hooks.emit(AgentStart())
    assert len(seen) == 1


@pytest.mark.anyio
async def test_on_intercept(agent):
    """handler 返回 HookResult 被短路返回（#3）。"""
    api = ExtensionAPI(agent)

    @api.on(ToolExecutionStart)
    def block(event, api):
        return HookResult(block=True, reason="no")

    result = await agent.hooks.emit(ToolExecutionStart("id1", "t", {}))
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


@pytest.mark.anyio
async def test_load_extension(tmp_path, agent):
    """load_extension 加载 .py，工具进 registry、命令可查（#11）。"""
    manager = ExtensionManager(agent, extension_dirs=[])
    ext = tmp_path / "my_ext.py"
    ext.write_text(
        "def extension(api):\n"
        "    @api.tool(description='Double a number')\n"
        "    def double(x: int) -> int:\n"
        "        'Double x.'\n"
        "        return x * 2\n"
        "    @api.command('hello')\n"
        "    def hello_cmd():\n"
        "        return 'Hello!'\n",
        encoding="utf-8",
    )

    await manager.load_extension(ext)
    assert agent.registry.get("double") is not None
    assert manager.handle_command("hello") == "Hello!"


@pytest.mark.anyio
async def test_load_extension_missing_func(tmp_path, agent):
    """无 extension 函数 → ValueError（#12）。"""
    manager = ExtensionManager(agent, extension_dirs=[])
    ext = tmp_path / "bad.py"
    ext.write_text("x = 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="extension"):
        await manager.load_extension(ext)


def test_discover_skips_private(tmp_path, agent):
    """discover 跳过 _ 开头私有文件（#13）。"""
    manager = ExtensionManager(agent, extension_dirs=[])
    ext_dir = tmp_path / "exts"
    ext_dir.mkdir()
    (ext_dir / "a.py").write_text("def extension(api): pass\n", encoding="utf-8")
    (ext_dir / "_private.py").write_text("def extension(api): pass\n", encoding="utf-8")
    found = manager.discover(ext_dir)
    assert [p.name for p in found] == ["a.py"]


@pytest.mark.anyio
async def test_load_isolates_bad(tmp_path, agent, capsys):
    """load 隔离坏扩展：好的照常加载、坏的 print 警告不抛（#14）。"""
    ext_dir = tmp_path / "exts"
    ext_dir.mkdir()
    (ext_dir / "good.py").write_text(
        """
def extension(api):
    @api.command("ok")
    def ok():
        return "ok"
""",
        encoding="utf-8",
    )
    (ext_dir / "bad.py").write_text("x = 1\n", encoding="utf-8")  # 无 extension 函数

    manager = ExtensionManager(agent, extension_dirs=[ext_dir])
    await manager.load()
    assert manager.handle_command("ok") == "ok"
    assert "Failed to load extension" in capsys.readouterr().out


# ── 端到端（FakeLLM 驱动，extension 经 Agent 装配生效）──────────────


class _FakeLLM:
    """替身：chat/achat 按脚本返回 Response，记录 tools 和 messages。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def achat_stream(self, *, messages, tools=None, **kwargs):
        self.calls.append({"messages": list(messages), "tools": tools})
        yield self.responses.pop(0)

    async def achat(self, *, messages, tools=None, **kwargs):
        self.calls.append({"messages": list(messages), "tools": tools})
        return self.responses.pop(0)

    def chat(self, *, messages, tools=None, **kwargs):
        self.calls.append({"messages": list(messages), "tools": tools})
        return self.responses.pop(0)


def _resp(content="", tool_calls=None):
    return Response(content=content, model="fake", tool_calls=tool_calls)


def _make_agent(llm, tmp_path, extension_dirs):
    session = Session(path=tmp_path / "s.jsonl")
    return Agent(llm=llm, tools=[], session=session, extension_dirs=extension_dirs)


@pytest.mark.anyio
async def test_extension_tool_end_to_end(tmp_path):
    """extension 注册的工具在 run() 中被模型调用（#15）。"""
    ext_dir = tmp_path / "exts"
    ext_dir.mkdir()
    (ext_dir / "my_ext.py").write_text(
        """
def extension(api):
    @api.tool(description="Double a number")
    def double(x: int) -> int:
        \"\"\"Double x.\"\"\"
        return x * 2
""",
        encoding="utf-8",
    )

    tc = [
        {
            "id": "1",
            "type": "function",
            "function": {"name": "double", "arguments": '{"x": 5}'},
        }
    ]
    llm = _FakeLLM([_resp(tool_calls=tc), _resp(content="10")])
    agent = _make_agent(llm, tmp_path, extension_dirs=[ext_dir])

    answer = await agent.run("double 5")
    assert answer == "10"
    # 第一轮 tools 含 extension 工具
    assert any(t["function"]["name"] == "double" for t in llm.calls[0]["tools"])


@pytest.mark.anyio
async def test_extension_hook_end_to_end(tmp_path):
    """extension 注册的 ToolExecutionStart hook 在 run() 中拦截工具（#16）。"""
    ext_dir = tmp_path / "exts"
    ext_dir.mkdir()
    (ext_dir / "blocker.py").write_text(
        """
from my_agent_core.events import HookResult, ToolExecutionStart

def extension(api):
    @api.on(ToolExecutionStart)
    def block(event, api):
        return HookResult(block=True, reason="extension blocked")
""",
        encoding="utf-8",
    )

    # 工具被拦后模型收到 "blocked" 观察，直接结束
    tc = [
        {
            "id": "1",
            "type": "function",
            "function": {"name": "double", "arguments": '{"x": 5}'},
        }
    ]
    llm = _FakeLLM([_resp(tool_calls=tc), _resp(content="done")])
    agent = _make_agent(llm, tmp_path, extension_dirs=[ext_dir])

    answer = await agent.run("double 5")
    assert answer == "done"
    # session 里出现被拦观察
    contents = [m.content for m in agent.session.get_full_history_messages()]
    assert any("extension blocked" in c for c in contents)


@pytest.mark.anyio
async def test_extension_overrides_user_tool(tmp_path):
    """extension 后加载覆盖用户同名工具（spec §1 决策 8）。"""
    ext_dir = tmp_path / "exts"
    ext_dir.mkdir()
    (ext_dir / "override.py").write_text(
        """
def extension(api):
    @api.tool(description="Override double to x100")
    def double(x: int) -> int:
        \"\"\"Return x * 100.\"\"\"
        return x * 100
""",
        encoding="utf-8",
    )

    @tool
    def double(x: int) -> int:
        """Return x * 2."""
        return x * 2

    session = Session(path=tmp_path / "s.jsonl")
    agent = Agent(
        llm=_FakeLLM([]),
        tools=[double],
        session=session,
        extension_dirs=[ext_dir],
    )

    await agent.extension_manager.load()
    tool_entry = agent.registry.get("double")
    assert tool_entry is not None
    result = await tool_entry.execute({"x": 5})
    assert result.data == 500  # extension 版本 x*100，非用户 x*2


@pytest.mark.anyio
async def test_extension_decision_points_end_to_end(tmp_path):
    """Extension 经 UserInput / AgentStart / BeforeModelCall 完整干预生命周期。"""
    ext_dir = tmp_path / "exts"
    ext_dir.mkdir()
    (ext_dir / "lifecycle_guard.py").write_text(
        """
from my_agent_core.events import UserInput, AgentStart, BeforeModelCall, HookResult
from my_agent_llm import Message

def extension(api):
    @api.on(UserInput)
    def rewrite_input(event, api):
        if "bad_word" in event.input_text:
            return HookResult(updated_input=event.input_text.replace("bad_word", "good_word"))
        return None

    @api.on(AgentStart)
    def rewrite_system(event, api):
        return HookResult(updated_system_prompt="Guarded System Prompt")

    @api.on(BeforeModelCall)
    def inject_notice(event, api):
        ephemeral = Message(role="user", content="[EPHEMERAL WARNING]")
        return HookResult(updated_messages=list(event.messages) + [ephemeral])
""",
        encoding="utf-8",
    )

    llm = _FakeLLM([_resp(content="safe answer")])
    agent = _make_agent(llm, tmp_path, extension_dirs=[ext_dir])

    res = await agent.run("test bad_word")
    assert res == "safe answer"

    # 1. UserInput 改写生效：LLM 收到的 user prompt 中包含 good_word 而非 bad_word
    last_user_msg = [m for m in llm.calls[0]["messages"] if m.role == "user" and "[EPHEMERAL" not in m.content][-1]
    assert last_user_msg.content == "test good_word"

    # 2. AgentStart 改写生效：LLM 收到的 system prompt 为 Guarded System Prompt
    assert llm.calls[0]["messages"][0].content == "Guarded System Prompt"

    # 3. BeforeModelCall 临时注入生效：LLM 视图中包含 [EPHEMERAL WARNING]
    assert any("[EPHEMERAL WARNING]" in m.content for m in llm.calls[0]["messages"])

    # 4. Session 保持零污染：Session 磁盘绝不包含 [EPHEMERAL WARNING]
    session_contents = [e.content for e in agent.session.tree.entries.values()]
    assert not any("[EPHEMERAL WARNING]" in c for c in session_contents)
    assert any("test good_word" in c for c in session_contents)

