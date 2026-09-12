import contextlib
import sys


def _is_utf8_encoding(encoding: str | None) -> bool:
    if encoding is None:
        return False
    return encoding.lower().replace("-", "").replace("_", "") == "utf8"


def _force_utf8_streams() -> None:
    for stream in (sys.stdout, sys.stderr):
        if stream and not _is_utf8_encoding(getattr(stream, "encoding", None)):
            with contextlib.suppress(AttributeError, ValueError, Exception):
                reconfigure = getattr(stream, "reconfigure", None)
                if callable(reconfigure):
                    reconfigure(encoding="utf-8", errors="replace")
