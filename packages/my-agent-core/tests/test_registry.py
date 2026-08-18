"""ToolRegistry 离线测试：注册/查表/批量 schema/执行（含错误路径）。

无需 API key。对应 docs/superpowers/specs/2026-08-03-tool-class-design.md §7。
"""
import asyncio
import pytest

from my_agent_core.registry import ToolRegistry
from my_agent_core.tools import tool


def make_tool_call(name: str, arguments: str) -> dict:
    """构造协议形状的假 tool_call（与 Response.tool_calls 元素一致）。"""
    return {
        "id": "fake-id",
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


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


@pytest.mark.anyio
async def test_execute_success():
    """正常执行返回 ToolResult(ok=True)。"""
    result = await _registry(multiply).execute(make_tool_call("multiply", '{"a": 6, "b": 7}'))
    assert result.ok is True
    assert result.data == 42


@pytest.mark.anyio
async def test_execute_coerces_string_to_int():
    """类型强转："37" → 37。"""
    result = await _registry(multiply).execute(make_tool_call("multiply", '{"a": "6", "b": 7}'))
    assert result.ok is True
    assert result.data == 42


@pytest.mark.anyio
async def test_execute_validation_error():
    """缺必填 → ToolResult(ok=False)，含 pydantic 错误消息。"""
    result = await _registry(multiply).execute(make_tool_call("multiply", '{"a": 6}'))
    assert result.ok is False
    assert result.error is not None
    assert "Field required" in result.error


@pytest.mark.anyio
async def test_execute_unknown_tool():
    """未知工具名 → ToolResult(ok=False)。"""
    result = await _registry(multiply).execute(make_tool_call("nope", "{}"))
    assert result.ok is False
    assert result.error == "Unknown tool 'nope'. Available: multiply"


@pytest.mark.anyio
async def test_execute_invalid_json():
    """坏 JSON → ToolResult(ok=False)。"""
    result = await _registry(multiply).execute(make_tool_call("multiply", "{not json"))
    assert result.ok is False
    assert result.error.startswith("Invalid JSON arguments for tool 'multiply':")


@pytest.mark.anyio
async def test_execute_tool_exception():
    """工具异常 → ToolResult(ok=False)，永不抛。"""

    @tool
    def boom(x: int) -> int:
        """Always fails."""
        raise RuntimeError("kaboom")

    result = await _registry(boom).execute(make_tool_call("boom", '{"x": 1}'))
    assert result.ok is False
    assert result.error == "Error executing tool 'boom': kaboom"


@pytest.mark.anyio
async def test_execute_nondict_json_never_raises():
    """arguments 解析出非 dict 也不抛。"""
    result = await _registry(multiply).execute(make_tool_call("multiply", "[1, 2]"))
    assert result.ok is False
    assert result.error is not None


@pytest.mark.anyio
async def test_execute_applies_defaults():
    """默认值参数不传 → 函数收到默认值。"""
    result = await _registry(greet).execute(make_tool_call("greet", '{"name": "pi"}'))
    assert result.ok is True
    assert result.data == "Hello, pi!"


@pytest.mark.anyio
async def test_registry_execute_batch_parallel_and_order_preserving():
    """execute_batch: 只读并发 + 写入串行 + 结果严格保序回填。"""
    registry = ToolRegistry()
    timeline = []

    @tool(is_parallel_safe=True)
    async def slow_read(id: int) -> str:
        timeline.append(f"start_read_{id}")
        await asyncio.sleep(0.05)
        timeline.append(f"end_read_{id}")
        return f"data_{id}"

    @tool(is_parallel_safe=False)
    async def write_op(id: int) -> str:
        timeline.append(f"write_{id}")
        return f"written_{id}"

    registry.register(slow_read)
    registry.register(write_op)

    tool_calls = [
        {"id": "c0", "function": {"name": "slow_read", "arguments": '{"id": 0}'}},
        {"id": "c1", "function": {"name": "write_op", "arguments": '{"id": 1}'}},
        {"id": "c2", "function": {"name": "slow_read", "arguments": '{"id": 2}'}},
    ]

    results = await registry.execute_batch(tool_calls)

    # 1. 结果严格保序对应
    assert len(results) == 3
    assert results[0].data == "data_0"
    assert results[1].data == "written_1"
    assert results[2].data == "data_2"

    # 2. 验证只读工具并发启动 (start_read_0 与 start_read_2 都在前)
    assert timeline[0] == "start_read_0"
    assert timeline[1] == "start_read_2"

