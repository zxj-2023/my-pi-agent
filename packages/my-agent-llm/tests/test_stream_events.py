"""高阶流式事件模型测试（对标 Tau provider_events）。"""

from my_agent_llm.events import (  # pyright: ignore[reportMissingImports]
    StreamDoneEvent,
    StreamErrorEvent,
    StreamEvent,
    StreamStartEvent,
    TextDeltaEvent,
    ThinkingDeltaEvent,
    ToolCallDeltaEvent,
    ToolCallDoneEvent,
)
from my_agent_llm.models import (  # pyright: ignore[reportMissingImports]
    Message,
    ToolCall,
)


def test_stream_events_instantiation():
    """验证各流式事件的实例化与字段类型。"""
    msg = Message(role="assistant", content="")

    # 1. Start Event
    start = StreamStartEvent(partial=msg)
    assert isinstance(start, StreamEvent)
    assert start.partial == msg

    # 2. Text Delta Event
    partial_text = Message(role="assistant", content="hello")
    t_delta = TextDeltaEvent(delta="hello", partial=partial_text)
    assert t_delta.delta == "hello"
    assert t_delta.partial == partial_text

    # 3. Thinking Delta Event
    partial_thinking = Message(
        role="assistant",
        content="",
        metadata={"reasoning_content": "thinking..."},
    )
    th_delta = ThinkingDeltaEvent(delta="thinking...", partial=partial_thinking)
    assert th_delta.delta == "thinking..."
    assert th_delta.partial == partial_thinking

    # 4. Tool Call Delta Event
    tc_delta = ToolCallDeltaEvent(index=0, delta='{"a": 1}', partial=msg)
    assert tc_delta.index == 0
    assert tc_delta.delta == '{"a": 1}'

    # 5. Tool Call Done Event
    tc = ToolCall(id="call_1", name="calculator", args={"expr": "1+1"})
    tc_done = ToolCallDoneEvent(index=0, tool_call=tc, partial=msg)
    assert tc_done.index == 0
    assert tc_done.tool_call == tc

    # 6. Stream Done Event
    done_msg = Message(role="assistant", content="hello")
    done = StreamDoneEvent(message=done_msg, usage={"total_tokens": 42})
    assert done.message == done_msg
    assert done.usage == {"total_tokens": 42}

    # 7. Stream Error Event
    err_msg = Message(
        role="assistant",
        content="fail",
        metadata={"stop_reason": "error"},
    )
    exc = RuntimeError("network disconnected")
    err = StreamErrorEvent(error=err_msg, stop_reason="error", exc=exc)
    assert err.error == err_msg
    assert err.stop_reason == "error"
    assert err.exc == exc
