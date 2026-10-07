from unittest.mock import MagicMock, patch
from my_pi_eval.cli import build_harbor_command, check_docker_environment


def test_build_harbor_command():
    cmd = build_harbor_command(
        task_path="/path/to/task",
        model="deepseek/deepseek-chat",
        concurrency=2,
    )
    assert cmd[0] == "harbor"
    assert "run" in cmd
    assert "-p" in cmd
    assert "/path/to/task" in cmd
    assert "--agent-import-path" in cmd
    assert "my_pi_eval.agent:MyPiAgent" in cmd
    assert "-m" in cmd
    assert "deepseek/deepseek-chat" in cmd
    assert "-n" in cmd
    assert "2" in cmd


@patch("subprocess.run")
def test_check_docker_environment_running(mock_run):
    mock_res = MagicMock()
    mock_res.returncode = 0
    mock_run.return_value = mock_res
    assert check_docker_environment() is True


@patch("subprocess.run")
def test_check_docker_environment_not_running(mock_run):
    mock_res = MagicMock()
    mock_res.returncode = 1
    mock_run.return_value = mock_res
    assert check_docker_environment() is False


@patch("subprocess.run", side_effect=FileNotFoundError)
def test_check_docker_environment_not_installed(mock_run):
    assert check_docker_environment() is False
