from __future__ import annotations

import asyncio
from typing import Any

import pytest

from my_agent_core.codemode import CodemodeBridge, ScriptResult
from my_agent_core.loop import CancellationToken
from my_agent_core.tools import ToolResult

pytestmark = pytest.mark.anyio


async def test_bridge_basic_execution():
    bridge = CodemodeBridge()
    res = await bridge.execute_script("text(10 + 20);")
    assert isinstance(res, ScriptResult)
    assert res.ok is True
    assert res.text_items == ["30"]
    assert res.console_lines == []
    assert res.store_writes == {}
    assert res.error is None
    assert res.wall_time >= 0

    # Test console logs and multiple text items
    res2 = await bridge.execute_script("console.log('debug output'); text('line1'); text('line2');")
    assert res2.ok is True
    assert res2.text_items == ["line1", "line2"]
    assert res2.console_lines == ["debug output"]

    # Test top-level return
    res3 = await bridge.execute_script("return 10 * 5;")
    assert res3.ok is True
    assert res3.text_items == ["50"]


async def test_bridge_tool_callback():
    bridge = CodemodeBridge()
    recorded_calls: list[tuple[str, dict[str, Any]]] = []

    async def mock_executor(name: str, args: dict[str, Any]) -> Any:
        recorded_calls.append((name, args))
        if name == "fetch_data":
            return f"fetched:{args.get('key')}"
        if name == "tool_result_call":
            return ToolResult(ok=True, data="from_tool_result")
        return "default"

    # Test simple return
    res = await bridge.execute_script(
        'const r = await tools.fetch_data({ key: "val" }); text(r);',
        tool_executor=mock_executor,
    )
    assert res.ok is True
    assert res.text_items == ["fetched:val"]
    assert len(recorded_calls) == 1
    assert recorded_calls[0] == ("fetch_data", {"key": "val"})

    # Test ToolResult return
    res2 = await bridge.execute_script(
        "const r = await tools.tool_result_call({}); text(r);",
        tool_executor=mock_executor,
    )
    assert res2.ok is True
    assert res2.text_items == ["from_tool_result"]


async def test_bridge_tool_error():
    bridge = CodemodeBridge()

    async def mock_executor(name: str, args: dict[str, Any]) -> Any:
        if name == "fail_tool":
            return ToolResult(ok=False, error="Tool failed with error")
        if name == "throw_tool":
            raise RuntimeError("Python exception raised in tool")
        return "ok"

    # JS catches tool error
    res_catch = await bridge.execute_script(
        """
        try {
            await tools.fail_tool({});
        } catch (e) {
            text("caught: " + e.message);
        }
        """,
        tool_executor=mock_executor,
    )
    assert res_catch.ok is True
    assert res_catch.text_items == ["caught: Tool failed with error"]

    # JS does not catch tool error
    res_fail = await bridge.execute_script(
        "await tools.fail_tool({});",
        tool_executor=mock_executor,
    )
    assert res_fail.ok is False
    assert "Tool failed with error" in (res_fail.error or "")

    # Python tool raises exception
    res_throw = await bridge.execute_script(
        "await tools.throw_tool({});",
        tool_executor=mock_executor,
    )
    assert res_throw.ok is False
    assert "Python exception raised in tool" in (res_throw.error or "")

    # Tool executor is None but tool is called
    res_no_exec = await bridge.execute_script("await tools.any_tool({});")
    assert res_no_exec.ok is False
    assert "No tool executor provided" in (res_no_exec.error or "")


async def test_bridge_syntax_error():
    bridge = CodemodeBridge()
    res = await bridge.execute_script("const invalid = ;")
    assert res.ok is False
    assert res.error is not None
    assert any(term in res.error for term in ["SyntaxError", "Unexpected token"])


async def test_bridge_timeout():
    bridge = CodemodeBridge()
    # Synchronous infinite loop or long sleep
    res = await bridge.execute_script(
        "while(true){}",
        timeout_ms=500,
    )
    assert res.ok is False
    assert res.error is not None
    assert "timeout" in res.error.lower() or "timed out" in res.error.lower()


async def test_bridge_store_roundtrip():
    bridge = CodemodeBridge()
    res = await bridge.execute_script(
        'store("k", 123); text(load("k")); text(load("init"));',
        store={"init": "val"},
    )
    assert res.ok is True
    assert res.text_items == ["123", "val"]
    assert res.store_writes == {"k": 123}


async def test_bridge_exit_early():
    bridge = CodemodeBridge()
    res = await bridge.execute_script('text("before"); exit(); text("after");')
    assert res.ok is True
    assert res.text_items == ["before"]


async def test_bridge_spawn_failure():
    bridge = CodemodeBridge(node_bin="non_existent_binary_xyz_12345")
    res = await bridge.execute_script("text(1);")
    assert res.ok is False
    assert "Failed to spawn runner process" in (res.error or "")


async def test_bridge_cancellation():
    bridge = CodemodeBridge()

    # Pre-cancelled token
    token_pre = CancellationToken()
    token_pre.cancel()
    res_pre = await bridge.execute_script("text('not run');", signal=token_pre)
    assert res_pre.ok is False
    assert "interrupted" in (res_pre.error or "").lower() or "cancel" in (res_pre.error or "").lower()

    # In-flight cancellation
    token_flight = CancellationToken()

    async def cancel_later():
        await asyncio.sleep(0.1)
        token_flight.cancel()

    asyncio.create_task(cancel_later())
    res_flight = await bridge.execute_script("while(true){}", signal=token_flight)
    assert res_flight.ok is False
    assert "interrupted" in (res_flight.error or "").lower() or "cancel" in (res_flight.error or "").lower()
