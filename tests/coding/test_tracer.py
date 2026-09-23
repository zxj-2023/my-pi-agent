from __future__ import annotations

from pathlib import Path

from my_agent_core.events import (
    AgentEnd,
    AgentStart,
    MessageEnd,
    MessageStart,
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


def test_tracer_dual_track_and_rebind(tmp_path: Path) -> None:
    session1_log = tmp_path / "s1.debug.log"
    session1_events = tmp_path / "s1.events.jsonl"
    tracer = DebugEventTracer(log_path=session1_log, events_path=session1_events)

    msg = Message(role="assistant", content="hello s1")
    tracer(AgentStart(system_prompt="sys", user_input="prompt 1"))
    tracer(TurnStart(iteration=1))
    tracer(MessageStart(message=msg))
    tracer(MessageEnd(message=msg))
    tracer(TurnEnd())
    tracer(AgentEnd(messages=[msg], iterations=1, stop_reason="end_turn", final_text="done"))

    assert session1_log.is_file()
    assert session1_events.is_file()
    s1_log_content = session1_log.read_text(encoding="utf-8")
    assert "[AGENT_START] prompt=\"prompt 1\"" in s1_log_content

    import json
    s1_events_lines = [json.loads(line) for line in session1_events.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(s1_events_lines) >= 5
    assert any(e.get("type") == "agent_start" and e.get("user_input") == "prompt 1" for e in s1_events_lines)
    assert any(e.get("type") == "turn_start" and e.get("iteration") == 1 for e in s1_events_lines)
    assert any(e.get("type") == "agent_end" and e.get("stop_reason") == "end_turn" for e in s1_events_lines)

    # 动态切换/重绑定至 Session 2
    session2_log = tmp_path / "s2.debug.log"
    session2_events = tmp_path / "s2.events.jsonl"
    tracer.rebind(log_path=session2_log, events_path=session2_events)

    msg2 = Message(role="assistant", content="hello s2")
    tracer(AgentStart(system_prompt="sys2", user_input="prompt 2"))
    tracer(TurnStart(iteration=1))
    tracer(MessageEnd(message=msg2))
    tracer(AgentEnd(messages=[msg2], iterations=1, stop_reason="end_turn", final_text="done2"))

    tracer.close()

    assert session2_log.is_file()
    assert session2_events.is_file()
    assert "[AGENT_START] prompt=\"prompt 2\"" in session2_log.read_text(encoding="utf-8")
    # session 1 应该没有 prompt 2
    assert "prompt 2" not in session1_log.read_text(encoding="utf-8")

