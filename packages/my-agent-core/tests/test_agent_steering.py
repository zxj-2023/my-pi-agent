import pytest
from my_agent_llm import Response

from my_agent_core.agent import Agent
from my_agent_core.session_store import SessionStore
from my_agent_core.tools import tool


class SequenceFakeLLM:
    """按顺序返回预置响应的 FakeLLM。"""

    def __init__(self, responses: list[Response]):
        self.responses = list(responses)
        self.call_count = 0
        self.received_messages: list[list] = []

    async def achat_stream(self, messages, tools=None, model=None):
        self.received_messages.append(list(messages))
        if self.responses:
            resp = self.responses.pop(0)
        else:
            resp = Response(content="Default answer", model="fake")
        self.call_count += 1
        yield resp


@pytest.mark.anyio
async def test_agent_steer_during_tool_execution(tmp_path):
    """测试在工具执行阶段注入 steer 消息，大模型在下一轮感知并调整。"""
    store = SessionStore(tmp_path)
    session = store.create()

    agent_ref = {}

    @tool(name="search", description="搜索工具")
    def search(query: str) -> str:
        # 在工具执行期间用户插入 steering
        if "agent" in agent_ref:
            agent_ref["agent"].steer("请停止搜索，直接回答结果是 42")
        return "Found raw data: 123"

    responses = [
        # Round 1: 尝试调用工具 search
        Response(
            content="Let me search",
            model="fake",
            tool_calls=[
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "search", "arguments": '{"query": "test"}'},
                }
            ],
        ),
        # Round 2: 收到 tool_result 和 steering 消息后的最终回答
        Response(content="结果是 42", model="fake"),
    ]

    llm = SequenceFakeLLM(responses)
    agent = Agent(
        llm=llm,
        session=session,
        tools=[search],
        skill_dirs=[],
        subagent_dirs=[],
        memory_dir=False,
        plugin_dirs=[],
    )
    agent_ref["agent"] = agent

    final = await agent.run("请帮我查一下数据")
    assert final == "结果是 42"
    assert llm.call_count == 2

    # 验证 Round 2 收到的 messages 包含了 user 的 steering 消息
    r2_messages = llm.received_messages[1]
    assert any(m.role == "tool" and "Found raw data" in m.content for m in r2_messages)
    assert any(m.role == "user" and "请停止搜索" in m.content for m in r2_messages)

    # 验证 session 树中持久化了 steering 消息
    session_messages = session.get_current_path_messages()
    contents = [m.content for m in session_messages]
    assert "请帮我查一下数据" in contents
    assert "Found raw data: 123" in contents
    assert "请停止搜索，直接回答结果是 42" in contents
    assert "结果是 42" in contents


@pytest.mark.anyio
async def test_agent_steer_during_final_text(tmp_path):
    """测试当大模型给出无工具文本时，若检测到流式期间有 steer，不退出并继续作答。"""
    store = SessionStore(tmp_path)
    session = store.create()

    class StreamingSteerLLM:
        def __init__(self, agent_holder):
            self.agent_holder = agent_holder
            self.turn = 0

        async def achat_stream(self, messages, tools=None, model=None):
            self.turn += 1
            if self.turn == 1:
                # 模拟流式输出期间用户 steer
                self.agent_holder["agent"].steer("请补充原理说明")
                yield Response(content="初步结论为 A", model="fake")
            else:
                yield Response(content="补充原理：A 是基于 X 原理", model="fake")

    agent_holder = {}
    llm = StreamingSteerLLM(agent_holder)
    agent = Agent(
        llm=llm,
        session=session,
        tools=[],
        skill_dirs=[],
        subagent_dirs=[],
        memory_dir=False,
        plugin_dirs=[],
    )
    agent_holder["agent"] = agent

    final = await agent.run("请给出结论")
    assert final == "补充原理：A 是基于 X 原理"
    assert llm.turn == 2

    session_messages = session.get_current_path_messages()
    contents = [m.content for m in session_messages]
    assert "请给出结论" in contents
    assert "初步结论为 A" in contents
    assert "请补充原理说明" in contents
    assert "补充原理：A 是基于 X 原理" in contents


@pytest.mark.anyio
async def test_agent_follow_up_continuation(tmp_path):
    """测试外层循环自动消费 follow_up 追问消息。"""
    store = SessionStore(tmp_path)
    session = store.create()

    responses = [
        Response(content="任务 A 完成", model="fake"),
        Response(content="任务 B 完成", model="fake"),
    ]
    llm = SequenceFakeLLM(responses)
    agent = Agent(
        llm=llm,
        session=session,
        tools=[],
        skill_dirs=[],
        subagent_dirs=[],
        memory_dir=False,
        plugin_dirs=[],
    )

    # 在 run 启动前或执行前注入 follow_up
    agent.follow_up("接下来执行任务 B")

    final = await agent.run("首先执行任务 A")
    assert final == "任务 B 完成"
    assert llm.call_count == 2

    # 验证 session 完整持久化了两段对话
    current_msgs = session.get_current_path_messages()
    contents = [m.content for m in current_msgs]
    assert "首先执行任务 A" in contents
    assert "任务 A 完成" in contents
    assert "接下来执行任务 B" in contents
    assert "任务 B 完成" in contents


@pytest.mark.anyio
async def test_agent_steering_mode_all(tmp_path):
    """测试 steering_mode='all' 模式下一次性注入多条 steering。"""
    store = SessionStore(tmp_path)
    session = store.create()

    agent_ref = {}

    @tool(name="step_tool", description="步骤工具")
    def step_tool() -> str:
        if "agent" in agent_ref:
            agent_ref["agent"].steer("Steer 1")
            agent_ref["agent"].steer("Steer 2")
        return "done"

    responses = [
        Response(
            content="",
            model="fake",
            tool_calls=[
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "step_tool", "arguments": "{}"},
                }
            ],
        ),
        Response(content="Handled both steers", model="fake"),
    ]
    llm = SequenceFakeLLM(responses)
    agent = Agent(
        llm=llm,
        session=session,
        tools=[step_tool],
        steering_mode="all",
        skill_dirs=[],
        subagent_dirs=[],
        memory_dir=False,
        plugin_dirs=[],
    )
    agent_ref["agent"] = agent

    final = await agent.run("start")
    assert final == "Handled both steers"
    assert llm.call_count == 2

    # Round 2 应一次性包含 Steer 1 和 Steer 2
    r2_messages = llm.received_messages[1]
    user_contents = [m.content for m in r2_messages if m.role == "user"]
    assert "Steer 1" in user_contents
    assert "Steer 2" in user_contents


@pytest.mark.anyio
async def test_agent_abort_clears_queue(tmp_path):
    """测试 abort 取消时清空未决队列并退出。"""
    store = SessionStore(tmp_path)
    session = store.create()

    agent_holder = {}

    class AbortLLM:
        async def achat_stream(self, messages, tools=None, model=None):
            agent_holder["agent"].follow_up("Should not run")
            agent_holder["agent"].abort()
            yield Response(content="aborting", model="fake")

    llm = AbortLLM()
    agent = Agent(
        llm=llm,
        session=session,
        tools=[],
        skill_dirs=[],
        subagent_dirs=[],
        memory_dir=False,
        plugin_dirs=[],
    )
    agent_holder["agent"] = agent

    res = await agent.run("hello")
    assert res == "(cancelled)"
    assert len(agent.message_queue) == 0
