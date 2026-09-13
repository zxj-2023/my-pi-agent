from pathlib import Path

from my_coding_agent.tools.base import (
    DEFAULT_IGNORE_DIRS,
    DEFAULT_MAX_BYTES,
    DEFAULT_MAX_LINES,
    is_binary_file,
    resolve_path,
)


def test_resolve_path_relative(tmp_path: Path):
    target = resolve_path(tmp_path, "src/main.py")
    assert target == (tmp_path / "src/main.py").resolve()


def test_resolve_path_absolute(tmp_path: Path):
    abs_file = (tmp_path.parent / "config.toml").resolve()
    target = resolve_path(tmp_path, str(abs_file))
    assert target == abs_file


def test_resolve_path_parent_traversal(tmp_path: Path):
    target = resolve_path(tmp_path, "../sibling/file.txt")
    assert target == (tmp_path.parent / "sibling/file.txt").resolve()


def test_resolve_path_with_path_instance(tmp_path: Path):
    target = resolve_path(tmp_path, Path("sub/dir/file.py"))
    assert target == (tmp_path / "sub" / "dir" / "file.py").resolve()


def test_is_binary_file(tmp_path: Path):
    text_file = tmp_path / "text.txt"
    text_file.write_text("hello world", encoding="utf-8")
    assert not is_binary_file(text_file)

    bin_file = tmp_path / "bin.dat"
    bin_file.write_bytes(b"hello\x00world")
    assert is_binary_file(bin_file)

    missing_file = tmp_path / "missing.txt"
    assert not is_binary_file(missing_file)


def test_constants():
    assert DEFAULT_MAX_LINES == 2000
    assert DEFAULT_MAX_BYTES == 50 * 1024
    assert ".git" in DEFAULT_IGNORE_DIRS
    assert "node_modules" in DEFAULT_IGNORE_DIRS
    assert "__pycache__" in DEFAULT_IGNORE_DIRS
