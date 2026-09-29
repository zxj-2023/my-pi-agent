"""内核事件 → ACP session/update 翻译层单元测试。"""

from __future__ import annotations

from pathlib import Path

from acp.schema import AgentMessageChunk, AgentThoughtChunk, ToolCallProgress, ToolCallStart
from my_agent_core.events import MessageUpdate, ToolExecutionEnd, ToolExecutionStart
from my_agent_llm import Message, StreamChunk

from my_acp_agent.events import (
    MAX_RESULT_CHARS,
    tool_kind,
    tool_locations,
    tool_title,
    translate_message_update,
    translate_tool_end,
    translate_tool_start,
)

WS = Path("/workspace")


def _msg() -> Message:
    return Message(role="assistant", content="")


def test_tool_kind_maps_builtin_tools():
    assert tool_kind("read") == "read"
    assert tool_kind("write") == "edit"
    assert tool_kind("edit") == "edit"
    assert tool_kind("bash") == "execute"
    assert tool_kind("grep") == "search"
    assert tool_kind("unknown_tool") == "other"


def test_tool_title_renders_args_and_tolerates_missing_keys():
    assert tool_title("read", {"path": "a.py"}) == "Read a.py"
    assert tool_title("bash", {"command": "ls -la"}) == "Run ls -la"
    # 入参缺失时回落工具名，不抛异常
    assert tool_title("read", {}) == "Read "
    assert tool_title("mystery", {"x": 1}) == "mystery"


def test_tool_locations_resolves_relative_paths():
    locations = tool_locations("read", {"path": "src/main.py"}, WS)
    assert len(locations) == 1
    assert Path(locations[0].path) == WS / "src/main.py"


def test_tool_locations_absolute_path_untouched():
    absolute = Path("/tmp/x.txt")
    locations = tool_locations("write", {"path": str(absolute)}, WS)
    assert Path(locations[0].path) == absolute


def test_tool_locations_empty_when_no_path_arg():
    assert tool_locations("bash", {"command": "ls"}, WS) == []


def test_translate_message_update_emits_text_chunk():
    event = MessageUpdate(message=_msg(), chunk=StreamChunk(content="hello"))
    updates = translate_message_update(event)
    assert len(updates) == 1
    assert isinstance(updates[0], AgentMessageChunk)
    assert updates[0].content.text == "hello"


def test_translate_message_update_emits_thought_chunk():
    event = MessageUpdate(
        message=_msg(),
        chunk=StreamChunk(content="", metadata={"reasoning_content": "thinking..."}),
    )
    updates = translate_message_update(event)
    assert len(updates) == 1
    assert isinstance(updates[0], AgentThoughtChunk)
    assert updates[0].content.text == "thinking..."


def test_translate_message_update_emits_thought_then_text():
    event = MessageUpdate(
        message=_msg(),
        chunk=StreamChunk(content="answer", metadata={"reasoning_content": "reason"}),
    )
    updates = translate_message_update(event)
    assert [type(u) for u in updates] == [AgentThoughtChunk, AgentMessageChunk]


def test_translate_message_update_ignores_empty_and_tool_only_chunks():
    assert translate_message_update(MessageUpdate(message=_msg(), chunk=None)) == []
    assert translate_message_update(MessageUpdate(message=_msg(), chunk=StreamChunk(content=""))) == []


def test_translate_tool_start_carries_kind_status_and_location():
    event = ToolExecutionStart(tool_call_id="c1", tool_name="read", args={"path": "a.py"})
    update = translate_tool_start(event, WS)
    assert isinstance(update, ToolCallStart)
    assert update.tool_call_id == "c1"
    assert update.kind == "read"
    assert update.status == "in_progress"
    assert update.title == "Read a.py"
    assert update.raw_input == {"path": "a.py"}


def test_translate_tool_end_success():
    event = ToolExecutionEnd(tool_call_id="c1", tool_name="read", result="file body", is_error=False)
    update = translate_tool_end(event, WS)
    assert isinstance(update, ToolCallProgress)
    assert update.status == "completed"
    assert update.content[0].content.text == "file body"


def test_translate_tool_end_error_marks_failed():
    event = ToolExecutionEnd(tool_call_id="c1", tool_name="bash", result="boom", is_error=True)
    update = translate_tool_end(event, WS)
    assert update.status == "failed"


def test_translate_tool_end_truncates_oversized_result():
    big = "x" * (MAX_RESULT_CHARS + 500)
    update = translate_tool_end(
        ToolExecutionEnd(tool_call_id="c1", tool_name="bash", result=big, is_error=False),
        WS,
    )
    text = update.content[0].content.text
    assert len(text) < len(big)
    assert "truncated" in text


def test_translate_tool_end_empty_result_has_no_content():
    update = translate_tool_end(
        ToolExecutionEnd(tool_call_id="c1", tool_name="bash", result="", is_error=False),
        WS,
    )
    assert update.content is None
