from __future__ import annotations

import asyncio
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from my_coding_agent.tools.bash import BashResult, make_bash_tool

pytestmark = pytest.mark.anyio


async def test_bash_echo(tmp_path: Path):
    tool = make_bash_tool(tmp_path)
    res = await tool.execute(command="python -c \"print('hello from bash')\"")
    assert "hello from bash" in res
    assert res.ok is True


async def test_bash_timeout_kills_process(tmp_path: Path):
    tool = make_bash_tool(tmp_path)
    res = await tool.execute(
        command='python -c "import time; time.sleep(10)"',
        timeout=1,
    )
    assert "timed out after 1 seconds" in res
    assert res.ok is True


async def test_bash_blocked_commands(tmp_path: Path):
    tool = make_bash_tool(tmp_path)
    res = await tool.execute(command="rm -rf /")
    assert "Blocked dangerous command" in res

    for blocked in ["shutdown", "reboot", "mkfs", "dd if=/dev/zero", ":(){ :|:& };:"]:
        b_res = await tool.execute(command=f"echo ok && {blocked}")
        assert "Blocked dangerous command" in b_res


async def test_bash_output_truncation_spills_log(tmp_path: Path):
    tool = make_bash_tool(tmp_path)
    # 生成超过 3000 行
    cmd = "python -c \"for i in range(1, 3000): print(f'line {i}')\""
    res = await tool.execute(command=cmd)
    assert "[Output truncated: showing last" in res
    assert "Full output saved to:" in res
    assert "line 2999" in res

    # 验证日志文件确实生成且包含完整输出
    match = re.search(r"Full output saved to: (.*?)\]", str(res))
    assert match is not None
    log_path = Path(match.group(1))
    assert log_path.exists()
    content = log_path.read_text(encoding="utf-8")
    assert "line 1\n" in content or "line 1\r\n" in content
    assert "line 2999" in content
    # 清理测试日志
    log_path.unlink(missing_ok=True)


async def test_bash_byte_truncation_spills_log(tmp_path: Path):
    tool = make_bash_tool(tmp_path)
    # 生成小于 2000 行但超过 50KB 字节的单行/多行数据
    cmd = "python -c \"for i in range(100): print('X' * 1000)\""
    res = await tool.execute(command=cmd)
    assert "[Output truncated: showing last" in res
    assert "Full output saved to:" in res

    match = re.search(r"Full output saved to: (.*?)\]", str(res))
    assert match is not None
    log_path = Path(match.group(1))
    assert log_path.exists()
    log_path.unlink(missing_ok=True)


async def test_bash_command_failure_exit_code(tmp_path: Path):
    tool = make_bash_tool(tmp_path)
    res = await tool.execute(
        command="python -c \"import sys; print('error details'); sys.exit(42)\""
    )
    assert "Command failed with exit code 42:" in res
    assert "error details" in res


async def test_bash_no_output(tmp_path: Path):
    tool = make_bash_tool(tmp_path)
    res = await tool.execute(command='python -c "pass"')
    assert res == "(Command executed with no output)"


async def test_bash_workspace_cwd(tmp_path: Path):
    tool = make_bash_tool(tmp_path)
    res = await tool.execute(command='python -c "import os; print(os.getcwd())"')
    assert str(tmp_path.resolve()).lower() in str(res).lower()


async def test_bash_workspace_coerced_from_str(tmp_path: Path):
    tool = make_bash_tool(str(tmp_path))
    res = await tool.execute(command='python -c "import os; print(os.getcwd())"')
    assert str(tmp_path.resolve()).lower() in str(res).lower()


async def test_bash_run_in_background_not_configured(tmp_path: Path):
    tool = make_bash_tool(tmp_path, background_runner=None)
    res = await tool.execute(command="echo hi", run_in_background=True)
    assert "Error: Background task execution not configured on this agent." in res


async def test_bash_run_in_background_success(tmp_path: Path):
    class FakeRunner:
        async def run_process(self, command: str, cwd: Path | str) -> str:
            return "bg_job_123"

    tool = make_bash_tool(tmp_path, background_runner=FakeRunner())
    res = await tool.execute(command="echo hi", run_in_background=True)
    assert "Background task started with ID: bg_job_123" in res


async def test_bash_result_ergonomics(tmp_path: Path):
    tool = make_bash_tool(tmp_path)
    # dict execute
    res = await tool.execute({"command": "python -c \"print('hello')\"", "timeout": 60})
    assert isinstance(res, BashResult)
    assert res.ok is True
    assert "hello" in res
    assert "hello" in str(res)
    assert "hello" in repr(res)
    assert tool.is_parallel_safe is False


async def test_bash_cancelled_kills_process(tmp_path: Path):
    tool = make_bash_tool(tmp_path)
    pid_file = tmp_path / "child.pid"
    cmd = (
        'python -c "import os, time; '
        f"open(r'{pid_file}', 'w').write(str(os.getpid())); "
        'time.sleep(30)"'
    )
    task = asyncio.create_task(tool.execute(command=cmd))

    # 等待子进程启动并写入 PID
    for _ in range(50):
        if pid_file.exists() and pid_file.read_text(encoding="utf-8").strip():
            break
        await asyncio.sleep(0.1)

    assert pid_file.exists()
    child_pid = int(pid_file.read_text(encoding="utf-8").strip())

    # 取消协程任务
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # 验证子进程树已终止
    await asyncio.sleep(0.5)
    if sys.platform == "win32":
        res = subprocess.run(
            ["tasklist", "/FI", f"PID eq {child_pid}"],
            capture_output=True,
            text=True,
        )
        assert str(child_pid) not in res.stdout
    else:
        with pytest.raises(OSError):
            os.kill(child_pid, 0)
