"""单元测试：对话转录本自愈与断头保护引擎 (tool_history.py)"""

from typing import Any

from my_agent_core.tool_history import (
    _INTERRUPTED_TOOL_RESULT,
    repair_tool_history,
)
from my_agent_llm.models import Message


def _make_tc(call_id: str, name: str = "bash", args: str = "{}") -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": args},
    }


def test_repair_clean_history_unchanged():
    """正常完备的工具调用历史：完全不改动。"""
    messages = [
        Message(role="user", content="Hello"),
        Message(
            role="assistant",
            content="Running tool",
            metadata={"tool_calls": [_make_tc("call_1")]},
        ),
        Message(
            role="tool",
            content="output 1",
            metadata={"tool_call_id": "call_1"},
        ),
        Message(role="assistant", content="Done"),
    ]
    repair = repair_tool_history(messages)
    assert not repair.changed
    assert repair.messages == tuple(messages)
    assert repair.synthesized_results == 0
    assert repair.dropped_orphan_results == 0
    assert repair.dropped_duplicate_results == 0
    assert repair.reordered_results == 0


def test_repair_synthesizes_interrupted_tool_call():
    """断头悬空调用（如用户 Ctrl+C 中止）：自动合成中断结果。"""
    messages = [
        Message(role="user", content="Do task"),
        Message(
            role="assistant",
            content="I will run bash",
            metadata={"tool_calls": [_make_tc("call_1")]},
        ),
        # 此时程序被中断，没有任何 tool 消息
    ]
    repair = repair_tool_history(messages)
    assert repair.changed
    assert len(repair.messages) == 3
    assert repair.synthesized_results == 1

    synth_msg = repair.messages[2]
    assert synth_msg.role == "tool"
    assert synth_msg.content == _INTERRUPTED_TOOL_RESULT
    assert synth_msg.metadata is not None
    assert synth_msg.metadata["tool_call_id"] == "call_1"
    assert synth_msg.metadata.get("is_error")


def test_repair_multiple_dangling_tool_calls():
    """同一个 Assistant 消息发起了多个并发工具调用，中途中止：全部保序补齐。"""
    messages = [
        Message(
            role="assistant",
            content="",
            metadata={"tool_calls": [_make_tc("c1"), _make_tc("c2"), _make_tc("c3")]},
        )
    ]
    repair = repair_tool_history(messages)
    assert repair.changed
    assert len(repair.messages) == 4
    assert repair.synthesized_results == 3

    assert repair.messages[1].metadata is not None and repair.messages[1].metadata["tool_call_id"] == "c1"
    assert repair.messages[2].metadata is not None and repair.messages[2].metadata["tool_call_id"] == "c2"
    assert repair.messages[3].metadata is not None and repair.messages[3].metadata["tool_call_id"] == "c3"
    for i in (1, 2, 3):
        assert repair.messages[i].content == _INTERRUPTED_TOOL_RESULT


def test_repair_drops_orphan_tool_result():
    """孤儿工具结果（未匹配任何 Assistant tool_call）：自动丢弃。"""
    messages = [
        Message(role="user", content="Hi"),
        Message(
            role="tool",
            content="orphan output",
            metadata={"tool_call_id": "ghost_call"},
        ),
        Message(role="assistant", content="Hello"),
    ]
    repair = repair_tool_history(messages)
    assert repair.changed
    assert len(repair.messages) == 2
    assert repair.dropped_orphan_results == 1
    assert [m.role for m in repair.messages] == ["user", "assistant"]


def test_repair_reorders_misplaced_tool_result():
    """工具结果与调用顺序颠倒或被插队：自动重排至紧邻 Assistant 之后。"""
    messages = [
        Message(
            role="assistant",
            content="call 1",
            metadata={"tool_calls": [_make_tc("c1")]},
        ),
        Message(role="user", content="irrelevant interrupt"),
        Message(
            role="tool",
            content="output c1",
            metadata={"tool_call_id": "c1"},
        ),
    ]
    repair = repair_tool_history(messages)
    assert repair.changed
    assert len(repair.messages) == 3
    assert repair.reordered_results == 1

    # 验证 c1 的 tool 结果被移动到 assistant 之后，紧接着才是 user 消息
    assert repair.messages[0].role == "assistant"
    assert repair.messages[1].role == "tool"
    assert repair.messages[1].metadata is not None and repair.messages[1].metadata["tool_call_id"] == "c1"
    assert repair.messages[2].role == "user"


def test_repair_handles_repeated_tool_call_ids():
    """模型在不同轮次复用同一个 tool_call_id：Phase 1 优先就近预留，杜绝错配抢夺。"""
    messages = [
        # Turn 1
        Message(
            role="assistant",
            content="Turn 1",
            metadata={"tool_calls": [_make_tc("dup_id")]},
        ),
        Message(
            role="tool",
            content="output 1",
            metadata={"tool_call_id": "dup_id"},
        ),
        # Turn 2
        Message(
            role="assistant",
            content="Turn 2",
            metadata={"tool_calls": [_make_tc("dup_id")]},
        ),
        Message(
            role="tool",
            content="output 2",
            metadata={"tool_call_id": "dup_id"},
        ),
    ]
    repair = repair_tool_history(messages)
    assert not repair.changed
    assert repair.messages[1].content == "output 1"
    assert repair.messages[3].content == "output 2"


def test_repair_diagnostic_data():
    """验证诊断信息正确返回字典。"""
    messages = [
        Message(
            role="assistant",
            content="",
            metadata={"tool_calls": [_make_tc("c1")]},
        ),
        Message(role="tool", content="ghost", metadata={"tool_call_id": "orphan"}),
    ]
    repair = repair_tool_history(messages)
    diag = repair.diagnostic_data()
    assert diag["synthesizedResults"] == 1
    assert diag["droppedOrphanResults"] == 1


class AbortMockLLM:
    def __init__(self):
        self.turns = 0
        self.agent = None

    async def achat_stream(self, messages, tools=None, **kwargs):
        self.turns += 1
        if self.turns == 1:
            from my_agent_llm.models import StreamChunk
            yield StreamChunk(
                content="I will run tool",
                tool_calls=[_make_tc("call_aborted", "test_tool")],
            )
            # 在返回首个块并携带 tool_calls 后触发 abort
            if self.agent is not None:
                self.agent.abort()
            yield StreamChunk(content="")
        else:
            from my_agent_llm.models import StreamChunk
            yield StreamChunk(content="Recovered successfully")


def test_agent_aborted_with_tool_calls_repaired(tmp_path):
    """验证 Agent 在被 abort 取消后，悬空的 tool_calls 会被立即自愈补齐，后续交互安全恢复。"""
    async def _test():
        from my_agent_core.agent import Agent
        from my_agent_core.session import Session

        session = Session(path=tmp_path / "session.jsonl")
        llm: Any = AbortMockLLM()
        agent = Agent(
            llm=llm,
            session=session,
            tools=[],
            system_prompt="sys",
            memory_dir=False,
            task_store=False,
        )
        llm.agent = agent

        # 执行 run，在第一轮中途被 abort
        res = await agent.run("Start")
        assert res == "(cancelled)"

        # 验证会话中悬空的工具调用被即刻自愈补齐为中断结果
        tool_msgs = [m for m in session.get_current_path_messages() if m.role == "tool"]
        assert len(tool_msgs) == 1
        assert tool_msgs[0].content == _INTERRUPTED_TOOL_RESULT
        assert tool_msgs[0].metadata is not None and tool_msgs[0].metadata["tool_call_id"] == "call_aborted"

        # 续跑恢复：下一轮能够顺利恢复，不会因悬空工具调用报 API 400 异常
        agent._aborted = False
        res2 = await agent.run("Continue")
        assert res2 == "Recovered successfully"

    import asyncio
    asyncio.run(_test())
