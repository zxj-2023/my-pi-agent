from my_agent_core import ContextManager, clean_provider_context
from my_agent_llm.models import Message


def test_clean_provider_context_strips_cancelled_empty_assistant_and_orphan_tools():
    msgs = [
        Message(role="system", content="sys"),
        Message(role="user", content="hello"),
        Message(role="assistant", content="hi"),
        Message(role="user", content="run sleep"),
        Message(
            role="assistant",
            content="",
            metadata={"stop_reason": "cancelled", "tool_calls": [{"id": "call_1", "name": "bash", "args": {}}]},
        ),
        Message(role="tool", content="interrupted", metadata={"tool_call_id": "call_1"}),
    ]
    cleaned = clean_provider_context(msgs)
    roles = [m.role for m in cleaned]
    # Cancelled empty assistant and its tool call should be cleanly omitted
    assert roles == ["system", "user", "assistant", "user"]


def test_build_cached_view_snaps_group_boundaries():
    ctx = ContextManager(budget=100000, llm=None)
    # Suppose compaction covered 4 messages, but later messages have assistant(tool_calls) + tool
    ctx.restore_cache(summary="summary text", covered_count=4, retained_tail=[])

    messages = [
        Message(role="system", content="sys"),
        Message(role="user", content="u1"),
        Message(role="assistant", content="a1"),
        Message(role="user", content="u2"),
        # start=4 would land on assistant(tool_calls)
        Message(role="assistant", content="", metadata={"tool_calls": [{"id": "c1", "name": "bash", "args": {}}]}),
        # index 5 is tool
        Message(role="tool", content="res1", metadata={"tool_call_id": "c1"}),
    ]

    view = ctx._build_cached_view(messages)
    # View must contain both assistant(tool_calls) and tool result, never orphan tool!
    roles = [m.role for m in view]
    assert roles == ["system", "user", "assistant", "tool"]


def test_clean_provider_context_on_view_drops_orphan_tool_if_ever_isolated():
    # If a view somehow only has system, user summary, and an orphan tool message
    broken_view = [
        Message(role="system", content="sys"),
        Message(role="user", content="[Context summary] ..."),
        Message(role="tool", content="orphan tool output", metadata={"tool_call_id": "call_unknown"}),
    ]
    safe_view = clean_provider_context(broken_view)
    roles = [m.role for m in safe_view]
    # The orphan tool must be safely removed to prevent API 400
    assert roles == ["system", "user"]
