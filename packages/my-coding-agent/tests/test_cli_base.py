import sys
from unittest.mock import MagicMock

from my_coding_agent.cli_base import _force_utf8_streams, _is_utf8_encoding


def test_is_utf8_encoding():
    assert _is_utf8_encoding("utf-8") is True
    assert _is_utf8_encoding("UTF-8") is True
    assert _is_utf8_encoding("utf8") is True
    assert _is_utf8_encoding("cp1252") is False
    assert _is_utf8_encoding(None) is False


def test_force_utf8_streams_runs_without_error():
    # 验证在当前平台上调用不会抛出任何异常
    _force_utf8_streams()
    assert sys.stdout is not None
    assert sys.stderr is not None


def test_force_utf8_streams_reconfigures_non_utf8(monkeypatch):
    mock_stdout = MagicMock()
    mock_stdout.encoding = "cp936"
    mock_stderr = MagicMock()
    mock_stderr.encoding = "utf-8"
    monkeypatch.setattr(sys, "stdout", mock_stdout)
    monkeypatch.setattr(sys, "stderr", mock_stderr)

    _force_utf8_streams()
    mock_stdout.reconfigure.assert_called_once_with(encoding="utf-8", errors="replace")
    mock_stderr.reconfigure.assert_not_called()


def test_force_utf8_streams_suppresses_exception(monkeypatch):
    mock_stdout = MagicMock()
    mock_stdout.encoding = "cp1252"
    mock_stdout.reconfigure.side_effect = AttributeError("no reconfigure")
    monkeypatch.setattr(sys, "stdout", mock_stdout)
    monkeypatch.setattr(sys, "stderr", None)

    # Should not raise
    _force_utf8_streams()
