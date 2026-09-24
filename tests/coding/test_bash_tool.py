from __future__ import annotations

import asyncio
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

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
    assert res.ok is False


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
    res = await tool.execute(command="python -c \"import sys; print('error details'); sys.exit(42)\"")
    assert res.ok is False
    assert "Command failed with exit code 42:" in str(res)
    assert "error details" in str(res)


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
    cmd = f"python -c \"import os, time; open(r'{pid_file}', 'w').write(str(os.getpid())); time.sleep(30)\""
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


async def test_bash_on_update_streaming(tmp_path: Path):
    """测试 bash 执行期间通过 on_update 回调实时回传输出流（对标 Pi 官方流式工具更新）。"""
    tool = make_bash_tool(tmp_path)
    updates: list[str] = []

    def handle_update(chunk: Any) -> None:
        updates.append(str(chunk))

    cmd = "python -c \"import time; print('step1', flush=True); time.sleep(0.15); print('step2', flush=True)\""
    res = await tool.execute(
        {"command": cmd},
        on_update=handle_update,
    )
    assert res.ok is True
    assert "step1" in str(res.data)
    assert "step2" in str(res.data)
    assert len(updates) > 0


def test_resolve_shell_detection():
    """测试 Windows 下优先解析 Git Bash 路径。"""
    from my_coding_agent.tools.bash import _resolve_shell

    shell_path, is_bash = _resolve_shell()
    assert isinstance(shell_path, str)
    assert isinstance(is_bash, bool)
    if is_bash:
        assert "bash" in shell_path.lower()


async def test_bash_signal_cancellation_kills_process_immediately(tmp_path: Path):
    """测试在执行长时间命令时，signal.cancel() 能够毫秒级杀死子进程并返回中断结果。"""
    from my_agent_core.loop import CancellationToken
    tool = make_bash_tool(tmp_path)
    signal = CancellationToken()

    pid_file = tmp_path / "long_running.pid"
    cmd = f"python -c \"import os, time; open(r'{pid_file}', 'w').write(str(os.getpid())); time.sleep(30)\""

    async def _cancel_soon():
        for _ in range(50):
            if pid_file.exists() and pid_file.read_text(encoding="utf-8").strip():
                break
            await asyncio.sleep(0.05)
        signal.cancel()

    cancel_task = asyncio.create_task(_cancel_soon())
    start_time = asyncio.get_running_loop().time()
    res = await tool.execute(command=cmd, signal=signal)
    duration = asyncio.get_running_loop().time() - start_time
    await cancel_task

    # 验证毫秒级退出 (< 3.0s，绝不会等待 30s)
    assert duration < 3.0
    assert res.ok is False
    assert "interrupted" in str(res).lower()


async def test_bash_pipefail_propagates_error(tmp_path: Path):
    """测试 pipefail 使得管道中间命令的失败能够如实被捕获，而不被 tail/head 吞没。"""
    tool = make_bash_tool(tmp_path)
    res = await tool.execute(command='python -c "import sys; sys.exit(42)" | cat')
    assert res.ok is False
    assert "42" in str(res)

