from __future__ import annotations

from pathlib import Path

from my_agent_core.events import (
    AgentEnd,
    AgentStart,
    MessageEnd,
    ToolExecutionEnd,
    ToolExecutionStart,
    TurnEnd,
    TurnStart,
)
from my_agent_llm import Message
from my_coding_agent.tracer import DebugEventTracer, export_debug_dump


def test_tracer_logs_lifecycle_events(tmp_path: Path) -> None:
    log_file = tmp_path / "debug.log"
    tracer = DebugEventTracer(log_path=log_file)

    # 1. 发射 AgentStart
    tracer(AgentStart(system_prompt="sys prompt", user_input="hello world"))

    # 2. 发射 TurnStart
    tracer(TurnStart(iteration=1))

    # 3. 发射 ToolExecutionStart 与 ToolExecutionEnd
    call_id = "call-123"
    tracer(
        ToolExecutionStart(
            tool_call_id=call_id,
            tool_name="read",
            args={"path": "test.txt", "api_key": "sk-secret-12345"},
        )
    )
    tracer(
        ToolExecutionEnd(
            tool_call_id=call_id,
            tool_name="read",
            result="file content",
            is_error=False,
        )
    )

    # 4. 发射 MessageEnd
    msg = Message(
        role="assistant",
        content="done",
        metadata={"usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}},
    )
    tracer(MessageEnd(message=msg))

    # 5. 发射 TurnEnd 与 AgentEnd
    tracer(TurnEnd())
    tracer(AgentEnd(messages=[msg], iterations=1, stop_reason="end_turn", final_text="done"))

    tracer.close()

    assert log_file.is_file()
    content = log_file.read_text(encoding="utf-8")

    assert "[AGENT_START]" in content
    assert "hello world" in content
    assert "[TURN_START] iteration=1" in content
    assert "[TOOL_CALL_START] tool=read" in content
    assert "***REDACTED***" in content  # api_key 脱敏验证
    assert "sk-secret-12345" not in content  # 原始密钥未泄漏
    assert "[TOOL_CALL_END] tool=read" in content
    assert "[LLM_RESPONSE]" in content
    assert "[AGENT_END]" in content


def test_export_debug_dump(tmp_path: Path) -> None:
    class DummyAgent:
        class Inner:
            model = "gpt-4o"
            system_prompt = "system instructions"
            messages = [Message(role="user", content="hi"), Message(role="assistant", content="hello")]
            registry = {"read": object(), "write": object()}

        agent = Inner()
        workspace = str(tmp_path)

    dump_file = tmp_path / "dump.json"
    data = export_debug_dump(DummyAgent(), dump_file)

    assert dump_file.is_file()
    assert data["model"] == "gpt-4o"
    assert data["system_prompt"] == "system instructions"
    assert len(data["messages"]) == 2
    assert "read" in data["registered_tools"]
    assert "write" in data["registered_tools"]
