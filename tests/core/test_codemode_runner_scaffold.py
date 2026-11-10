from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.anyio

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = REPO_ROOT / "src" / "my_agent_core" / "codemode" / "runner.mjs"
NODE_BIN = shutil.which("node") or "node"


async def spawn_runner() -> asyncio.subprocess.Process:
    return await asyncio.create_subprocess_exec(
        NODE_BIN,
        str(RUNNER_PATH),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )


async def send_json(proc: asyncio.subprocess.Process, data: dict[str, Any]) -> None:
    assert proc.stdin is not None
    payload = json.dumps(data) + "\n"
    proc.stdin.write(payload.encode("utf-8"))
    await proc.stdin.drain()


async def read_json(proc: asyncio.subprocess.Process, timeout: float = 5.0) -> dict[str, Any]:
    assert proc.stdout is not None
    line = await asyncio.wait_for(proc.stdout.readline(), timeout=timeout)
    assert line, "Process closed stdout unexpectedly"
    return json.loads(line.decode("utf-8"))


async def test_codemode_runner_file_exists():
    assert RUNNER_PATH.is_file(), f"Runner script not found at {RUNNER_PATH}"


async def test_codemode_runner_basic_arithmetic():
    proc = await spawn_runner()
    try:
        await send_json(
            proc,
            {
                "action": "execute",
                "code": "text(1 + 2);",
                "store": {},
                "timeout_ms": 10000,
                "max_output_tokens": 1000,
            },
        )
        completed = await read_json(proc)
        assert completed["action"] == "completed"
        assert completed["ok"] is True
        assert completed["text_items"] == ["3"]
        assert completed["console_lines"] == []
        assert completed["store_writes"] == {}
        assert completed.get("error") is None
        assert isinstance(completed.get("wall_time"), (int, float))
        assert completed["wall_time"] >= 0
    finally:
        if proc.returncode is None:
            proc.terminate()
            await proc.wait()


async def test_codemode_runner_tool_calling():
    proc = await spawn_runner()
    try:
        await send_json(
            proc,
            {
                "action": "execute",
                "code": 'const res = await tools.echo({ msg: "hi" }); text(res);',
                "store": {},
                "timeout_ms": 10000,
                "max_output_tokens": 1000,
            },
        )
        tool_call = await read_json(proc)
        assert tool_call["action"] == "tool_call"
        assert tool_call["name"] == "echo"
        assert tool_call["args"] == {"msg": "hi"}
        call_id = tool_call["call_id"]

        await send_json(
            proc,
            {
                "action": "tool_result",
                "call_id": call_id,
                "ok": True,
                "result": "echo: hi",
            },
        )

        completed = await read_json(proc)
        assert completed["action"] == "completed"
        assert completed["ok"] is True
        assert completed["text_items"] == ["echo: hi"]
        assert completed["console_lines"] == []
        assert completed["store_writes"] == {}
    finally:
        if proc.returncode is None:
            proc.terminate()
            await proc.wait()


async def test_codemode_runner_tool_calling_error_handled():
    proc = await spawn_runner()
    try:
        await send_json(
            proc,
            {
                "action": "execute",
                "code": 'try { await tools.fail({ test: 1 }); } catch (e) { text("caught: " + e.message); }',
                "store": {},
                "timeout_ms": 10000,
                "max_output_tokens": 1000,
            },
        )
        tool_call = await read_json(proc)
        assert tool_call["action"] == "tool_call"
        assert tool_call["name"] == "fail"
        call_id = tool_call["call_id"]

        await send_json(
            proc,
            {
                "action": "tool_result",
                "call_id": call_id,
                "ok": False,
                "error": "simulated tool failure",
            },
        )

        completed = await read_json(proc)
        assert completed["action"] == "completed"
        assert completed["ok"] is True
        assert completed["text_items"] == ["caught: simulated tool failure"]
    finally:
        if proc.returncode is None:
            proc.terminate()
            await proc.wait()


async def test_codemode_runner_console_log():
    proc = await spawn_runner()
    try:
        await send_json(
            proc,
            {
                "action": "execute",
                "code": 'console.log("hello", 123);',
                "store": {},
                "timeout_ms": 10000,
                "max_output_tokens": 1000,
            },
        )
        completed = await read_json(proc)
        assert completed["action"] == "completed"
        assert completed["ok"] is True
        assert completed["console_lines"] == ["hello 123"]
    finally:
        if proc.returncode is None:
            proc.terminate()
            await proc.wait()


async def test_codemode_runner_store_load():
    proc = await spawn_runner()
    try:
        await send_json(
            proc,
            {
                "action": "execute",
                "code": 'store("a", 1); text(load("a"));',
                "store": {},
                "timeout_ms": 10000,
                "max_output_tokens": 1000,
            },
        )
        completed = await read_json(proc)
        assert completed["action"] == "completed"
        assert completed["ok"] is True
        assert completed["text_items"] == ["1"]
        assert completed["store_writes"] == {"a": 1}
    finally:
        if proc.returncode is None:
            proc.terminate()
            await proc.wait()


async def test_codemode_runner_preexisting_store():
    proc = await spawn_runner()
    try:
        await send_json(
            proc,
            {
                "action": "execute",
                "code": 'text(load("cursor")); store("cursor", 42);',
                "store": {"cursor": 10},
                "timeout_ms": 10000,
                "max_output_tokens": 1000,
            },
        )
        completed = await read_json(proc)
        assert completed["action"] == "completed"
        assert completed["ok"] is True
        assert completed["text_items"] == ["10"]
        assert completed["store_writes"] == {"cursor": 42}
    finally:
        if proc.returncode is None:
            proc.terminate()
            await proc.wait()


async def test_codemode_runner_sandbox_security():
    proc = await spawn_runner()
    try:
        code = """
        text(String(typeof process === 'undefined'));
        text(String(typeof require === 'undefined'));
        text(String(typeof fetch === 'undefined'));
        text(String(Object.isFrozen(Object.prototype) === true));
        """
        await send_json(
            proc,
            {
                "action": "execute",
                "code": code,
                "store": {},
                "timeout_ms": 10000,
                "max_output_tokens": 1000,
            },
        )
        completed = await read_json(proc)
        assert completed["action"] == "completed"
        assert completed["ok"] is True
        assert completed["text_items"] == ["true", "true", "true", "true"]
    finally:
        if proc.returncode is None:
            proc.terminate()
            await proc.wait()


async def test_codemode_runner_exit_early():
    proc = await spawn_runner()
    try:
        await send_json(
            proc,
            {
                "action": "execute",
                "code": 'text("before"); exit(); text("after");',
                "store": {},
                "timeout_ms": 10000,
                "max_output_tokens": 1000,
            },
        )
        completed = await read_json(proc)
        assert completed["action"] == "completed"
        assert completed["ok"] is True
        assert completed["text_items"] == ["before"]
    finally:
        if proc.returncode is None:
            proc.terminate()
            await proc.wait()


async def test_codemode_runner_unhandled_script_error():
    proc = await spawn_runner()
    try:
        await send_json(
            proc,
            {
                "action": "execute",
                "code": 'throw new Error("fatal test crash");',
                "store": {},
                "timeout_ms": 10000,
                "max_output_tokens": 1000,
            },
        )
        completed = await read_json(proc)
        assert completed["action"] == "completed"
        assert completed["ok"] is False
        assert "fatal test crash" in str(completed.get("error"))
    finally:
        if proc.returncode is None:
            proc.terminate()
            await proc.wait()


async def test_codemode_runner_top_level_return():
    proc = await spawn_runner()
    try:
        await send_json(
            proc,
            {
                "action": "execute",
                "code": 'return { "message": "done", "status": 200 };',
                "store": {},
                "timeout_ms": 10000,
                "max_output_tokens": 1000,
            },
        )
        completed = await read_json(proc)
        assert completed["action"] == "completed"
        assert completed["ok"] is True
        assert completed["text_items"] == ['{"message":"done","status":200}']
    finally:
        if proc.returncode is None:
            proc.terminate()
            await proc.wait()


async def test_codemode_runner_concurrent_tool_calls():
    proc = await spawn_runner()
    try:
        code = """
        const p1 = tools.fetch_a({ id: 1 });
        const p2 = tools.fetch_b({ id: 2 });
        const [r1, r2] = await Promise.all([p1, p2]);
        text(`${r1}|${r2}`);
        """
        await send_json(
            proc,
            {
                "action": "execute",
                "code": code,
                "store": {},
                "timeout_ms": 10000,
                "max_output_tokens": 1000,
            },
        )
        req1 = await read_json(proc)
        req2 = await read_json(proc)
        calls = {req1["name"]: req1, req2["name"]: req2}
        assert "fetch_a" in calls
        assert "fetch_b" in calls

        # Respond in reverse order
        await send_json(
            proc,
            {
                "action": "tool_result",
                "call_id": calls["fetch_b"]["call_id"],
                "ok": True,
                "result": "B_RES",
            },
        )
        await send_json(
            proc,
            {
                "action": "tool_result",
                "call_id": calls["fetch_a"]["call_id"],
                "ok": True,
                "result": "A_RES",
            },
        )

        completed = await read_json(proc)
        assert completed["action"] == "completed"
        assert completed["ok"] is True
        assert completed["text_items"] == ["A_RES|B_RES"]
    finally:
        if proc.returncode is None:
            proc.terminate()
            await proc.wait()


async def test_codemode_runner_syntax_error():
    proc = await spawn_runner()
    try:
        await send_json(
            proc,
            {
                "action": "execute",
                "code": "const invalid = ;",
                "store": {},
                "timeout_ms": 10000,
                "max_output_tokens": 1000,
            },
        )
        completed = await read_json(proc)
        assert completed["action"] == "completed"
        assert completed["ok"] is False
        assert completed["error"] is not None
    finally:
        if proc.returncode is None:
            proc.terminate()
            await proc.wait()


async def test_codemode_runner_sandbox_escape_blocked():
    proc = await spawn_runner()
    try:
        code = """
        let escapeCaught = false;
        try {
          text.constructor.constructor("return process")();
        } catch (e) {
          escapeCaught = true;
        }
        text(String(escapeCaught));
        """
        await send_json(
            proc,
            {
                "action": "execute",
                "code": code,
                "store": {},
                "timeout_ms": 10000,
                "max_output_tokens": 1000,
            },
        )
        completed = await read_json(proc)
        assert completed["action"] == "completed"
        assert completed["ok"] is True
        assert completed["text_items"] == ["true"]
    finally:
        if proc.returncode is None:
            proc.terminate()
            await proc.wait()
