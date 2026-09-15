"""Tests for Python CLI entrypoint (my_coding_agent.cli)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from my_coding_agent.cli import find_tui_entry, main


def test_find_tui_entry_in_dev_workspace():
    entry = find_tui_entry()
    assert entry is not None
    assert entry.exists()
    assert entry.name == "my-agent.js"


def test_cli_help_flag_displays_usage(capsys):
    with patch.object(sys, "argv", ["my-pi-agent", "--help"]):
        code = main(["--help"])
        # If node exists, it delegates to node --help or prints local help
        # Either way code is 0 or delegated
        out = capsys.readouterr().out
        assert code == 0 or "Usage" in out or "my-agent" in out or "my-pi-agent" in out


def test_cli_missing_node_outputs_friendly_guide(capsys):
    with patch("shutil.which", return_value=None):
        code = main(["-m", "gpt-4o"])
        assert code == 1
        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert "Node.js" in combined or "node" in combined
        assert "https://nodejs.org" in combined or "fnm" in combined or "nvm" in combined


def test_cli_launches_node_with_python_executable():
    # Use an existing real file so exists() returns True naturally
    fake_entry = Path(__file__).resolve()
    with (
        patch("my_coding_agent.cli.find_tui_entry", return_value=fake_entry),
        patch("shutil.which", return_value="/usr/bin/node"),
        patch("subprocess.run") as mock_run,
    ):
        mock_run.return_value = MagicMock(returncode=0)
        code = main(["-c", "-m", "deepseek-chat"])
        assert code == 0
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert call_args[0] == "/usr/bin/node"
        assert str(fake_entry) in call_args[1]
        assert "-c" in call_args
        assert "-m" in call_args
        assert "deepseek-chat" in call_args
        assert "--python-executable" in call_args
        assert sys.executable in call_args
