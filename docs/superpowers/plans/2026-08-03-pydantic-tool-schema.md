# 工具层 pydantic 化实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 pydantic 取代 `my_agent_core/tools.py` 里手写的 `TYPE_MAP`：schema 生成与参数校验收敛到同一份动态 pydantic 模型，工具参数获得 pydantic 全集表达力（含默认值/Optional）。

**Architecture:** `@tool` 装饰器用 `pydantic.create_model` 从函数签名动态建一个参数模型（`extra="forbid"`），schema 由 `model_json_schema()` 生成（递归删 `title` 键），`call_tool` 执行前用同一模型 `model_validate` 校验 + 强转。对外 API（`@tool` 用法、`Tool`、`schemas_for`、`call_tool` 签名）零变化。

**Tech Stack:** Python ≥3.11，`pydantic>=2.0`（新增直接依赖），pytest（离线测试）。

**规格依据:** `docs/superpowers/specs/2026-08-03-pydantic-tool-schema-design.md`

## Global Constraints

- Python 环境与包管理一律用 `uv` + 项目级 `.venv`，绝不用全局 pip。
- 测试与验证命令用 `uv run python -m pytest -q`（不要用 `uv run pytest`，环境里会出 spurious warning）。
- 文档、注释、docstring 写**中文**；标识符用英文（贴合现有风格，不要把注释翻成英文）。
- `call_tool` 永不抛异常：一切运行期错误转描述性字符串；装饰器错误在 import 阶段 fail-loud 抛 `TypeError`。
- 外科手术式修改：只改本计划列出的内容，不顺手重构其他代码。
- 除 Task 3 的文档改动外，不改动 `agent.py`、`main.py` 的任何代码。
- 提交信息用中文，风格对齐现有 `feat:` / `docs:` 前缀。

---

### Task 1: 依赖 + schema 生成切换到 pydantic（装饰期）

**Files:**
- Modify: `pyproject.toml:6-9`（dependencies）
- Modify: `my_agent_core/tools.py`（删 `TYPE_MAP`，重写 `Tool` dataclass 与 `tool()` 装饰器，新增 `_clean_schema`；`schemas_for` 与 `call_tool` 本任务**保持原样**）
- Create: `tests/test_tools.py`

**Interfaces:**
- Produces: `Tool.model: type[BaseModel]`（Task 2 的 `call_tool` 用它做运行期校验）；`_clean_schema(schema) -> dict`；装饰后的 `Tool.parameters` 为无 `title` 键的 JSON Schema dict。

**背景提示：** 本任务结束后、Task 2 完成前存在一个中间态——schema 已支持默认值，但 `call_tool` 还是裸调 `func(**args)`（不回填默认值、不强转）。`main.py` 的三个 demo 工具没有默认值参数，不受影响；这是预期内的过渡状态。

- [ ] **Step 1: 添加 pydantic 依赖**

编辑 `pyproject.toml`，`dependencies` 数组加一行：

```toml
[project]
name = "my-pi-agent"
version = "0.1.0"
description = "my_agent_core: minimal agent framework modeled on pi / pig-mono (learning project)"
requires-python = ">=3.11"
dependencies = [
    "openai>=2.50.0",
    "pydantic>=2.0",
    "python-dotenv>=1.0,<2.0",
]
```

- [ ] **Step 2: 安装并验证依赖**

Run: `uv sync`
然后 Run: `uv run python -c "import pydantic; print(pydantic.VERSION)"`
Expected: 打印 `2.x.x` 版本号，无报错。

- [ ] **Step 3: 写失败测试（装饰期，规格 §7 #1–#8 + #15）**

创建 `tests/test_tools.py`（tests/ 目录首个 `.py` 文件）。先只写装饰期部分——运行期测试在 Task 2 追加：

```python
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
```

- [ ] **Step 4: 运行测试，确认按预期失败**

Run: `uv run python -m pytest tests/test_tools.py -q`
Expected: FAIL。具体地：`test_schema_zero_params`（旧版多一个 `"required": []`）、`test_schema_default_values` / `test_schema_optional` / `test_schema_complex_types`（旧版装饰时抛 TypeError，或报 Unsupported annotation）、`test_reject_missing_annotation` / `test_reject_varargs`（错误消息与旧版不符，且旧版会接受 `*args: int`）应失败；`test_schema_basic_types`、`test_schema_has_no_titles`、`test_name_and_description`、`test_schemas_for_shape` 在旧实现上本来就能通过，属预期。

- [ ] **Step 5: 重写 tools.py 的装饰期部分**

`my_agent_core/tools.py` 做三处替换（`schemas_for` 与 `call_tool` 一字不动）：

① 导入区（第 7~20 行：`from __future__ import annotations` 到 `TYPE_MAP` 结尾）替换为：

```python
from __future__ import annotations

import inspect
import json
from dataclasses import dataclass
from typing import Any, Callable, get_type_hints

from pydantic import BaseModel, ConfigDict, create_model
```

（`TYPE_MAP` 整张表删除。）

② `Tool` dataclass 替换为：

```python
@dataclass
class Tool:
    """一个可被模型调用的工具：函数本体 + 发给模型的 JSON schema + 参数模型。"""

    name: str
    description: str
    parameters: dict[str, Any]
    func: Callable[..., Any]
    model: type[BaseModel]   # pydantic 参数模型：schema 生成与运行期校验共用
```

③ `tool()` 装饰器整体替换为（并在其后新增 `_clean_schema`）：

```python
def tool(func: Callable[..., Any]) -> Tool:
    """@tool 装饰器：从函数的名字、docstring、签名推导 Tool。

    schema 生成由 pydantic 驱动：参数类型支持 pydantic 全集
    （list/dict/Optional/嵌套等），允许默认值；无标注参数与
    *args/**kwargs 在装饰时抛 TypeError（明确失败）。
    """
    hints = get_type_hints(func)
    fields: dict[str, Any] = {}
    for param_name, param in inspect.signature(func).parameters.items():
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VARKW):
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
        parameters = _clean_schema(model.model_json_schema())
    except Exception as exc:   # 无法建模的类型 → 装饰时明确失败
        raise TypeError(
            f"tool '{func.__name__}': cannot build parameter schema: {exc}"
        ) from exc

    return Tool(
        name=func.__name__,
        description=inspect.getdoc(func) or "",
        parameters=parameters,
        func=func,
        model=model,
    )


def _clean_schema(schema: Any) -> Any:
    """递归删除 pydantic 生成的各级 title 键（对模型是纯噪音）。"""
    if isinstance(schema, dict):
        return {k: _clean_schema(v) for k, v in schema.items() if k != "title"}
    if isinstance(schema, list):
        return [_clean_schema(item) for item in schema]
    return schema
```

注意：错误消息里的中文（「不支持」「没有类型标注」）是测试 `match` 的锚点，保留原样。

- [ ] **Step 6: 运行测试，确认全部通过**

Run: `uv run python -m pytest tests/test_tools.py -q`
Expected: PASS（10 个测试全绿）。

- [ ] **Step 7: 提交**

```bash
git add pyproject.toml uv.lock my_agent_core/tools.py tests/test_tools.py
git commit -m "feat: 工具 schema 生成切换到 pydantic（移除手写 TYPE_MAP）"
```

---

### Task 2: call_tool 运行期校验与强转

**Files:**
- Modify: `my_agent_core/tools.py`（`call_tool` + 新增 `_format_validation_error`）
- Modify: `tests/test_tools.py`（追加运行期测试）

**Interfaces:**
- Consumes: `Tool.model: type[BaseModel]`（Task 1 产出）
- Produces: `call_tool` 返回的错误字符串新格式 `Validation failed for tool "X":` + 逐条 `  - field: msg`；`_format_validation_error(name: str, exc: ValidationError) -> str`（v1 阶段 2.2 的 loop.py 将复用它）

- [ ] **Step 1: 写失败测试（运行期，规格 §7 #9–#14）**

在 `tests/test_tools.py` 末尾追加：

```python
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


def test_call_tool_bool_not_accepted_as_int():
    """#12 bool/int 严格区分（钉死 pydantic v2 行为）。"""
    result = call_tool(make_tool_call("multiply", '{"a": true, "b": 7}'), _registry(multiply))
    assert result.startswith('Validation failed for tool "multiply":')


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
```

- [ ] **Step 2: 运行测试，确认按预期失败**

Run: `uv run python -m pytest tests/test_tools.py -q`
Expected: FAIL。具体地：`test_call_tool_coerces_string_to_int`（`"6" * 7` 得 `"6666666"`）、`test_call_tool_missing_required` / `test_call_tool_wrong_type` / `test_call_tool_extra_argument`（旧版落到 `Error executing tool ...` 的 TypeError 消息）、`test_call_tool_bool_not_accepted_as_int`（`True * 7 == 7`）应失败；`test_call_tool_success`、`test_call_tool_applies_defaults`、三个回归测试在旧实现上通过，属预期。

- [ ] **Step 3: 实现校验版 call_tool**

`my_agent_core/tools.py` 导入区把 `from pydantic import BaseModel, ConfigDict, create_model` 改为：

```python
from pydantic import BaseModel, ConfigDict, ValidationError, create_model
```

`call_tool` 整体替换为：

```python
def call_tool(tool_call: Any, tools_by_name: dict[str, Tool]) -> str:
    """执行单个 tool_call。任何错误都转成描述性字符串，永不抛出。"""
    name = tool_call.function.name
    target = tools_by_name.get(name)
    if target is None:
        available = ", ".join(sorted(tools_by_name))
        return f"Unknown tool '{name}'. Available: {available}"

    try:
        args = json.loads(tool_call.function.arguments)
    except (json.JSONDecodeError, TypeError) as exc:
        return f"Invalid JSON arguments for tool '{name}': {exc}"

    try:
        validated = target.model.model_validate(args)   # 校验 + 类型强转
    except ValidationError as exc:
        return _format_validation_error(name, exc)

    try:
        result = target.func(**validated.model_dump())
    except Exception as exc:  # 工具错误 → 消息，喂回模型
        return f"Error executing tool '{name}': {exc}"

    return str(result)


def _format_validation_error(name: str, exc: ValidationError) -> str:
    """把 pydantic 校验错误转成逐条消息回给模型（pi 风格，消息用 pydantic 原文）。"""
    lines = [f'Validation failed for tool "{name}":']
    for err in exc.errors():
        field = err["loc"][0] if err["loc"] else "?"
        lines.append(f"  - {field}: {err['msg']}")
    return "\n".join(lines)
```

- [ ] **Step 4: 运行全部测试，确认通过**

Run: `uv run python -m pytest tests/test_tools.py -q`
Expected: PASS（21 个测试全绿）。

- [ ] **Step 5: 真实运行 demo（规格 §7 #16）**

Run: `uv run python -m my_agent_core.main`
Expected: 三个问题答案符合预期——`37 times 19` 得 703；当前时间；Tokyo 与 Paris 的天气。
若 `.env` 缺少可用 API key 导致无法真实运行，在交付说明里明确标注此项未验证，不得默默跳过。

- [ ] **Step 6: 提交**

```bash
git add my_agent_core/tools.py tests/test_tools.py
git commit -m "feat: 工具参数改为 pydantic 校验与强转（call_tool）"
```

---

### Task 3: 同步文档修订

**Files:**
- Modify: `CLAUDE.md`（仓库根，**当前为 untracked 状态**，本任务一并提交入库）
- Modify: `my_agent_core/README.md`
- Modify: `docs/superpowers/specs/2026-08-01-my-agent-framework-design.md`

**Interfaces:**
- Consumes: Task 1/2 已落地的行为事实（pydantic 全集类型、默认值、校验强转、新错误格式）
- Produces: 文档与实现一致；框架设计文档中手写校验相关内容标注被新规格取代

- [ ] **Step 1: 修订 CLAUDE.md（两处）**

Edit 1 —— 依赖表述：

- old_string: `The framework depends only on the `openai` SDK + stdlib — **no agent-framework dependency, by design.**`
- new_string: `The framework depends only on the `openai` SDK + `pydantic` + stdlib — **no agent-framework dependency, by design**（pydantic 是通用库；禁的是 langchain/langgraph 这类 agent 框架）。`

Edit 2 —— tools.py 描述：

- old_string: `**`my_agent_core/tools.py`** — up-translation layer. `@tool` builds a `Tool` (function + JSON schema) from the function name, docstring, and type hints (`int`/`float`/`str`/`bool` only; default-value params are rejected at decoration time).`
- new_string: `**`my_agent_core/tools.py`** — up-translation layer. `@tool` builds a `Tool` (function + JSON schema + pydantic 参数模型) from the function name, docstring, and type hints (pydantic 全集类型，允许默认值；无标注参数与 `*args`/`**kwargs` 在装饰时拒绝).`

- [ ] **Step 2: 修订 my_agent_core/README.md（五处）**

Edit 1 —— 开头依赖：

- old_string: `从零实现的最简 ReAct agent。只依赖 `openai` SDK 与标准库，不依赖任何 agent 框架。`
- new_string: `从零实现的最简 ReAct agent。只依赖 `openai` SDK、`pydantic` 与标准库，不依赖任何 agent 框架。`

Edit 2 —— 「全部手写」措辞：

- old_string: `本项目负责执行工具、把观察结果写回消息历史，循环持续——直到模型认为可以直接
回答为止。所有协议细节（工具 schema 生成、`tool_calls` 解析、错误容错）全部
手写，透明可审查。`
- new_string: `本项目负责执行工具、把观察结果写回消息历史，循环持续——直到模型认为可以直接
回答为止。工具 schema 生成与参数校验委托 `pydantic`，其余协议细节
（`tool_calls` 解析、调度、错误容错）全部手写，透明可审查。`

Edit 3 —— 特性列表 @tool 一行：

- old_string: `- `@tool` 装饰器：从函数名、docstring、类型标注自动生成发给模型的 JSON schema`
- new_string: `- `@tool` 装饰器：从函数名、docstring、类型标注自动生成发给模型的 JSON schema（pydantic 驱动，支持全集类型与默认值）`

Edit 4 —— 「添加新工具」示例与类型说明：

- old_string:
```
# 然后把它传入 run_agent 的 tools 列表：
run_agent(question, tools=[get_weather], client=client, model=model)
```

支持的参数类型标注：`int`、`float`、`str`、`bool`；暂不支持默认值参数。
```
- new_string:
```
@tool
def search_docs(query: str, tags: list[str], limit: int = 5) -> str:
    """Search docs by query and tags."""   # 复杂类型、默认值都可以
    return f"results for {query} (tags={tags}, limit={limit})"

# 然后把它传入 run_agent 的 tools 列表：
run_agent(question, tools=[get_weather, search_docs], client=client, model=model)
```

参数类型支持 pydantic 全集（`list` / `dict` / `Optional` / 嵌套 `BaseModel` 等），
允许默认值；无标注参数与 `*args` / `**kwargs` 在装饰时拒绝。
```

Edit 5 —— v1 路线阶段 2.2：

- old_string: `- [ ] 2.2 `loop.py`：`validate_arguments` 执行前校验（缺必填 / 类型不符 /
      多余参数逐条报错；bool/int 区分）→ 验证：框架 §7 #6`
- new_string: `- [ ] 2.2 `loop.py`：执行前参数校验（经 `Tool.model` pydantic 校验 + 强转，
      逐条错误消息复用 tools.py 的 `_format_validation_error`）→ 验证：框架 §7 #6`

- [ ] **Step 3: 修订框架设计文档 2026-08-01（六处）**

目标文件：`docs/superpowers/specs/2026-08-01-my-agent-framework-design.md`

Edit 1 —— 六段管道第 3 步（「`execute_one`」管道示意里的第 3 行）：

- old_string: `3. validate_arguments(...)      → 违规非空 → 校验错误字符串（逐条列出违规，pi 风格，见下）`
- new_string: `3. tool.model.model_validate(args) → ValidationError → 校验错误字符串（逐条列出，pi 风格，见下；含类型强转）`

Edit 2 —— `validate_arguments` 代码块整体替换。定位以 `def validate_arguments(name: str, args: dict, schema: dict) -> str | None:` 开头的整个 ```python 围栏块（约 17 行，以 docstring 的 `"""` 结束），替换为：

```python
# —— 已由 2026-08-03-pydantic-tool-schema-design.md 取代 ——
# 校验不再是手写函数，而是 Tool 上的 pydantic 参数模型：
#
#     validated = tool.model.model_validate(args)     # 校验 + 类型强转（"37" → 37）
#     # ValidationError → _format_validation_error(name, exc) → 逐条错误字符串
#
# 原三条规则全部由 pydantic 覆盖：
# - 缺必填   → pydantic required 检查（装饰器生成的模型字段即真实签名）
# - 类型不符 → pydantic 类型检查（v2 默认严格区分 bool/int，无需特殊处理）
# - 多余参数 → 动态模型 extra="forbid"
# 错误消息直接沿用 pydantic 原始 msg，逐条列出（pi 风格）：
#
#     Validation failed for tool "get_weather":
#       - city: Field required
#       - retries: Input should be a valid integer
#       - verbose: Extra inputs are not permitted
```

Edit 3 —— 错误表「模型参数缺必填」行：

- old_string: `| 模型参数缺必填 / 类型不符 / 多余参数 | 步骤 3 | `validate_arguments` 逐条列出违规成错误字符串，工具不执行 |`
- new_string: `| 模型参数缺必填 / 类型不符 / 多余参数 | 步骤 3 | `tool.model.model_validate`（pydantic）逐条列出违规成错误字符串，工具不执行 |`

Edit 4 —— 错误表「装饰器」行：

- old_string: `| 装饰器遇到不支持的标注/默认值 | `@tool` | 装饰时（import 阶段）抛 `TypeError`（不变） |`
- new_string: `| 装饰器遇到无标注参数 / *args/**kwargs / 无法建模的类型 | `@tool` | 装饰时（import 阶段）抛 `TypeError`（默认值合法，见 2026-08-03 规格） |`

Edit 5 —— §7 测试清单 #1：

- old_string: `| 1 | schema 生成 | `@tool` / `schemas_for` 行为（名字/docstring/类型标注 → schema；零参数；不支持标注报错） |`
- new_string: `| 1 | schema 生成 | `@tool` / `schemas_for` 行为（名字/docstring/类型标注 → pydantic schema；零参数；默认值/Optional/复杂类型；无标注与 *args/**kwargs 报错） |`

Edit 6 —— §7 测试清单 #6：

- old_string: `| 6 | 参数校验（新） | 缺必填 / 类型不符（含 bool 与 int 的区分）/ 多余参数 → 错误逐条列出违规，工具未执行（副作用探针）；arguments 非 JSON object → 错误字符串 |`
- new_string: `| 6 | 参数校验（新） | pydantic 校验 + 强转（"37"→37）；缺必填 / 类型不符（含 bool 与 int 的区分）/ 多余参数 → 错误逐条列出违规，工具未执行（副作用探针）；arguments 非 JSON object → 错误字符串 |`

- [ ] **Step 4: 文档自检**

Run: `uv run python -m pytest -q`（确认文档改动没碰坏任何代码）
Expected: PASS（21 passed）。
再人工通读三处 diff：`git diff CLAUDE.md my_agent_core/README.md docs/superpowers/specs/2026-08-01-my-agent-framework-design.md`，确认没有残留「仅四种类型」「暂不支持默认值」「validate_arguments 手写」的旧表述（用 `git grep -n "TYPE_MAP"` 应无源码命中）。

- [ ] **Step 5: 提交**

```bash
git add CLAUDE.md my_agent_core/README.md docs/superpowers/specs/2026-08-01-my-agent-framework-design.md
git commit -m "docs: 同步工具层 pydantic 化（CLAUDE.md/README/框架设计文档）"
```

注意：`CLAUDE.md` 目前是 untracked 文件，`git add` 会把整份项目指令文件首次纳入版本库——这是有意的（它本就该在仓库里）。`.env.example` 的既有本地修改与本任务无关，**不要** add。

---

## 完成标准（对照规格 §7 全清单）

- `uv run python -m pytest -q` → 21 passed
- `uv run python -m my_agent_core.main` → 703 / 当前时间 / 两城市天气（依赖可用 API key）
- `git grep -n "TYPE_MAP"` → 无源码命中
- 三个提交：schema 生成（feat）、运行期校验（feat）、文档同步（docs）
