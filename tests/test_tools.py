"""tools.py 离线测试：schema 生成（装饰期）+ call_tool 分发（运行期）。

无需 API key。测试清单对应
docs/superpowers/specs/2026-08-03-pydantic-tool-schema-design.md §7。
"""
from types import SimpleNamespace
from typing import Literal, Optional

import pytest
from pydantic import BaseModel

from my_agent_core.tools import Tool, call_tool, schemas_for, tool


def make_tool_call(name: str, arguments: str) -> SimpleNamespace:
    """构造与 OpenAI SDK 结构一致的假 tool_call。"""
    return SimpleNamespace(function=SimpleNamespace(name=name, arguments=arguments))


# ---------- 装饰期：schema 生成（规格 §7 #1–#8） ----------


def test_schema_basic_types():
    """#1 基本类型 → JSON Schema 类型名。"""

    @tool
    def f(a: int, b: str, c: float, d: bool) -> None:
        """doc"""

    assert f.parameters == {
        "type": "object",
        "properties": {
            "a": {"type": "integer"},
            "b": {"type": "string"},
            "c": {"type": "number"},
            "d": {"type": "boolean"},
        },
        "required": ["a", "b", "c", "d"],
    }


def test_schema_zero_params():
    """#2 零参数工具。"""

    @tool
    def f() -> str:
        """doc"""

    assert f.parameters == {"type": "object", "properties": {}}


def test_schema_default_values():
    """#3 默认值参数 → 不进 required，schema 含 default。"""

    @tool
    def f(city: str, retries: int = 3) -> None:
        """doc"""

    assert f.parameters["required"] == ["city"]
    assert f.parameters["properties"]["retries"] == {"type": "integer", "default": 3}


def test_schema_optional():
    """#4 Optional：无默认值仍必填（anyOf 形式）；= None 时可选。"""

    @tool
    def f(a: Optional[int], b: Optional[int] = None) -> None:
        """doc"""

    props = f.parameters["properties"]
    assert props["a"] == {"anyOf": [{"type": "integer"}, {"type": "null"}]}
    assert f.parameters["required"] == ["a"]
    assert props["b"]["anyOf"] == [{"type": "integer"}, {"type": "null"}]
    assert props["b"]["default"] is None


def test_schema_complex_types():
    """#5 list / dict / Literal / 嵌套 BaseModel。"""

    class Address(BaseModel):
        city: str

    @tool
    def f(
        tags: list[str],
        meta: dict[str, int],
        mode: Literal["fast", "slow"],
        addr: Address,
    ) -> None:
        """doc"""

    props = f.parameters["properties"]
    assert props["tags"] == {"type": "array", "items": {"type": "string"}}
    assert props["meta"] == {"type": "object", "additionalProperties": {"type": "integer"}}
    assert props["mode"]["enum"] == ["fast", "slow"]
    assert props["addr"] == {"$ref": "#/$defs/Address"}
    assert f.parameters["$defs"]["Address"]["properties"]["city"] == {"type": "string"}


def test_schema_has_no_titles():
    """#6 schema 各级均无 title 键。"""

    @tool
    def f(city: str, count: int = 1) -> None:
        """doc"""

    def collect_keys(node):
        if isinstance(node, dict):
            yield from node.keys()
            for v in node.values():
                yield from collect_keys(v)
        elif isinstance(node, list):
            for item in node:
                yield from collect_keys(item)

    assert "title" not in list(collect_keys(f.parameters))


def test_reject_missing_annotation():
    """#7a 无类型标注 → 装饰时 TypeError。"""
    with pytest.raises(TypeError, match="没有类型标注"):

        @tool
        def f(city) -> None:  # noqa: ANN001
            """doc"""


def test_reject_varargs():
    """#7b *args / **kwargs → 装饰时 TypeError。"""
    with pytest.raises(TypeError, match="不支持"):

        @tool
        def f(*args: int) -> None:
            """doc"""

    with pytest.raises(TypeError, match="不支持"):

        @tool
        def g(**kwargs: int) -> None:
            """doc"""


def test_name_and_description():
    """#8 name / description 取自函数名 / docstring。"""

    @tool
    def get_weather(city: str) -> str:
        """Get the weather for a city."""
        return ""

    assert get_weather.name == "get_weather"
    assert get_weather.description == "Get the weather for a city."


def test_schemas_for_shape():
    """#15 schemas_for 输出形状回归。"""

    @tool
    def multiply(a: int, b: int) -> int:
        """Multiply two integers."""
        return a * b

    assert schemas_for([multiply]) == [
        {
            "type": "function",
            "function": {
                "name": "multiply",
                "description": "Multiply two integers.",
                "parameters": multiply.parameters,
            },
        }
    ]


# ---------- 运行期：call_tool 校验与分发（规格 §7 #9–#14） ----------


@tool
def multiply(a: int, b: int) -> int:
    """Multiply two integers."""
    return a * b


@tool
def greet(name: str, greeting: str = "Hello") -> str:
    """Greet someone."""
    return f"{greeting}, {name}!"


def _registry(*tools: Tool) -> dict[str, Tool]:
    return {t.name: t for t in tools}


def test_call_tool_success():
    """#9 正常调用返回 str(result)。"""
    result = call_tool(make_tool_call("multiply", '{"a": 6, "b": 7}'), _registry(multiply))
    assert result == "42"


def test_call_tool_coerces_string_to_int():
    """#10 类型强转："37" → 37。"""
    result = call_tool(make_tool_call("multiply", '{"a": "6", "b": 7}'), _registry(multiply))
    assert result == "42"


def test_call_tool_missing_required():
    """#11a 缺必填 → 逐条错误消息。"""
    result = call_tool(make_tool_call("multiply", '{"a": 6}'), _registry(multiply))
    assert result.startswith('Validation failed for tool "multiply":')
    assert "b: Field required" in result


def test_call_tool_wrong_type():
    """#11b 类型不符 → 逐条错误消息。"""
    result = call_tool(make_tool_call("multiply", '{"a": "abc", "b": 7}'), _registry(multiply))
    assert result.startswith('Validation failed for tool "multiply":')
    assert "a: Input should be a valid integer" in result


def test_call_tool_extra_argument():
    """#11c 多余参数 → 逐条错误消息。"""
    result = call_tool(make_tool_call("multiply", '{"a": 6, "b": 7, "c": 8}'), _registry(multiply))
    assert result.startswith('Validation failed for tool "multiply":')
    assert "c: Extra inputs are not permitted" in result


def test_call_tool_applies_defaults():
    """#13 默认值参数不传 → 函数收到默认值。"""
    result = call_tool(make_tool_call("greet", '{"name": "pi"}'), _registry(greet))
    assert result == "Hello, pi!"


def test_call_tool_unknown_tool():
    """#14a 回归：未知工具名。"""
    result = call_tool(make_tool_call("nope", "{}"), _registry(multiply))
    assert result == "Unknown tool 'nope'. Available: multiply"


def test_call_tool_invalid_json():
    """#14b 回归：非法 JSON。"""
    result = call_tool(make_tool_call("multiply", "{not json"), _registry(multiply))
    assert result.startswith("Invalid JSON arguments for tool 'multiply':")


def test_call_tool_tool_exception():
    """#14c 回归：工具自身异常 → 错误字符串，永不抛。"""

    @tool
    def boom(x: int) -> int:
        """Always fails."""
        raise RuntimeError("kaboom")

    result = call_tool(make_tool_call("boom", '{"x": 1}'), _registry(boom))
    assert result == "Error executing tool 'boom': kaboom"


def test_call_tool_nondict_json_never_raises():
    """#14d 回归：arguments 解析出非 dict 也不抛。"""
    result = call_tool(make_tool_call("multiply", "[1, 2]"), _registry(multiply))
    assert result.startswith('Validation failed for tool "multiply":')
