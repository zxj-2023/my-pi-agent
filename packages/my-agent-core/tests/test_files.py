"""四个文件工具离线测试（真文件系统 tmp_path，无需 FakeLLM）。"""
from my_agent_core.tools.builtin import (
    make_bash_tool,
    make_edit_tool,
    make_read_tool,
    make_write_tool,
)


def test_read_basic(tmp_path):
    """读文件全文（#2）。"""
    read = make_read_tool(tmp_path)
    (tmp_path / "a.txt").write_text("line1\nline2\nline3", encoding="utf-8")
    result = read.execute({"path": "a.txt"})
    assert result.ok is True
    assert result.data == "line1\nline2\nline3"


def test_read_limit(tmp_path):
    """limit 截断 + '... (N more)'（#2）。"""
    read = make_read_tool(tmp_path)
    (tmp_path / "a.txt").write_text("\n".join(f"l{i}" for i in range(10)), encoding="utf-8")
    result = read.execute({"path": "a.txt", "limit": 3})
    assert "... (7 more)" in result.data


def test_read_escape(tmp_path):
    """路径逃逸 → 'escapes workspace'（#1）。"""
    read = make_read_tool(tmp_path)
    result = read.execute({"path": "../secret.txt"})
    assert "escapes workspace" in result.data


def test_read_missing(tmp_path):
    """不存在文件 → 'Error'（#2）。"""
    read = make_read_tool(tmp_path)
    result = read.execute({"path": "nope.txt"})
    assert "Error" in result.data


def test_write_creates_and_overwrites(tmp_path):
    """写文件（自动建父目录）+ 覆盖 + 返回字节数（#3）。"""
    write = make_write_tool(tmp_path)
    result = write.execute({"path": "sub/dir/a.txt", "content": "hello"})
    assert result.data == "Wrote 5 bytes"
    assert (tmp_path / "sub" / "dir" / "a.txt").read_text(encoding="utf-8") == "hello"
    write.execute({"path": "sub/dir/a.txt", "content": "world"})
    assert (tmp_path / "sub" / "dir" / "a.txt").read_text(encoding="utf-8") == "world"


def test_edit_replaces_once(tmp_path):
    """精确替换一次（#4）。"""
    edit = make_edit_tool(tmp_path)
    (tmp_path / "a.txt").write_text("hello world hello", encoding="utf-8")
    result = edit.execute({"path": "a.txt", "old_text": "hello", "new_text": "hi"})
    assert result.data == "Edited a.txt"
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "hi world hello"


def test_edit_text_not_found(tmp_path):
    """old_text 不存在 → 'Text not found'（#4）。"""
    edit = make_edit_tool(tmp_path)
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    result = edit.execute({"path": "a.txt", "old_text": "nope", "new_text": "x"})
    assert "Text not found" in result.data


def test_bash_normal(tmp_path):
    """正常命令返回 stdout（#5）。"""
    bash = make_bash_tool(tmp_path)
    result = bash.execute({"command": "echo hi"})
    assert result.data == "hi"


def test_bash_dangerous(tmp_path):
    """危险命令 → blocked（#6）。"""
    bash = make_bash_tool(tmp_path)
    result = bash.execute({"command": "sudo rm -rf /"})
    assert result.data == "Error: Dangerous command blocked"


def test_bash_timeout(tmp_path, monkeypatch):
    """超时 → 'Timeout'（#7）。用 monkeypatch 缩短超时避免等 120s。"""
    from my_agent_core.tools.builtin import files
    monkeypatch.setattr(files, "_TIMEOUT_SECONDS", 1)
    bash = make_bash_tool(tmp_path)
    result = bash.execute({"command": "sleep 5"})
    assert "Timeout" in result.data
