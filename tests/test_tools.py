"""tools.py 离线测试：schema 生成（装饰期）+ Tool 类能力（执行期）。

无需 API key。测试清单对应
docs/superpowers/specs/2026-08-03-pydantic-tool-schema-design.md §7。
"""
from typing import Literal, Optional

import pytest
from pydantic import BaseModel

from my_agent_core.tools import ToolResult, tool


# ---------- 装饰期：schema 生成（规格 §7 #1–#8） ----------


def test_schema_basic_types():
    """#1 基本类型 → JSON Schema 类型名。"""

    @tool
    def f(a: int, b: str, c: float, d: bool) -> None:
        """doc"""

    params = f.to_openai_schema()["function"]["parameters"]
    assert params["type"] == "object"
    assert params["required"] == ["a", "b", "c", "d"]
    assert params["properties"]["a"]["type"] == "integer"
    assert params["properties"]["b"]["type"] == "string"
    assert params["properties"]["c"]["type"] == "number"
    assert params["properties"]["d"]["type"] == "boolean"


def test_schema_zero_params():
    """#2 零参数工具。"""

    @tool
    def f() -> str:
        """doc"""

    params = f.to_openai_schema()["function"]["parameters"]
    assert params["type"] == "object"
    assert params["properties"] == {}


def test_schema_default_values():
    """#3 默认值参数 → 不进 required，schema 含 default。"""

    @tool
    def f(city: str, retries: int = 3) -> None:
        """doc"""

    params = f.to_openai_schema()["function"]["parameters"]
    assert params["required"] == ["city"]
    assert params["properties"]["retries"]["type"] == "integer"
    assert params["properties"]["retries"]["default"] == 3


def test_schema_optional():
    """#4 Optional：无默认值仍必填（anyOf 形式）；= None 时可选。"""

    @tool
    def f(a: Optional[int], b: Optional[int] = None) -> None:
        """doc"""

    params = f.to_openai_schema()["function"]["parameters"]
    props = params["properties"]
    assert params["required"] == ["a"]
    assert props["a"]["anyOf"] == [{"type": "integer"}, {"type": "null"}]
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

    params = f.to_openai_schema()["function"]["parameters"]
    props = params["properties"]
    assert props["tags"]["type"] == "array"
    assert props["tags"]["items"] == {"type": "string"}
    assert props["meta"]["type"] == "object"
    assert props["meta"]["additionalProperties"] == {"type": "integer"}
    assert props["mode"]["enum"] == ["fast", "slow"]
    assert props["addr"] == {"$ref": "#/$defs/Address"}
    assert params["$defs"]["Address"]["properties"]["city"]["type"] == "string"


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


# ---------- Tool 类能力（新增） ----------


def test_tool_name_override():
    """name 覆盖：@tool(name=...)。"""
    from my_agent_core.tools import tool as _tool

    @_tool(name="get_weather_v2")
    def f(city: str) -> str:
        """doc"""
        return ""

    assert f.name == "get_weather_v2"


def test_tool_description_override():
    """description 覆盖：@tool(description=...)。"""
    from my_agent_core.tools import tool as _tool

    @_tool(description="Override desc")
    def f(city: str) -> str:
        """Original doc"""
        return ""

    assert f.description == "Override desc"


def test_tool_params_model_override():
    """params_model 覆盖：外部传入 BaseModel。"""
    from my_agent_core.tools import tool as _tool
    from pydantic import BaseModel as BM

    class MyArgs(BM):
        city: str

    @_tool(params_model=MyArgs)
    def f(city: str) -> str:
        """doc"""
        return city

    assert f.params_model is MyArgs
    result = f.execute({"city": "北京"})
    assert result.ok and result.data == "北京"


def test_tool_factory_usage():
    """@tool() 带括号与 @tool 不带括号两种用法等价。"""
    from my_agent_core.tools import tool as _tool

    @_tool()
    def a(x: int) -> int:
        """doc"""
        return x

    @_tool
    def b(x: int) -> int:
        """doc"""
        return x

    assert a.name == "a" and b.name == "b"
    # 两种用法等价：参数结构一致（title/类名噪音不同，比较语义字段）
    assert (
        a.to_openai_schema()["function"]["parameters"]["properties"]
        == b.to_openai_schema()["function"]["parameters"]["properties"]
    )
    assert (
        a.to_openai_schema()["function"]["parameters"]["required"]
        == b.to_openai_schema()["function"]["parameters"]["required"]
    )


def test_tool_callable():
    """__call__ 直接调用函数本体。"""

    @tool
    def multiply(a: int, b: int) -> int:
        """Multiply two integers."""
        return a * b

    assert multiply(6, 7) == 42


def test_tool_execute_success():
    """execute 成功 → ToolResult(ok=True, data=...)。"""

    @tool
    def multiply(a: int, b: int) -> int:
        """Multiply two integers."""
        return a * b

    result = multiply.execute({"a": 6, "b": 7})
    assert result.ok is True
    assert result.data == 42
    assert result.error is None


def test_tool_execute_validation_error():
    """execute 校验失败 → ToolResult(ok=False)，永不抛。"""

    @tool
    def f(a: int) -> int:
        """doc"""
        return a

    result = f.execute({"a": "abc"})
    assert result.ok is False
    assert result.error is not None
    assert "Input should be a valid integer" in result.error


def test_tool_execute_tool_exception():
    """execute 工具异常 → ToolResult(ok=False)，永不抛。"""

    @tool
    def boom(x: int) -> int:
        """Always fails."""
        raise RuntimeError("kaboom")

    result = boom.execute({"x": 1})
    assert result.ok is False
    assert result.error == "Error executing tool 'boom': kaboom"


def test_tool_result_serialize():
    """ToolResult.serialize：成功返回 str(data)，失败返回错误文本。"""
    assert ToolResult(ok=True, data=42).serialize() == "42"
    assert ToolResult(ok=False, error="bad").serialize() == "bad"
    assert ToolResult(ok=False).serialize() == "Unknown error"
