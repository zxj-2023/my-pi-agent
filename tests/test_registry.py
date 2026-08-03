"""ToolRegistry 离线测试：注册/查表/批量 schema/执行（含错误路径）。

无需 API key。对应 docs/superpowers/specs/2026-08-03-tool-class-design.md §7。
"""
from types import SimpleNamespace

from my_agent_core.registry import ToolRegistry
from my_agent_core.tools import tool


def make_tool_call(name: str, arguments: str) -> SimpleNamespace:
    """构造与 OpenAI SDK 结构一致的假 tool_call。"""
    return SimpleNamespace(function=SimpleNamespace(name=name, arguments=arguments))


@tool
def multiply(a: int, b: int) -> int:
    """Multiply two integers."""
    return a * b


@tool
def greet(name: str, greeting: str = "Hello") -> str:
    """Greet someone."""
    return f"{greeting}, {name}!"


def _registry(*tools) -> ToolRegistry:
    reg = ToolRegistry()
    for t in tools:
        reg.register(t)
    return reg


def test_register_and_get():
    """register 后可按名字 get。"""
    reg = _registry(multiply)
    assert reg.get("multiply") is multiply
    assert reg.get("nope") is None


def test_unregister():
    """unregister 后 get 返回 None。"""
    reg = _registry(multiply)
    reg.unregister("multiply")
    assert reg.get("multiply") is None


def test_register_overwrites():
    """同名注册后者覆盖前者。"""

    @tool
    def multiply(a: int, b: int) -> int:
        """Other multiply."""
        return a + b

    reg = _registry()
    reg.register(multiply)
    reg.register(multiply)  # 同名再注册
    assert reg.get("multiply") is multiply
    assert len(reg.get_schemas()) == 1


def test_get_schemas_shape():
    """get_schemas 输出 OpenAI tools 形状。"""
    reg = _registry(multiply)
    schemas = reg.get_schemas()
    assert schemas == [
        {
            "type": "function",
            "function": {
                "name": "multiply",
                "description": "Multiply two integers.",
                "parameters": multiply.to_openai_schema()["function"]["parameters"],
            },
        }
    ]


def test_execute_success():
    """正常执行返回 ToolResult(ok=True)。"""
    result = _registry(multiply).execute(make_tool_call("multiply", '{"a": 6, "b": 7}'))
    assert result.ok is True
    assert result.data == 42


def test_execute_coerces_string_to_int():
    """类型强转："37" → 37。"""
    result = _registry(multiply).execute(make_tool_call("multiply", '{"a": "6", "b": 7}'))
    assert result.ok is True
    assert result.data == 42


def test_execute_validation_error():
    """缺必填 → ToolResult(ok=False)，含逐条消息。"""
    result = _registry(multiply).execute(make_tool_call("multiply", '{"a": 6}'))
    assert result.ok is False
    assert result.error is not None
    assert result.error.startswith('Validation failed for tool "multiply":')
    assert "b: Field required" in result.error


def test_execute_unknown_tool():
    """未知工具名 → ToolResult(ok=False)。"""
    result = _registry(multiply).execute(make_tool_call("nope", "{}"))
    assert result.ok is False
    assert result.error == "Unknown tool 'nope'. Available: multiply"


def test_execute_invalid_json():
    """坏 JSON → ToolResult(ok=False)。"""
    result = _registry(multiply).execute(make_tool_call("multiply", "{not json"))
    assert result.ok is False
    assert result.error.startswith("Invalid JSON arguments for tool 'multiply':")


def test_execute_tool_exception():
    """工具异常 → ToolResult(ok=False)，永不抛。"""

    @tool
    def boom(x: int) -> int:
        """Always fails."""
        raise RuntimeError("kaboom")

    result = _registry(boom).execute(make_tool_call("boom", '{"x": 1}'))
    assert result.ok is False
    assert result.error == "Error executing tool 'boom': kaboom"


def test_execute_nondict_json_never_raises():
    """arguments 解析出非 dict 也不抛。"""
    result = _registry(multiply).execute(make_tool_call("multiply", "[1, 2]"))
    assert result.ok is False
    assert result.error.startswith('Validation failed for tool "multiply":')


def test_execute_applies_defaults():
    """默认值参数不传 → 函数收到默认值。"""
    result = _registry(greet).execute(make_tool_call("greet", '{"name": "pi"}'))
    assert result.ok is True
    assert result.data == "Hello, pi!"
