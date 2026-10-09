# pyright: reportMissingImports=false
import shlex
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def fake_env():
    import base64
    import re

    env = MagicMock(spec=["exec", "is_file", "is_dir"])
    filesystem = {
        "/app/main.py": "line1\nline2\n",
        "/app/run.sh": "echo old\n",
        "/app/edit_test.py": "def foo():\n    return 41\n",
        "/app/dup.py": "x = 1\nx = 1\n",
    }

    async def fake_exec(command: str):
        res = MagicMock()
        res.return_code = 0
        res.stderr = ""
        res.stdout = ""
        if command.startswith("cat "):
            target = command.split("cat ", 1)[1].strip().strip("'\"")
            if target in filesystem:
                res.stdout = filesystem[target]
            else:
                res.return_code = 1
                res.stderr = f"cat: {target}: No such file or directory"
        elif "base64 -d >" in command:
            m = re.search(r"echo\s+['\"]?([A-Za-z0-9+/=]+)['\"]?\s+\|\s+base64 -d >\s+['\"]?(.+?)['\"]?$", command)
            if m:
                b64_content, path = m.group(1), m.group(2).strip().strip("'\"")
                filesystem[path] = base64.b64decode(b64_content).decode("utf-8")
        else:
            res.stdout = "hello container\n"
        return res

    env.exec = AsyncMock(side_effect=fake_exec)
    env.filesystem = filesystem
    return env


@pytest.mark.anyio
async def test_harbor_bash_tool(fake_env):
    from my_pi_eval.tools import HarborToolRegistry

    registry = HarborToolRegistry(fake_env)
    res = await registry.execute("bash", {"command": "echo test"})
    assert res.ok is True
    assert "hello container" in str(res.data)
    call_arg = fake_env.exec.await_args[0][0]
    assert "echo test" in call_arg
    assert "DEBIAN_FRONTEND=noninteractive" in call_arg


@pytest.mark.anyio
async def test_harbor_bash_strips_ansi_and_cr(fake_env):
    """对标 Pi bash-executor.ts：清洗 ANSI 颜色控制符与 \r 进度条。"""
    from my_pi_eval.tools import HarborToolRegistry

    fake_env.exec.side_effect = None
    exec_res = MagicMock()
    exec_res.return_code = 0
    exec_res.stdout = "\x1b[31mFAILED\x1b[0m 10%\r20%\rFinished\n"
    exec_res.stderr = ""
    fake_env.exec.return_value = exec_res

    registry = HarborToolRegistry(fake_env)
    res = await registry.execute("bash", {"command": "pytest"})
    assert res.ok is True
    assert "\x1b[31m" not in str(res.data)
    assert "\r" not in str(res.data)
    assert "FAILED" in str(res.data)
    assert "Finished" in str(res.data)


@pytest.mark.anyio
async def test_harbor_bash_error_merges_stdout_and_exit_code(fake_env):
    """对标 Pi bash.ts：失败时完整保留 stdout+stderr，并在末尾追加 Command exited with code {code}。"""
    from my_pi_eval.tools import HarborToolRegistry

    fake_env.exec.side_effect = None
    exec_res = MagicMock()
    exec_res.return_code = 1
    exec_res.stdout = "Traceback (most recent call last):\n  File 'app.py', line 10\nZeroDivisionError"
    exec_res.stderr = "warning: unused import"
    fake_env.exec.return_value = exec_res

    registry = HarborToolRegistry(fake_env)
    res = await registry.execute("bash", {"command": "python app.py"})
    assert res.ok is False
    serialized = res.serialize()
    assert "ZeroDivisionError" in serialized
    assert "warning: unused import" in serialized
    assert "Command exited with code 1" in serialized


@pytest.mark.anyio
async def test_harbor_read_tool(fake_env):
    from my_pi_eval.tools import HarborToolRegistry

    registry = HarborToolRegistry(fake_env)
    res = await registry.execute("read", {"path": "/app/main.py", "offset": 1, "limit": 10})
    assert res.ok is True
    assert "1 | line1" in str(res.data)


@pytest.mark.anyio
async def test_harbor_write_tool_normalizes_crlf(fake_env):
    from my_pi_eval.tools import HarborToolRegistry

    registry = HarborToolRegistry(fake_env)
    res = await registry.execute("write", {"path": "/app/run.sh", "content": "echo 1\r\necho 2\r\n"})
    assert res.ok is True
    assert fake_env.filesystem["/app/run.sh"] == "echo 1\necho 2\n"


@pytest.mark.anyio
async def test_harbor_edit_tool_surgical_replacement(fake_env):
    from my_pi_eval.tools import HarborToolRegistry

    registry = HarborToolRegistry(fake_env)
    res = await registry.execute(
        "edit", {"path": "/app/edit_test.py", "edits": [{"oldText": "return 41", "newText": "return 42"}]}
    )
    assert res.ok is True
    assert fake_env.filesystem["/app/edit_test.py"] == "def foo():\n    return 42\n"


@pytest.mark.anyio
async def test_harbor_edit_tool_uniqueness_check(fake_env):
    from my_pi_eval.tools import HarborToolRegistry

    registry = HarborToolRegistry(fake_env)
    res = await registry.execute("edit", {"path": "/app/dup.py", "edits": [{"oldText": "x = 1", "newText": "x = 2"}]})
    assert res.ok is False
    assert "2 times" in str(res.error)
    assert "Must be uniquely matching" in str(res.error)


@pytest.mark.anyio
async def test_harbor_tools_never_throw(fake_env):
    from my_pi_eval.tools import HarborToolRegistry

    fake_env.exec.side_effect = RuntimeError("Docker crashed")
    registry = HarborToolRegistry(fake_env)
    res = await registry.execute("bash", {"command": "ls"})
    assert res.ok is False
    assert "Docker crashed" in str(res.error)


@pytest.mark.anyio
async def test_harbor_cwd_tracking_and_relative_path(fake_env):
    from my_pi_eval.tools import HarborToolRegistry

    exec_result = MagicMock()
    exec_result.return_code = 0
    exec_result.stdout = "changed directory\n__MY_PI_CWD__:/app/subfolder\n"
    exec_result.stderr = ""
    fake_env.exec.side_effect = None
    fake_env.exec.return_value = exec_result

    registry = HarborToolRegistry(fake_env)
    res = await registry.execute("bash", {"command": "cd subfolder"})
    assert res.ok is True
    assert registry.cwd == "/app/subfolder"
    assert "__MY_PI_CWD__" not in str(res.data)

    # Now read relative path "foo.py", should resolve to "/app/subfolder/foo.py"
    read_exec = MagicMock()
    read_exec.return_code = 0
    read_exec.stdout = "hello from foo\n"
    read_exec.stderr = ""
    fake_env.exec.return_value = read_exec
    res_read = await registry.execute("read", {"path": "foo.py"})
    assert res_read.ok is True
    assert "1 | hello from foo" in str(res_read.data)
    assert fake_env.exec.await_args[0][0] == f"cat {shlex.quote('/app/subfolder/foo.py')}"
