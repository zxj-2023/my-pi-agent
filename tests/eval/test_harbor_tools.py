import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def fake_env():
    env = MagicMock()
    exec_result = MagicMock()
    exec_result.return_code = 0
    exec_result.stdout = "hello container\n"
    exec_result.stderr = ""
    env.exec = AsyncMock(return_value=exec_result)
    env.read_file = AsyncMock(return_value="line1\nline2\n")
    env.write_file = AsyncMock()
    return env


@pytest.mark.anyio
async def test_harbor_bash_tool(fake_env):
    from my_pi_eval.tools import HarborToolRegistry

    registry = HarborToolRegistry(fake_env)
    res = await registry.execute("bash", {"command": "echo test"})
    assert res.ok is True
    assert "hello container" in str(res.data)
    fake_env.exec.assert_awaited_once_with("echo test")


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
    fake_env.write_file.assert_awaited_once_with("/app/run.sh", "echo 1\necho 2\n")


@pytest.mark.anyio
async def test_harbor_edit_tool_surgical_replacement(fake_env):
    from my_pi_eval.tools import HarborToolRegistry

    fake_env.read_file.return_value = "def foo():\n    return 41\n"
    registry = HarborToolRegistry(fake_env)
    res = await registry.execute(
        "edit", {"path": "/app/main.py", "edits": [{"oldText": "return 41", "newText": "return 42"}]}
    )
    assert res.ok is True
    fake_env.write_file.assert_awaited_once_with("/app/main.py", "def foo():\n    return 42\n")


@pytest.mark.anyio
async def test_harbor_edit_tool_uniqueness_check(fake_env):
    from my_pi_eval.tools import HarborToolRegistry

    fake_env.read_file.return_value = "x = 1\nx = 1\n"
    registry = HarborToolRegistry(fake_env)
    res = await registry.execute("edit", {"path": "/app/main.py", "edits": [{"oldText": "x = 1", "newText": "x = 2"}]})
    assert res.ok is False
    assert "2 times" in str(res.error)


@pytest.mark.anyio
async def test_harbor_tools_never_throw(fake_env):
    from my_pi_eval.tools import HarborToolRegistry

    fake_env.exec.side_effect = RuntimeError("Docker crashed")
    registry = HarborToolRegistry(fake_env)
    res = await registry.execute("bash", {"command": "ls"})
    assert res.ok is False
    assert "Docker crashed" in str(res.error)
