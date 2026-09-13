from __future__ import annotations

import sys
import threading
from collections.abc import Callable
from types import TracebackType


class LiveInputListener:
    """对标 Pig-TUI keylistener.py 的流式生成期间按键监听器。"""

    def __init__(
        self,
        on_escape: Callable[[], None] | None = None,
        on_line: Callable[[str], None] | None = None,
    ):
        self.on_escape = on_escape
        self.on_line = on_line
        self.active: bool = False
        self._buffer: list[str] = []
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def _handle_key(self, char: str) -> None:
        if char == "\x1b":  # ESC
            if self.on_escape:
                self.on_escape()
            self._buffer.clear()
        elif char in ("\r", "\n"):
            line = "".join(self._buffer).strip()
            self._buffer.clear()
            if line and self.on_line:
                self.on_line(line)
        elif char in ("\x08", "\x7f"):  # Backspace / Delete
            if self._buffer:
                self._buffer.pop()
        else:
            self._buffer.append(char)

    def _worker_windows(self) -> None:
        import msvcrt
        import time

        while not self._stop_event.is_set():
            try:
                if msvcrt.kbhit():
                    ch = msvcrt.getwch()
                    self._handle_key(ch)
            except Exception:
                pass
            time.sleep(0.05)

    def _worker_posix(self) -> None:
        import select
        import termios
        import tty

        try:
            fd = sys.stdin.fileno()
            old_settings = termios.tcgetattr(fd)  # type: ignore
        except Exception:
            return

        try:
            tty.setcbreak(fd)  # type: ignore
            while not self._stop_event.is_set():
                try:
                    rlist, _, _ = select.select([sys.stdin], [], [], 0.05)
                    if rlist:
                        ch = sys.stdin.read(1)
                        if ch == "\x1b":
                            # 区分单独 ESC 还是 ANSI 转义序列 (如方向键 \x1b[A)
                            r_esc, _, _ = select.select([sys.stdin], [], [], 0.02)
                            if r_esc:
                                sys.stdin.read(2)  # 消费多字符序列
                                continue
                        if ch:
                            self._handle_key(ch)
                except Exception:
                    pass
        except Exception:
            pass
        finally:
            try:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)  # type: ignore
            except Exception:
                pass

    def start(self) -> None:
        if self.active:
            return
        try:
            if not sys.stdin or not hasattr(sys.stdin, "isatty") or not sys.stdin.isatty():
                return
        except Exception:
            return

        self.active = True
        self._buffer.clear()
        self._stop_event.clear()
        target_worker = self._worker_windows if sys.platform == "win32" else self._worker_posix
        self._thread = threading.Thread(target=target_worker, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self.active = False
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.2)
        self._thread = None

    def __enter__(self) -> LiveInputListener:
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.stop()

    async def __aenter__(self) -> LiveInputListener:
        self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.stop()
