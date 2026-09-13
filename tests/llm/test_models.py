"""数据模型测试。"""

from my_agent_llm.models import (
    Message,
    Response,
    StreamChunk,
    ToolCall,
    TurnOutcome,
    normalize_finish_reason,
)


def test_message_fields():
    """Message：role/content/metadata。"""
    m = Message(role="user", content="hi")
    assert m.role == "user"
    assert m.content == "hi"
    assert m.metadata is None


def test_message_metadata_tool_calls():
    """Message.metadata 承载 tool_calls。"""
    m = Message(role="assistant", content="", metadata={"tool_calls": [{"id": "1"}]})
    assert m.metadata is not None
    assert m.metadata["tool_calls"] == [{"id": "1"}]


def test_response_fields():
    """Response：content/model/tool_calls/reasoning/usage/finish_reason。"""
    r = Response(
        content="hi",
        model="gpt-4.1-mini",
        tool_calls=[
            ToolCall.model_validate(
                {
                    "id": "1",
                    "type": "function",
                    "function": {"name": "f", "arguments": "{}"},
                }
            )
        ],
        reasoning_content="think",
        usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        finish_reason="stop",
    )
    assert r.content == "hi"
    assert r.reasoning_content == "think"
    assert r.outcome == TurnOutcome.TOOL_CALLS
    assert r.tool_calls is not None
    assert len(r.tool_calls) == 1
    assert r.tool_calls[0].name == "f"
    assert r.tool_calls[0].args == {}


def test_stream_chunk_tool_calls_optional():
    """StreamChunk：content 必填，tool_calls 可选。"""
    c = StreamChunk(content="delta")
    assert c.tool_calls is None
    assert c.metadata is None


def test_stream_chunk_metadata_reasoning():
    """StreamChunk.metadata 承载流式 reasoning。"""
    c = StreamChunk(content="", metadata={"reasoning_content": "think"})
    assert c.metadata is not None
    assert c.metadata["reasoning_content"] == "think"


def test_structured_tool_call_direct():
    """ToolCall：支持结构化原生实例化。"""
    tc = ToolCall(id="call_1", name="add", args={"a": 1, "b": 2})
    assert tc.id == "call_1"
    assert tc.name == "add"
    assert tc.args == {"a": 1, "b": 2}
    assert tc.error is None


def test_structured_tool_call_from_wire_dict():
    """ToolCall：支持从 OpenAI wire dict 反序列化并解析 JSON arguments。"""
    tc = ToolCall.model_validate(
        {
            "id": "call_2",
            "type": "function",
            "function": {"name": "calc", "arguments": '{"x": 42}'},
        }
    )
    assert tc.id == "call_2"
    assert tc.name == "calc"
    assert tc.args == {"x": 42}
    assert tc.error is None


def test_structured_tool_call_malformed_json():
    """ToolCall：畸形 JSON 不抛异常，记录错误并留空 args。"""
    tc = ToolCall.model_validate(
        {
            "id": "call_3",
            "type": "function",
            "function": {"name": "bad", "arguments": '{"x": 42'},
        }
    )
    assert tc.id == "call_3"
    assert tc.name == "bad"
    assert tc.args == {}
    assert tc.error is not None
    assert "Malformed JSON" in tc.error


def test_turn_outcome_normalization():
    """TurnOutcome：各大厂商的 finish_reason 正确映射为中立枚举。"""
    assert normalize_finish_reason("stop") == TurnOutcome.COMPLETED
    assert normalize_finish_reason("end_turn") == TurnOutcome.COMPLETED
    assert normalize_finish_reason("tool_calls") == TurnOutcome.TOOL_CALLS
    assert normalize_finish_reason("tool_use") == TurnOutcome.TOOL_CALLS
    assert normalize_finish_reason(None, has_tool_calls=True) == TurnOutcome.TOOL_CALLS
    assert normalize_finish_reason("length") == TurnOutcome.LENGTH
    assert normalize_finish_reason("max_tokens") == TurnOutcome.LENGTH
    assert normalize_finish_reason("content_filter") == TurnOutcome.CONTENT_FILTER
    assert normalize_finish_reason("safety") == TurnOutcome.CONTENT_FILTER
    assert normalize_finish_reason("cancelled") == TurnOutcome.ABORTED
    assert normalize_finish_reason("aborted") == TurnOutcome.ABORTED
    assert normalize_finish_reason("error") == TurnOutcome.PROVIDER_ERROR
    assert normalize_finish_reason("unknown_reason") == TurnOutcome.UNKNOWN


def test_response_to_message_with_structured_tool_calls():
    """Response.to_message：将结构化 ToolCall 转化为标准 Message 字典。"""
    r = Response(
        content="",
        model="gpt-4o",
        tool_calls=[ToolCall(id="call_99", name="grep", args={"pattern": "foo"})],
        finish_reason="tool_calls",
    )
    assert r.outcome == TurnOutcome.TOOL_CALLS
    msg = r.to_message()
    assert msg.role == "assistant"
    assert msg.metadata is not None
    assert msg.metadata["tool_calls"] == [
        {"id": "call_99", "name": "grep", "args": {"pattern": "foo"}, "error": None}
    ]
    assert msg.metadata["stop_reason"] == "tool_calls"
