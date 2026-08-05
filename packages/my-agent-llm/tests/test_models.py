"""数据模型测试。"""
from my_agent_llm.models import Message, Response, StreamChunk


def test_message_fields():
    """Message：role/content/metadata。"""
    m = Message(role="user", content="hi")
    assert m.role == "user"
    assert m.content == "hi"
    assert m.metadata is None


def test_message_metadata_tool_calls():
    """Message.metadata 承载 tool_calls。"""
    m = Message(role="assistant", content="", metadata={"tool_calls": [{"id": "1"}]})
    assert m.metadata["tool_calls"] == [{"id": "1"}]


def test_response_fields():
    """Response：content/model/tool_calls/reasoning/usage/finish_reason。"""
    r = Response(
        content="hi",
        model="gpt-4.1-mini",
        tool_calls=[{"id": "1", "type": "function", "function": {"name": "f", "arguments": "{}"}}],
        reasoning_content="think",
        usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        finish_reason="stop",
    )
    assert r.content == "hi"
    assert r.reasoning_content == "think"


def test_stream_chunk_tool_calls_optional():
    """StreamChunk：content 必填，tool_calls 可选。"""
    c = StreamChunk(content="delta")
    assert c.tool_calls is None
    assert c.metadata is None


def test_stream_chunk_metadata_reasoning():
    """StreamChunk.metadata 承载流式 reasoning。"""
    c = StreamChunk(content="", metadata={"reasoning_content": "think"})
    assert c.metadata["reasoning_content"] == "think"
