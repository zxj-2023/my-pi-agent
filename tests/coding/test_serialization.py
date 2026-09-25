from __future__ import annotations

import uuid

from my_agent_core.events import (
    MessageUpdate,
    ToolExecutionEnd,
    ToolExecutionStart,
)
from my_agent_llm import Message
from my_agent_llm.models import StreamChunk
from my_coding_agent.serialization import (
    serialize_event,
    serialize_message,
    uuid7_str,
)


def test_uuid7_str() -> None:
    u = uuid7_str()
    assert isinstance(u, str)
    parsed = uuid.UUID(u)
    assert parsed.version == 7


def test_serialize_message() -> None:
    msg = Message(role="assistant", content="hello", metadata={"tool_calls": [{"name": "read"}]})
    data = serialize_message(msg)
    assert data["role"] == "assistant"
    assert data["content"] == "hello"
    assert data["metadata"]["tool_calls"] == [{"name": "read"}]


def test_serialize_event_message_update() -> None:
    msg = Message(role="assistant", content="chunk")
    chunk = StreamChunk(content="delta")
    ev = MessageUpdate(message=msg, chunk=chunk)
    payload = serialize_event(ev)
    assert payload["type"] == "message_update"
    assert payload["message"]["role"] == "assistant"
    assert payload["delta"] == "delta"


def test_serialize_event_tool_execution() -> None:
    start_ev = ToolExecutionStart(tool_call_id="call-1", tool_name="bash", args={"cmd": "ls"})
    start_data = serialize_event(start_ev)
    assert start_data["type"] == "tool_execution_start"
    assert start_data["toolName"] == "bash"

    end_ev = ToolExecutionEnd(tool_call_id="call-1", tool_name="bash", result="file.txt", is_error=False)
    end_data = serialize_event(end_ev)
    assert end_data["type"] == "tool_execution_end"
    assert end_data["result"] == "file.txt"


def test_serialize_auto_retry_events() -> None:
    from my_agent_core.events import AutoRetryEnd, AutoRetryStart

    start_ev = AutoRetryStart(attempt=1, max_attempts=3, delay_ms=2000, error_message="Rate limit 429")
    start_payload = serialize_event(start_ev)
    assert start_payload["type"] == "auto_retry_start"
    assert start_payload["attempt"] == 1
    assert start_payload["maxAttempts"] == 3
    assert start_payload["delayMs"] == 2000
    assert start_payload["errorMessage"] == "Rate limit 429"

    end_ev = AutoRetryEnd(success=True, attempt=1)
    end_payload = serialize_event(end_ev)
    assert end_payload["type"] == "auto_retry_end"
    assert end_payload["success"] is True
    assert end_payload["attempt"] == 1
    assert end_payload["finalError"] == ""
