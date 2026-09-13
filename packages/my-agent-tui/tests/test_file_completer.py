from pathlib import Path

from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.document import Document

from my_agent_tui.components.completer import FileReferenceCompleter


def test_file_completer_matches_at_prefix(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src/calc.py").write_text("", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_calc.py").write_text("", encoding="utf-8")

    completer = FileReferenceCompleter(workspace=tmp_path)
    doc = Document("请查看 @src/ca")
    completions = [c.text for c in completer.get_completions(doc, None)]
    assert "@src/calc.py" in completions
    assert "@tests/test_calc.py" not in completions


def test_file_completer_skips_ignored_dirs(tmp_path: Path) -> None:
    venv_dir = tmp_path / ".venv/lib"
    venv_dir.mkdir(parents=True)
    (venv_dir / "secret.py").write_text("", encoding="utf-8")

    completer = FileReferenceCompleter(workspace=tmp_path)
    doc = Document("引用 @sec")
    completions = [c.text for c in completer.get_completions(doc, None)]
    assert completions == []


def test_file_completer_delegates_to_base_completer(tmp_path: Path) -> None:
    base = WordCompleter(["/help", "/clear", "/exit"], ignore_case=True, sentence=True)
    completer = FileReferenceCompleter(workspace=tmp_path, base_completer=base)

    doc = Document("/he")
    completions = [c.text for c in completer.get_completions(doc, None)]
    assert "/help" in completions
    assert "/clear" not in completions


def test_file_completer_no_base_completer(tmp_path: Path) -> None:
    completer = FileReferenceCompleter(workspace=tmp_path)
    doc = Document("普通文本无@符号")
    completions = list(completer.get_completions(doc, None))
    assert completions == []


def test_file_completer_bare_at_lists_all_files(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("", encoding="utf-8")
    (tmp_path / "b.py").write_text("", encoding="utf-8")

    completer = FileReferenceCompleter(workspace=tmp_path)
    doc = Document("查看 @")
    completions = [c.text for c in completer.get_completions(doc, None)]
    assert "@a.txt" in completions
    assert "@b.py" in completions


def test_file_completer_metadata_and_position(tmp_path: Path) -> None:
    (tmp_path / "main.py").write_text("", encoding="utf-8")

    completer = FileReferenceCompleter(workspace=tmp_path)
    doc = Document("read @ma")
    completions = list(completer.get_completions(doc, None))
    assert len(completions) == 1
    c = completions[0]
    assert c.text == "@main.py"
    assert c.display_text == "@main.py"
    assert c.display_meta_text == "file"
    assert c.start_position == -len("@ma")
