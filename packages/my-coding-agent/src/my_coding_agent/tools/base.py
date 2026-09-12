from pathlib import Path

DEFAULT_MAX_LINES = 2000
DEFAULT_MAX_BYTES = 50 * 1024  # 50KB
DEFAULT_IGNORE_DIRS = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
}


def resolve_path(workspace: Path, p: str | Path) -> Path:
    raw = Path(p)
    if raw.is_absolute():
        return raw.resolve()
    return (workspace / raw).resolve()


def is_binary_file(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            chunk = f.read(1024)
            return b"\x00" in chunk
    except Exception:
        return False
