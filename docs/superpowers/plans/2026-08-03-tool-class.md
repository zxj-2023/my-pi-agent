# 工具层类化重构实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `my_agent_core/tools.py` 从「dataclass + 自由函数」重构为类模式：`Tool` 类（自包含 `to_openai_schema`/`execute`/`__call__`）+ `ToolResult` + 独立 `ToolRegistry`（新增 `registry.py`），`agent.py` 改用 registry，删掉 `schemas_for`/`call_tool` 自由函数。

**Architecture:** 三层职责分离——`Tool` 类（工具本体：动态建模 + 校验执行 + 协议转换）、`ToolResult`（结果对象，永不抛）、`ToolRegistry`（注册表：查表 + 批量 schema + 解析执行）。`agent.py` 只做「调用 registry + 配对写回」。

**Tech Stack:** Python ≥3.11，pydantic ≥2.0（已装），pytest（离线测试）。

**规格依据:** `docs/superpowers/specs/2026-08-03-tool-class-design.md`

## Global Constraints

- 测试与验证命令用 `uv run python -m pytest -q`（不要用 `uv run pytest`，环境里有 spurious warning）。
- 注释、docstring 写中文；标识符用英文。
- `Tool.execute` / `ToolRegistry.execute` 永不抛异常：一切错误转 `ToolResult(ok=False, error=...)`。
- 装饰器 fail-loud：无标注参数、`*args`/`**kwargs`、无法建模的类型在装饰时抛 `TypeError`。
- 宽松 bool/int：模型传 `true` 给 int 参数被强转为 `1`，不拦截（既有决策，勿加守卫）。
- 外科手术式修改：只改本计划列出的文件；`main.py` 不动。
- 提交信息用中文，风格对齐现有 `feat:` / `refactor:` / `docs:` 前缀。
- **设计偏离（计划已裁定）**：`ToolResult` 放 `my_agent_core/tools.py`（而非规格写的 registry.py）——因 `Tool.execute` 返回 `ToolResult`、`ToolRegistry.execute` 又依赖 `Tool`，放 registry.py 会造成循环导入。`registry.py` 从 `tools.py` import `Tool, ToolResult`。

---

### Task 1: tools.py 重写为 Tool 类 + ToolResult + tool() 工厂（保留兼容包装）

**Files:**
- Modify: `my_agent_core/tools.py`（整体重写）
- Modify: `tests/test_tools.py`（迁移 schema 测试 + 新增类测试）

**Interfaces:**
- Produces: `Tool(func, *, name=None, description=None, params_model=None)`；`Tool.name/description/params_model`；`Tool.to_openai_schema() -> dict`；`Tool.execute(args: dict) -> ToolResult`；`Tool.__call__(*args, **kwargs)`；`ToolResult(ok, data=None, error=None).serialize() -> str`；`tool(func=None, *, name=None, description=None, params_model=None)` 工厂装饰器；`schemas_for(tools)` / `call_tool(tool_call, tools_by_name)`（**兼容包装，Task 2 删除**）。

**背景提示：** 本任务是「先在旧结构旁边造出新类，再用兼容包装顶住旧调用方」，所以 Task 1 结束时 agent.py 与 20 个旧测试**原样可用**（`schemas_for`/`call_tool` 行为不变）。Task 2 才删包装、换 agent.py。

- [ ] **Step 1: 迁移 8 个 schema 测试 + 新增类测试（写失败测试）**

`tests/test_tools.py` 替换文件头 docstring 与 `from my_agent_core.tools import ...` 行，并做如下修改：

① 导入行改为（`call_tool`/`schemas_for` 仍要，Task 1 兼容包装还在）：

```python
from my_agent_core.tools import Tool, ToolResult, call_tool, schemas_for, tool
```

② 8 个 schema 测试（`test_schema_basic_types` 到 `test_schema_has_no_titles`）里所有 `f.parameters` 改为 `f.to_openai_schema()["function"]["parameters"]`。例如 `test_schema_basic_types`：

```python
def test_schema_basic_types():
    """#1 基本类型 → JSON Schema 类型名。"""

    @tool
    def f(a: int, b: str, c: float, d: bool) -> None:
        """doc"""

    assert f.to_openai_schema()["function"]["parameters"] == {
        "type": "object",
        "properties": {
            "a": {"type": "integer"},
            "b": {"type": "string"},
            "c": {"type": "number"},
            "d": {"type": "boolean"},
        },
        "required": ["a", "b", "c", "d"],
    }
```

其余 7 个 schema 测试同样替换（`test_schema_zero_params`、`test_schema_default_values`、`test_schema_optional`、`test_schema_complex_types`、`test_schema_has_no_titles` 内的 `props = f.parameters["properties"]` 等全部改为 `f.to_openai_schema()["function"]["parameters"]`）。

③ `test_schemas_for_shape` 改为（旧 Tool 无 `.parameters` 属性，必须迁移）：

```python
def test_schemas_for_shape():
    """#15 schemas_for 输出形状回归（兼容包装）。"""

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
                "parameters": multiply.to_openai_schema()["function"]["parameters"],
            },
        }
    ]
```

④ 在文件末尾（`test_call_tool_nondict_json_never_raises` 之后）追加类测试：

```python
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
        return ""

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
    assert a.to_openai_schema() == b.to_openai_schema()


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
    assert "a: Input should be a valid integer" in result.error


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
```

- [ ] **Step 2: 运行测试，确认按预期失败**

Run: `uv run python -m pytest tests/test_tools.py -q`
Expected: FAIL。具体地：8 个迁移 schema 测试（旧 dataclass `Tool` 无 `to_openai_schema` 方法）、`test_schemas_for_shape`、`test_tool_name_override` 等 9 个新测试失败；`test_reject_missing_annotation` / `test_reject_varargs` / `test_name_and_description` 与 10 个 `call_tool` 回归测试在旧实现上通过（旧 `tool()` 仍返回 dataclass）。均属预期。

- [ ] **Step 3: 重写 tools.py**

`my_agent_core/tools.py` 整体替换为：

```python
"""工具声明与分发 —— 上行翻译层（类模式）。

- Tool 类：从函数名、docstring、类型标注自动生成发给模型的 JSON schema
  （pydantic 驱动），并提供校验执行与直接调用
- tool() 装饰器：支持 @tool 与 @tool(name=..., description=..., params_model=...)
"""
from __future__ import annotations

import inspect
import json
from dataclasses import dataclass
from typing import Any, Callable, get_type_hints

from pydantic import BaseModel, ConfigDict, ValidationError, create_model


@dataclass
class ToolResult:
    """工具执行结果：成功/失败 + 数据或错误消息。"""

    ok: bool
    data: Any = None
    error: str | None = None

    def serialize(self) -> str:
        """转成写入 messages 的字符串。失败时返回错误文本。"""
        if self.ok:
            return str(self.data)
        return self.error or "Unknown error"


class Tool:
    """一个可被模型调用的工具：函数本体 + 参数模型 + 协议转换。"""

    def __init__(
        self,
        func: Callable[..., Any],
        *,
        name: str | None = None,
        description: str | None = None,
        params_model: type[BaseModel] | None = None,
    ):
        self.func = func
        self.name = name or func.__name__
        self.description = description or (inspect.getdoc(func) or "")
        self.params_model = params_model or self._create_params_model(func)

    def _create_params_model(self, func: Callable[..., Any]) -> type[BaseModel]:
        """从函数签名动态建模（pydantic create_model）。"""
        hints = get_type_hints(func)
        fields: dict[str, Any] = {}
        for param_name, param in inspect.signature(func).parameters.items():
            if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
                raise TypeError(
                    f"tool '{func.__name__}': parameter '{param_name}' is "
                    "*args/**kwargs, which is not supported（不支持）"
                )
            if param_name not in hints:
                raise TypeError(
                    f"tool '{func.__name__}': parameter '{param_name}' "
                    "has no type annotation（没有类型标注）"
                )
            default = ... if param.default is inspect.Parameter.empty else param.default
            fields[param_name] = (hints[param_name], default)

        try:
            model = create_model(
                f"{func.__name__}_Args",
                __config__=ConfigDict(extra="forbid"),   # 多余参数 → 校验错误
                **fields,
            )
            return model
        except Exception as exc:   # 无法建模的类型 → 装饰时明确失败
            raise TypeError(
                f"tool '{func.__name__}': cannot build parameter schema: {exc}"
            ) from exc

    def to_openai_schema(self) -> dict[str, Any]:
        """生成 OpenAI tools 参数（pydantic schema，已删 title 噪音）。"""
        parameters = _clean_schema(self.params_model.model_json_schema())
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": parameters,
            },
        }

    def execute(self, args: dict[str, Any]) -> ToolResult:
        """校验 + 执行，永不抛（错误全部转 ToolResult）。"""
        try:
            validated = self.params_model.model_validate(args)
        except ValidationError as exc:
            return ToolResult(ok=False, error=_format_validation_error(self.name, exc))
        try:
            result = self.func(**validated.model_dump())
        except Exception as exc:  # 工具错误 → 消息，喂回模型
            return ToolResult(ok=False, error=f"Error executing tool '{self.name}': {exc}")
        return ToolResult(ok=True, data=result)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """直接调用工具函数本体。"""
        return self.func(*args, **kwargs)


def tool(
    func: Callable[..., Any] | None = None,
    *,
    name: str | None = None,
    description: str | None = None,
    params_model: type[BaseModel] | None = None,
):
    """@tool 装饰器：支持 @tool 与 @tool(name=..., description=..., params_model=...)。

    schema 生成由 pydantic 驱动：参数类型支持 pydantic 全集（list/dict/Optional/嵌套等），
    允许默认值；无标注参数与 *args/**kwargs 在装饰时抛 TypeError（明确失败）。
    """

    def decorator(f: Callable[..., Any]) -> Tool:
        return Tool(func=f, name=name, description=description, params_model=params_model)

    if func is None:
        return decorator
    return decorator(func)


def _clean_schema(schema: Any) -> Any:
    """递归清理 pydantic schema：删除各级 title 键与 additionalProperties: false（对模型是纯噪音）。"""
    if isinstance(schema, dict):
        cleaned = {k: _clean_schema(v) for k, v in schema.items() if k != "title"}
        if cleaned.get("additionalProperties") is False:
            cleaned.pop("additionalProperties")
        return cleaned
    if isinstance(schema, list):
        return [_clean_schema(item) for item in schema]
    return schema


def _format_validation_error(name: str, exc: ValidationError) -> str:
    """把 pydantic 校验错误转成逐条消息回给模型（pi 风格，消息用 pydantic 原文）。"""
    lines = [f'Validation failed for tool "{name}":']
    for err in exc.errors():
        field = err["loc"][0] if err["loc"] else "?"
        lines.append(f"  - {field}: {err['msg']}")
    return "\n".join(lines)


# ---- 兼容包装（Task 2 移除）：agent.py 与旧测试暂用，保持行为不变 ----


def schemas_for(tools: list[Tool]) -> list[dict[str, Any]]:
    """（临时）生成 OpenAI API 的 tools 参数。"""
    return [t.to_openai_schema() for t in tools]


def call_tool(tool_call: Any, tools_by_name: dict[str, Tool]) -> str:
    """（临时）执行单个 tool_call。任何错误都转成描述性字符串，永不抛出。"""
    name = tool_call.function.name
    target = tools_by_name.get(name)
    if target is None:
        available = ", ".join(sorted(tools_by_name))
        return f"Unknown tool '{name}'. Available: {available}"

    try:
        args = json.loads(tool_call.function.arguments)
    except (json.JSONDecodeError, TypeError) as exc:
        return f"Invalid JSON arguments for tool '{name}': {exc}"

    return target.execute(args).serialize()
```

注意：`_clean_schema` 的逻辑从 `tool()` 局部搬进了 `Tool.to_openai_schema()`；`_create_params_model` 承接原 `tool()` 的 fail-loud 三段拒绝；`_format_validation_error` 从 call_tool 的局部搬成模块级（被 `Tool.execute` 用）。

- [ ] **Step 4: 运行测试，确认全部通过**

Run: `uv run python -m pytest tests/test_tools.py -q`
Expected: PASS（29 个测试全绿：8 迁移 schema + 2 reject + 1 name + 1 schemas_for + 9 新类测试 + 10 call_tool 回归）。

- [ ] **Step 5: 提交**

```bash
git add my_agent_core/tools.py tests/test_tools.py
git commit -m "refactor: Tool 改为类（to_openai_schema/execute/__call__）+ ToolResult + tool() 工厂"
```

---

### Task 2: registry.py（ToolRegistry）+ agent.py 改造 + 删兼容包装

**Files:**
- Create: `my_agent_core/registry.py`
- Create: `tests/test_registry.py`
- Modify: `my_agent_core/agent.py`（改用 registry）
- Modify: `my_agent_core/tools.py`（删 `schemas_for`/`call_tool`，去掉 `json` import）
- Modify: `tests/test_tools.py`（删 `schemas_for`/`call_tool` 相关测试，迁移到 test_registry.py）

**Interfaces:**
- Consumes: `Tool`（含 `to_openai_schema`/`execute`）、`ToolResult`（Task 1 产出）
- Produces: `ToolRegistry()` 含 `register(tool)` / `unregister(name)` / `get(name) -> Tool | None` / `get_schemas() -> list[dict]` / `execute(tool_call) -> ToolResult`；`agent.py` 不再 import `schemas_for`/`call_tool`。

- [ ] **Step 1: 写失败测试（tests/test_registry.py）**

创建 `tests/test_registry.py`：

```python
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
```

- [ ] **Step 2: 运行测试，确认按预期失败**

Run: `uv run python -m pytest tests/test_registry.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'my_agent_core.registry'`）。

- [ ] **Step 3: 创建 registry.py**

`my_agent_core/registry.py`：

```python
"""工具注册表 —— 持有工具集合，按名字查表与执行。"""
from __future__ import annotations

import json
from typing import Any

from my_agent_core.tools import Tool, ToolResult


class ToolRegistry:
    """工具注册表：持有工具集合，按名字查表与执行。"""

    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def get_schemas(self) -> list[dict[str, Any]]:
        """生成全部工具的 OpenAI tools 参数。"""
        return [t.to_openai_schema() for t in self._tools.values()]

    def execute(self, tool_call: Any) -> ToolResult:
        """执行单个 tool_call（收完整协议对象）。任何错误都转成 ToolResult，永不抛。"""
        name = tool_call.function.name
        try:
            args = json.loads(tool_call.function.arguments)
        except (json.JSONDecodeError, TypeError) as exc:
            return ToolResult(ok=False, error=f"Invalid JSON arguments for tool '{name}': {exc}")
        target = self._tools.get(name)
        if target is None:
            available = ", ".join(sorted(self._tools))
            return ToolResult(ok=False, error=f"Unknown tool '{name}'. Available: {available}")
        return target.execute(args)
```

- [ ] **Step 4: 运行 registry 测试，确认通过**

Run: `uv run python -m pytest tests/test_registry.py -q`
Expected: PASS（11 个测试全绿）。

- [ ] **Step 5: 改造 agent.py 改用 registry**

`my_agent_core/agent.py` 两处修改：

① 导入行（第 13 行）改为：

```python
from my_agent_core.registry import ToolRegistry
```

② `run_agent` 主体（第 31-34 行与第 73-79 行）改为：

```python
    # tools 注册表：execute 按 tool_call.function.name 在这里找到目标工具
    registry = ToolRegistry()
    for t in tools:
        registry.register(t)
    # schemas = 请求的 tools 参数：全部工具的 JSON schema
    schemas = registry.get_schemas()
```

```python
        for tc in msg.tool_calls:
            print(
                f"[round {iteration}] 调用工具 "
                f"{tc.function.name}({tc.function.arguments})"
            )
            observation = registry.execute(tc).serialize()  # 错误会被转成消息文本，不会抛异常
            print(f"[round {iteration}] 观察: {observation}")
```

- [ ] **Step 6: 删兼容包装 + 迁移/删除旧测试**

① `my_agent_core/tools.py`：删除文件末尾的「兼容包装」段（`schemas_for`、`call_tool` 两个函数与注释），并删除 import 区的 `import json`（不再使用）。

② `tests/test_tools.py`：删除 `test_schemas_for_shape` 与全部 10 个 `test_call_tool_*` 测试、模块级 `multiply`/`greet` 工具与 `_registry` 帮助函数（已迁移到 test_registry.py）；导入行改为 `from my_agent_core.tools import Tool, ToolResult, tool`（去掉 `call_tool`/`schemas_for`）。

- [ ] **Step 7: 运行全量测试，确认通过**

Run: `uv run python -m pytest -q`
Expected: PASS（约 30 个测试全绿：test_tools.py 18 + test_registry.py 11，以实际为准）。

- [ ] **Step 8: 真实运行 demo（规格 §7 集成）**

Run: `uv run python -m my_agent_core.main`
Expected: 三个问题答案符合预期——703 / 当前时间 / 两城市天气。
若 `.env` 无可用 API key，在交付说明里明确标注未验证及原因，不得默默跳过。

- [ ] **Step 9: 提交**

```bash
git add my_agent_core/registry.py my_agent_core/agent.py my_agent_core/tools.py tests/test_registry.py tests/test_tools.py
git commit -m "feat: 独立 ToolRegistry + agent 改用 registry（移除 schemas_for/call_tool）"
```

---

### Task 3: 同步文档修订

**Files:**
- Modify: `CLAUDE.md`
- Modify: `my_agent_core/README.md`
- Modify: `docs/superpowers/specs/2026-08-01-my-agent-framework-design.md`

**Interfaces:**
- Consumes: Task 1/2 已落地的行为事实（Tool 类、ToolResult、ToolRegistry、agent 用 registry）
- Produces: 文档与实现一致；框架设计文档中 `call_tool` 引用更新为 `registry.execute`

- [ ] **Step 1: 修订 CLAUDE.md（两处）**

Edit 1 —— tools.py 描述：

- old_string: `**`my_agent_core/tools.py`** — up-translation layer. `@tool` builds a `Tool` (function + JSON schema + pydantic 参数模型) from the function name, docstring, and type hints (pydantic 全集类型，允许默认值；无标注参数与 `*args`/`**kwargs` 在装饰时拒绝).`
- new_string: `**`my_agent_core/tools.py`** — up-translation layer. `@tool` (支持 `name`/`description`/`params_model` 覆盖) builds a `Tool` class (function + JSON schema + pydantic 参数模型 + `to_openai_schema`/`execute`/`__call__`) from the function name, docstring, and type hints (pydantic 全集类型，允许默认值；无标注参数与 `*args`/`**kwargs` 在装饰时拒绝). `ToolResult` 承载执行结果（ok/data/error，永不抛）。`

Edit 2 —— 新增 registry.py 描述（在 tools.py 描述后追加一行）：

- old_string: `- **`my_agent_core/agent.py`** — `run_agent(question, *, tools, client, model, system_prompt=None)`, the scheduler.`
- new_string: `- **`my_agent_core/registry.py`** — `ToolRegistry`：工具注册表（register/unregister/get/get_schemas/execute），`execute` 收完整 `tool_call`（内部 JSON 解析 + 查表），全部错误转 `ToolResult`。\n- **`my_agent_core/agent.py`** — `run_agent(question, *, tools, client, model, system_prompt=None)`, the scheduler.`

- [ ] **Step 2: 修订 my_agent_core/README.md（三处）**

Edit 1 —— 项目结构（line 50-57 区域）：

- old_string:
```
my_agent_core/
├── tools.py     # @tool 装饰器 + schema 生成 + 工具调用分发
├── agent.py     # ReAct 循环（run_agent）
└── main.py      # demo 入口：三个示例工具 + 三个示例问题
```
- new_string:
```
my_agent_core/
├── tools.py     # Tool 类 + tool() 装饰器 + ToolResult（schema 生成 + 校验执行）
├── registry.py  # ToolRegistry：工具注册表（查表 + 批量 schema + 执行）
├── agent.py     # ReAct 循环（run_agent）
└── main.py      # demo 入口：三个示例工具 + 三个示例问题
```

Edit 2 —— 特性列表 @tool 一行（line 18 区域）：

- old_string: `- `@tool` 装饰器：从函数名、docstring、类型标注自动生成发给模型的 JSON schema（pydantic 驱动，支持全集类型与默认值）`
- new_string: `- `@tool` 装饰器：从函数名、docstring、类型标注自动生成发给模型的 JSON schema（pydantic 驱动，支持全集类型与默认值）；支持 `name`/`description`/`params_model` 覆盖`

Edit 3 —— 「工作原理」下行调度描述（line 74-76 区域）：

- old_string: `2. **下行调度**：读响应的 `tool_calls`——非空就逐个执行工具，把结果作为
   `role: "tool"` 消息写回 messages（与助手消息的 `tool_call_id` 配对），
   再问一轮；为空则循环结束，返回模型的文本`
- new_string: `2. **下行调度**：读响应的 `tool_calls`——非空就逐个经 `ToolRegistry.execute` 执行
   （收完整 `tool_call`，内部解析 + 查表，永不抛），把 `ToolResult` 序列化后作为
   `role: "tool"` 消息写回 messages（与助手消息的 `tool_call_id` 配对），
   再问一轮；为空则循环结束，返回模型的文本`

另外：README 第 92 行「支持的参数类型标注」与「添加新工具」示例**无需改**（`@tool` 用法兼容）。

- [ ] **Step 3: 修订框架设计文档 2026-08-01（两处）**

目标文件：`docs/superpowers/specs/2026-08-01-my-agent-framework-design.md`

Edit 1 —— §4.4 替换文本中的 `call_tool` 引用（line 268 区域）：

- old_string: `#     validated = tool.model.model_validate(args)     # 校验 + 类型强转（"37" → 37）`
- new_string: `#     validated = tool.params_model.model_validate(args)  # 校验 + 类型强转（"37" → 37）`

Edit 2 —— 六段管道第 2 步描述（line 251-252 区域）：

- old_string: `2. json.loads(arguments)        → 失败   → "Invalid JSON arguments for tool 'X': ..."（沿用）`
- new_string: `2. json.loads(arguments)        → 失败   → "Invalid JSON arguments for tool 'X': ..."（沿用；现由 ToolRegistry.execute 负责）`

（注：`execute_one` 管道在 v1 阶段 2 实现时以 `ToolRegistry.execute` 为基底，本规格只更新引用措辞，不重写管道设计。）

- [ ] **Step 4: 文档自检**

Run: `uv run python -m pytest -q`（确认文档改动没碰坏代码）
Expected: PASS（约 30 passed）。
再人工通读三处 diff：`git diff CLAUDE.md my_agent_core/README.md docs/superpowers/specs/2026-08-01-my-agent-framework-design.md`，确认没有残留「schemas_for」「call_tool」「run_agent 里手写 tools_by_name」的旧表述（`git grep -n "schemas_for\|call_tool" -- "*.py"` 应无命中）。

- [ ] **Step 5: 提交**

```bash
git add CLAUDE.md my_agent_core/README.md docs/superpowers/specs/2026-08-01-my-agent-framework-design.md
git commit -m "docs: 同步工具层类化重构（CLAUDE.md/README/框架设计文档）"
```

注意：`.env.example` 的既有本地修改与本任务无关，**不要** add。

---

## 完成标准（对照规格 §7 全清单）

- `uv run python -m pytest -q` → 全绿（test_tools.py + test_registry.py）
- `uv run python -m my_agent_core.main` → 703 / 当前时间 / 两城市天气（依赖可用 API key）
- `git grep -n "schemas_for\|call_tool" -- "*.py"` → 无源码命中
- 三个提交：Task 1（refactor）、Task 2（feat）、Task 3（docs）