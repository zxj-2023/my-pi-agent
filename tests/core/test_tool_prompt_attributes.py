"""测试 Tool 类与 @tool 装饰器的提示词元数据自声明能力。"""

from my_agent_core.tools import Tool, tool


def test_tool_explicit_prompt_metadata():
    """显式指定 prompt_snippet 与 prompt_guidelines。"""

    def dummy(x: int) -> str:
        """This is a dummy tool with multiple sentences. Here is the second sentence."""
        return str(x)

    t = Tool(
        dummy,
        description="Detailed multi-line description of dummy tool. More details.",
        prompt_snippet="Execute dummy operation",
        prompt_guidelines=["Never run dummy with negative numbers.", "Always verify output."],
    )

    assert t.prompt_snippet == "Execute dummy operation"
    assert t.prompt_guidelines == [
        "Never run dummy with negative numbers.",
        "Always verify output.",
    ]


def test_tool_automatic_snippet_fallback():
    """未显式提供 prompt_snippet 时，自动从 description 提取首句作为精炼概要。"""

    def my_fetch(url: str) -> str:
        """Fetch content from remote HTTP/HTTPS url.

        Supports various protocols and options.
        """
        return url

    t = Tool(my_fetch)
    # 应截取首句并清理句末句号
    assert t.prompt_snippet == "Fetch content from remote HTTP/HTTPS url"
    assert t.prompt_guidelines == []


def test_tool_empty_description_fallback():
    """无 description 时，prompt_snippet 为安全空字符串。"""

    def no_doc(x: str) -> str:
        return x

    t = Tool(no_doc)
    assert t.prompt_snippet == ""
    assert t.prompt_guidelines == []


def test_tool_decorator_propagates_prompt_metadata():
    """@tool 装饰器能够正确透传 prompt_snippet 与 prompt_guidelines。"""

    @tool(
        name="custom_reader",
        description="Read file contents safely. Supports pagination.",
        prompt_snippet="Read file contents",
        prompt_guidelines=["Use read instead of cat or sed."],
    )
    def custom_reader(path: str) -> str:
        return path

    t: Tool = custom_reader  # pyright: ignore[reportAssignmentType]
    assert t.name == "custom_reader"
    assert t.prompt_snippet == "Read file contents"
    assert t.prompt_guidelines == ["Use read instead of cat or sed."]
