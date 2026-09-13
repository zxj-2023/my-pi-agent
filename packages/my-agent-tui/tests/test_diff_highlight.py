from rich.text import Text
from my_agent_tui.diff import render_diff_with_word_highlight


def test_diff_word_highlight_single_replacement():
    diff_sample = (
        "--- a/src/app.py\n"
        "+++ b/src/app.py\n"
        "@@ -1,3 +1,3 @@\n"
        "-def add(a, b): return a - b\n"
        "+def add(a, b): return a + b\n"
    )
    rendered = render_diff_with_word_highlight(diff_sample)
    assert isinstance(rendered, Text)
    plain = rendered.plain
    assert "--- a/src/app.py" in plain
    assert "+++ b/src/app.py" in plain
    assert "return a - b" in plain
    assert "return a + b" in plain


def test_diff_word_highlight_pure_add_and_delete():
    diff_sample = "--- a/test.py\n+++ b/test.py\n@@ -1,2 +1,3 @@\n+new_line_1\n-deleted_line_2\n+added_line_3\n"
    rendered = render_diff_with_word_highlight(diff_sample)
    assert "new_line_1" in rendered.plain
    assert "deleted_line_2" in rendered.plain


def test_diff_word_highlight_style_spans():
    diff_sample = "--- a/math.py\n+++ b/math.py\n@@ -1,1 +1,1 @@\n-x = 1\n+x = 2\n"
    rendered = render_diff_with_word_highlight(diff_sample)
    assert isinstance(rendered, Text)
    # Check that styles contain reverse highlighting for replaced words
    styles = [span.style for span in rendered.spans]
    assert any("reverse" in str(s) for s in styles)
