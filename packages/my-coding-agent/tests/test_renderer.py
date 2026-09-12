import io
from rich.console import Console
from my_agent_core.events import (
    AgentStart,
    AgentEnd,
    TurnStart,
    TurnEnd,
    MessageUpdate,
    ToolExecutionStart,
    ToolExecutionEnd,
)
from my_agent_llm.models import Message, StreamChunk
from my_coding_agent.renderer import EventRenderer, TextChunk


def test_renderer_thinking_and_content_deltas():
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True, color_system="truecolor")
    renderer = EventRenderer(console=console)

    # 1. 思考过程事件
    msg = Message(role="assistant", content="")
    renderer.on_event(
        MessageUpdate(
            message=msg,
            chunk=TextChunk(text="Thinking step 1", reasoning_content="Thinking step 1"),
        )
    )

    # 2. 正文输出事件
    renderer.on_event(MessageUpdate(message=msg, chunk=TextChunk(text="Hello world")))

    output = buf.getvalue()
    assert "\U0001F4AD" in output
    assert "思考过程:" in output
    assert "Thinking step 1" in output
    assert "Hello world" in output


def test_renderer_tool_execution_with_diff():
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True, color_system="truecolor")
    renderer = EventRenderer(console=console)

    renderer.on_event(ToolExecutionStart(tool_call_id="c1", tool_name="edit", args={"path": "app.py"}))

    diff_text = "--- a/app.py\n+++ b/app.py\n-old\n+new\n"
    res_text = f"Successfully applied 1 edit(s).\nDiff:\n```diff\n{diff_text}```"
    renderer.on_event(ToolExecutionEnd(tool_call_id="c1", tool_name="edit", result=res_text, is_error=False))

    output = buf.getvalue()
    assert "[edit]" in output
    assert "-old" in output
    assert "+new" in output


def test_renderer_tool_execution_failure():
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True, color_system="truecolor")
    renderer = EventRenderer(console=console)

    renderer.on_event(ToolExecutionStart(tool_call_id="c2", tool_name="bash", args={"command": "exit 1"}))
    renderer.on_event(
        ToolExecutionEnd(
            tool_call_id="c2",
            tool_name="bash",
            result="Command failed with exit code 1",
            is_error=True,
        )
    )

    output = buf.getvalue()
    assert "[bash]" in output
    assert "Failed" in output


def test_renderer_agent_lifecycle():
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True, color_system="truecolor")
    renderer = EventRenderer(console=console)

    renderer.on_event(AgentStart(user_input="test"))
    renderer.on_event(
        AgentEnd(
            messages=[],
            final_text="All done",
            iterations=3,
            stop_reason="end_turn",
        )
    )

    output = buf.getvalue()
    assert "耗时:" in output
    assert "回合: 3" in output


def test_renderer_tool_args_truncation():
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True, color_system="truecolor")
    renderer = EventRenderer(console=console)

    long_arg = "a" * 100
    renderer.on_event(
        ToolExecutionStart(
            tool_call_id="c3",
            tool_name="write",
            args={"path": "file.txt", "content": long_arg},
        )
    )

    output = buf.getvalue()
    assert "[write]" in output
    assert "..." in output


def test_renderer_stream_chunk_compatibility():
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True, color_system="truecolor")
    renderer = EventRenderer(console=console)

    msg = Message(role="assistant", content="")
    # 兼容来自 loop.py 的 StreamChunk
    renderer.on_event(
        MessageUpdate(
            message=msg,
            chunk=StreamChunk(content="", metadata={"reasoning_content": "DeepSeek thinking"}),
        )
    )
    renderer.on_event(
        MessageUpdate(
            message=msg,
            chunk=StreamChunk(content="Direct answer"),
        )
    )

    output = buf.getvalue()
    assert "DeepSeek thinking" in output
    assert "Direct answer" in output


def test_renderer_ignores_other_events():
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True, color_system="truecolor")
    renderer = EventRenderer(console=console)

    # 不崩溃测试
    renderer.on_event(TurnStart(iteration=1))
    renderer.on_event(TurnEnd(message=None, tool_results=[]))
    # 确认没有未捕获异常抛出
    assert True


def test_renderer_streamed_code_with_square_brackets():
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True, color_system="truecolor")
    renderer = EventRenderer(console=console)

    msg = Message(role="assistant", content="")
    code_chunk = "def get_items() -> list[str]:\n    return ['hello', 'world']\n"
    renderer.on_event(MessageUpdate(message=msg, chunk=TextChunk(text=code_chunk)))

    output = buf.getvalue()
    assert "list[str]" in output
    assert "['hello', 'world']" in output


def test_renderer_tool_execution_end_tool_name_badge():
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True, color_system="truecolor")
    renderer = EventRenderer(console=console)

    renderer.on_event(ToolExecutionEnd(tool_call_id="c99", tool_name="read", result="file content", is_error=False))

    output = buf.getvalue()
    assert "✓ OK" in output
    assert "[read]" in output
