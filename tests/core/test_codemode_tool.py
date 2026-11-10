import pytest

from my_agent_core.registry import ToolRegistry
from my_agent_core.tools import Tool
from my_agent_core.tools.codemode import (
    CodemodeResult,
    CodemodeSourceError,
    format_script_output,
    make_codemode_tool,
    parse_options,
    truncate_codemode_output,
)
from my_agent_core.codemode.bridge import ScriptResult


pytestmark = pytest.mark.anyio


# --- Unit Tests: parse_options ---


def test_parse_options_default():
    max_tokens, timeout = parse_options("text(1 + 2);")
    assert max_tokens == 10000
    assert timeout is None


def test_parse_options_valid_line_1():
    code = '// @options: {"max_output_tokens": 500, "timeout_ms": 2000}\ntext("hello");'
    max_tokens, timeout = parse_options(code)
    assert max_tokens == 500
    assert timeout == 2000


def test_parse_options_leading_spaces():
    code = '   // @options: {"timeout_ms": 5000}\ntext("hello");'
    max_tokens, timeout = parse_options(code)
    assert max_tokens == 10000
    assert timeout == 5000


def test_parse_options_misplaced_line_2_fails():
    code = 'const a = 1;\n// @options: {"max_output_tokens": 100}\ntext(a);'
    with pytest.raises(CodemodeSourceError) as exc_info:
        parse_options(code)
    assert "The // @options: line must be the first line of the input" in str(exc_info.value)


def test_parse_options_not_starting_on_line_1_fails():
    code = 'const x = 1; // @options: {"timeout_ms": 100}'
    with pytest.raises(CodemodeSourceError) as exc_info:
        parse_options(code)
    assert "The // @options: line must be the first line of the input" in str(exc_info.value)


def test_parse_options_invalid_json_fails():
    code = "// @options: {bad json}\ntext(1);"
    with pytest.raises(CodemodeSourceError) as exc_info:
        parse_options(code)
    assert "Invalid JSON in // @options:" in str(exc_info.value)


def test_parse_options_unknown_key_fails():
    code = '// @options: {"foo": 123}\ntext(1);'
    with pytest.raises(CodemodeSourceError) as exc_info:
        parse_options(code)
    assert "Unknown option 'foo'" in str(exc_info.value)


def test_parse_options_invalid_types_fail():
    with pytest.raises(CodemodeSourceError) as exc1:
        parse_options('// @options: {"max_output_tokens": -5}')
    assert "non-negative integer" in str(exc1.value)

    with pytest.raises(CodemodeSourceError) as exc2:
        parse_options('// @options: {"timeout_ms": 0}')
    assert "positive integer" in str(exc2.value)


# --- Unit Tests: format_script_output ---


def test_format_output_single_text():
    res = ScriptResult(ok=True, wall_time=0.12, text_items=["hello world"])
    out = format_script_output(res)
    assert out == "Script completed (0.1s)\nhello world"


def test_format_output_multiple_texts():
    res = ScriptResult(ok=True, wall_time=0.25, text_items=["line 1", "line 2"])
    out = format_script_output(res)
    expected = "Script completed (0.2s)\n==> text 1/2 <==\nline 1\n\n==> text 2/2 <==\nline 2"
    assert out == expected


def test_format_output_console_only():
    res = ScriptResult(ok=True, wall_time=0.08, console_lines=["log 1", "log 2"])
    out = format_script_output(res)
    expected = "Script completed (0.1s)\n<console_output>\nlog 1\nlog 2\n</console_output>"
    assert out == expected


def test_format_output_text_and_console():
    res = ScriptResult(
        ok=True,
        wall_time=0.15,
        text_items=["done"],
        console_lines=["debug 1"],
    )
    out = format_script_output(res)
    expected = "Script completed (0.1s)\ndone\n\n<console_output>\ndebug 1\n</console_output>"
    assert out == expected


def test_format_output_no_output():
    res = ScriptResult(ok=True, wall_time=0.05)
    out = format_script_output(res)
    assert out == "Script completed (0.1s)\n(no output)"


def test_format_output_failure():
    res = ScriptResult(
        ok=False,
        wall_time=0.04,
        error="SyntaxError: Unexpected identifier",
        console_lines=["compiling..."],
    )
    out = format_script_output(res)
    expected = (
        "Script failed (0.0s)\n"
        "<console_output>\ncompiling...\n</console_output>\n"
        "Script error:\nSyntaxError: Unexpected identifier"
    )
    assert out == expected


# --- Unit Tests: truncate_codemode_output ---


def test_truncate_codemode_output_within_limit():
    short_text = "short text"
    assert truncate_codemode_output(short_text, max_output_tokens=100) == short_text


def test_truncate_codemode_output_exceeding_limit():
    huge_text = "HEAD_" + ("x" * 2000) + "_TAIL"
    # max_output_tokens = 50 -> max_chars = 200
    truncated = truncate_codemode_output(huge_text, max_output_tokens=50)
    assert len(truncated) <= 200
    assert truncated.startswith("HEAD_")
    assert truncated.endswith("_TAIL")
    assert "characters omitted" in truncated


# --- Async Integration Tests: CodemodeTool Execution ---


async def test_codemode_tool_basic_execution():
    registry = ToolRegistry()
    tool = make_codemode_tool(registry)

    res = await tool.execute({"code": "text('Hello from JS');"})
    assert res.ok is True
    assert "Script completed" in res.content
    assert "Hello from JS" in res.content


async def test_codemode_tool_calling_registry_tools():
    registry = ToolRegistry()

    def add(a: int, b: int) -> int:
        """Add two numbers."""
        return a + b

    registry.register(Tool(add, name="add"))
    tool = make_codemode_tool(registry)

    js_code = """
    const sum = await tools.add({ a: 10, b: 25 });
    text("Sum is: " + sum);
    """
    res = await tool.execute({"code": js_code})
    assert res.ok is True
    assert "Sum is: 35" in res.content


async def test_codemode_tool_options_misplaced_fails_safely():
    registry = ToolRegistry()
    tool = make_codemode_tool(registry)

    js_code = """
    const x = 1;
    // @options: {"timeout_ms": 1000}
    text(x);
    """
    res = await tool.execute({"code": js_code})
    assert res.ok is False
    assert "Script failed" in res.content
    assert "CodemodeSourceError: The // @options: line must be the first line of the input" in res.content


async def test_codemode_tool_syntax_error_reporting():
    registry = ToolRegistry()
    tool = make_codemode_tool(registry)

    res = await tool.execute({"code": "const a = ;"})
    assert res.ok is False
    assert "Script failed" in res.content
    assert "Script error:" in res.content


async def test_codemode_tool_dynamic_declarations():
    registry = ToolRegistry()

    def greet(name: str) -> str:
        """Say hello to a user."""
        return f"Hello {name}"

    registry.register(Tool(greet, name="greet"))
    tool = make_codemode_tool(registry)

    schema = tool.to_openai_schema()
    desc = schema["function"]["description"]

    # Verify TS declaration block includes greet and excludes codemode
    assert "greet(args: { name: string; }): Promise<string>;" in desc
    assert "codemode(" not in desc


async def test_codemode_result_string_compatibility():
    res = CodemodeResult(ok=True, content="Script completed (0.1s)\nSuccess")
    assert res == "Script completed (0.1s)\nSuccess"
    assert "Success" in res
    assert str(res) == "Script completed (0.1s)\nSuccess"
    assert res.data == "Script completed (0.1s)\nSuccess"


async def test_codemode_tool_output_truncation_in_execution():
    registry = ToolRegistry()
    tool = make_codemode_tool(registry)

    # 100 tokens limit -> 400 chars max
    js_code = """// @options: {"max_output_tokens": 100}
    text("START_" + "A".repeat(1000) + "_END");
    """
    res = await tool.execute({"code": js_code})
    assert res.ok is True
    assert len(res.content) <= 400
    assert "START_" in res.content
    assert "_END" in res.content
    assert "characters omitted" in res.content


async def test_codemode_tool_no_output_execution():
    registry = ToolRegistry()
    tool = make_codemode_tool(registry)

    res = await tool.execute({"code": "const x = 1;"})
    assert res.ok is True
    assert "(no output)" in res.content


async def test_codemode_tool_tool_error_handling_in_js():
    registry = ToolRegistry()

    def buggy() -> str:
        """Buggy tool."""
        raise RuntimeError("database unreachable")

    registry.register(Tool(buggy, name="buggy"))
    tool = make_codemode_tool(registry)

    # Catching error in JS
    js_catch = """
    try {
        await tools.buggy();
    } catch (err) {
        text("Caught error: " + err.message);
    }
    """
    res_catch = await tool.execute({"code": js_catch})
    assert res_catch.ok is True
    assert "database unreachable" in res_catch.content

    # Uncaught error in JS
    js_uncaught = "await tools.buggy();"
    res_uncaught = await tool.execute({"code": js_uncaught})
    assert res_uncaught.ok is False
    assert "Script failed" in res_uncaught.content
    assert "database unreachable" in res_uncaught.content
