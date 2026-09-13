from unittest.mock import MagicMock, patch
import pytest

from my_agent_tui.keylistener import LiveInputListener


def test_keylistener_non_interactive_is_noop():
    # 测试非交互式管道环境下安全降级，不抛出任何异常
    listener = LiveInputListener()
    with listener:
        assert listener.active is False


@pytest.mark.anyio
async def test_keylistener_async_context_manager():
    # 测试异步上下文管理器
    listener = LiveInputListener()
    async with listener:
        assert listener.active is False


def test_keylistener_callbacks_invocation():
    mock_esc = MagicMock()
    mock_line = MagicMock()
    listener = LiveInputListener(on_escape=mock_esc, on_line=mock_line)

    # 模拟处理按键
    listener._handle_key("\x1b")
    mock_esc.assert_called_once()
    assert listener._buffer == []

    listener._handle_key("h")
    listener._handle_key("i")
    listener._handle_key("\r")
    mock_line.assert_called_once_with("hi")
    assert listener._buffer == []


def test_keylistener_newline_and_backspace():
    mock_line = MagicMock()
    listener = LiveInputListener(on_line=mock_line)

    # 测试退格键 \x08 与 \x7f (127)
    listener._handle_key("a")
    listener._handle_key("b")
    listener._handle_key("\x08")  # 退回 'b'
    listener._handle_key("c")
    listener._handle_key(chr(127))  # 退回 'c'
    listener._handle_key("d")
    listener._handle_key("\n")  # 回车触发
    mock_line.assert_called_once_with("ad")

    # 空 buffer 退格不抛异常
    listener._handle_key("\x08")
    assert listener._buffer == []


def test_keylistener_empty_or_whitespace_line():
    mock_line = MagicMock()
    listener = LiveInputListener(on_line=mock_line)

    # 纯空白回车不触发 on_line
    listener._handle_key(" ")
    listener._handle_key(" ")
    listener._handle_key("\r")
    mock_line.assert_not_called()
    assert listener._buffer == []


def test_keylistener_none_callbacks():
    # 回调为 None 时不抛异常
    listener = LiveInputListener()
    listener._handle_key("\x1b")
    listener._handle_key("a")
    listener._handle_key("\n")
    assert listener._buffer == []


def test_keylistener_interactive_start_stop():
    with patch("sys.stdin.isatty", return_value=True):
        listener = LiveInputListener()
        with patch.object(listener, "_worker_windows"), patch.object(listener, "_worker_posix"):
            listener.start()
            assert listener.active is True
            assert listener._thread is not None
            listener.stop()
            assert listener.active is False
            assert listener._thread is None


def test_keylistener_isatty_exception_graceful():
    # isatty 抛出异常时降级为 no-op
    with patch("sys.stdin.isatty", side_effect=ValueError("closed file")):
        listener = LiveInputListener()
        with listener:
            assert listener.active is False
