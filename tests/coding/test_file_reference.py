from pathlib import Path

from my_coding_agent.file_reference import FileReferenceParser


def test_parse_references() -> None:
    parser = FileReferenceParser(".")
    text = "请帮我重构 @src/main.py 和 @tests/test_main.py 谢谢"
    refs = parser.parse_references(text)
    assert refs == ["src/main.py", "tests/test_main.py"]


def test_parse_references_dedup() -> None:
    parser = FileReferenceParser(".")
    text = "对比 @src/a.py 与 @src/b.py 以及 @src/a.py"
    refs = parser.parse_references(text)
    assert refs == ["src/a.py", "src/b.py"]


def test_resolve_reference_existing_file(tmp_path: Path) -> None:
    f = tmp_path / "calc.py"
    f.write_text("def add(a, b): return a + b\n", encoding="utf-8")
    parser = FileReferenceParser(tmp_path)
    ok, path, content = parser.resolve_reference("calc.py")
    assert ok is True
    assert path == f
    assert "def add" in content


def test_resolve_reference_missing_file(tmp_path: Path) -> None:
    parser = FileReferenceParser(tmp_path)
    ok, path, content = parser.resolve_reference("missing.py")
    assert ok is False
    assert path is None
    assert "File not found" in content


def test_resolve_reference_directory(tmp_path: Path) -> None:
    d = tmp_path / "subdir"
    d.mkdir()
    parser = FileReferenceParser(tmp_path)
    ok, path, content = parser.resolve_reference("subdir")
    assert ok is False
    assert path == d
    assert "Path is a directory" in content


def test_resolve_reference_binary_file(tmp_path: Path) -> None:
    bin_file = tmp_path / "test.bin"
    bin_file.write_bytes(b"\x00\x01\x02\x03hello")
    parser = FileReferenceParser(tmp_path)
    ok, path, content = parser.resolve_reference("test.bin")
    assert ok is False
    assert path == bin_file
    assert "Cannot reference binary file" in content


def test_resolve_reference_line_truncation(tmp_path: Path) -> None:
    f = tmp_path / "large_lines.txt"
    f.write_text("\n".join(f"line {i}" for i in range(2500)), encoding="utf-8")
    parser = FileReferenceParser(tmp_path)
    ok, path, content = parser.resolve_reference("large_lines.txt")
    assert ok is True
    assert "[File truncated at 2000 lines]" in content
    assert "line 1999" in content
    assert "line 2005" not in content


def test_resolve_reference_byte_truncation(tmp_path: Path) -> None:
    f = tmp_path / "large_bytes.txt"
    f.write_text("x" * (60 * 1024), encoding="utf-8")
    parser = FileReferenceParser(tmp_path)
    ok, path, content = parser.resolve_reference("large_bytes.txt")
    assert ok is True
    assert "[File truncated at 50KB]" in content
    assert len(content.encode("utf-8")) <= 50 * 1024 + 100


def test_expand_references_appends_block(tmp_path: Path) -> None:
    f = tmp_path / "hello.py"
    f.write_text("print('hello')\n", encoding="utf-8")
    parser = FileReferenceParser(tmp_path)
    expanded = parser.expand_references("请检查 @hello.py 的逻辑")
    assert "请检查 @hello.py 的逻辑" in expanded
    assert "<referenced_files>" in expanded
    assert '<referenced_file path="hello.py">' in expanded
    assert "print('hello')" in expanded


def test_expand_references_no_refs() -> None:
    parser = FileReferenceParser(".")
    text = "没有任何引用的普通提问"
    assert parser.expand_references(text) == text


def test_expand_references_missing_files_only(tmp_path: Path) -> None:
    parser = FileReferenceParser(tmp_path)
    text = "请查看 @nonexistent.py"
    assert parser.expand_references(text) == text
