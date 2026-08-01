# my_ReAct：从零实现最简 ReAct Agent 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 不依赖 langchain/langgraph，仅用 `openai` SDK + 标准库，手写一个透明可读的 ReAct agent（工具 schema 生成、model↔tools 循环、错误恢复、循环护栏），并配套离线测试与学习笔记。

**Architecture:** 三个小模块：`tools.py`（`@tool` 装饰器 + schema 生成 + 工具调用分发，对应 langchain 的上行翻译层与 ToolNode）、`agent.py`（纯 while 循环 + 经典退出条件，对应 `factory.py` 的图骨架）、`main.py`（demo 入口）。消息状态就是 OpenAI wire format 的 dict 列表，不引入任何消息类；`client` 依赖注入以便离线测试。

**Tech Stack:** Python ≥3.11、uv、openai SDK、python-dotenv（已有）、pytest（已有）

## Global Constraints

- 依赖规则（用户全局）：一律用 `uv` + 项目级 `.venv`，不用全局 pip。
- `my_ReAct/` 内**禁止** import langchain/langgraph 的任何模块（这是本练习的意义）。
- 环境变量约定与项目一致：`OPENAI_API_KEY` 必需（运行 demo 时）、`OPENAI_MODEL` 默认 `gpt-4.1-mini`、`OPENAI_BASE_URL` 可选。
- 消息状态统一为 OpenAI wire format 的普通 dict 列表；不定义 Message 类。
- 错误分工：工具层错误（未知工具/坏 JSON/工具异常）在 `call_tool` 内转成描述性字符串返回；循环层错误（`max_iterations` 用尽）与配置错误（缺 API key）抛 `RuntimeError`。
- **项目尚未初始化 git**（spec §8，用户未要求初始化）：所有任务**不执行** `git init` / `git commit`；每个任务末尾仅给出建议的提交信息，供用户日后初始化 git 时使用。
- 运行命令统一用 `uv run ...`（Windows 环境，PowerShell/Git Bash 均可）。

## File Structure

| 文件 | 责任 | 任务 |
|---|---|---|
| `my_ReAct/__init__.py` | 空文件，使 `my_ReAct` 成为可导入的包 | Task 1 |
| `my_ReAct/tools.py` | `TYPE_MAP`、`Tool` dataclass、`@tool` 装饰器、`schemas_for()`、`call_tool()` | Task 2、3 |
| `my_ReAct/agent.py` | `DEFAULT_SYSTEM_PROMPT`、`run_agent()` 循环 | Task 4 |
| `my_ReAct/main.py` | demo 工具（multiply/get_current_time/get_weather）、`build_client()`、`main()` | Task 5 |
| `my_ReAct/README.md` | 学习笔记：运行方式、装饰器原理、`@tool` 拆解、与 langchain 源码映射表 | Task 6 |
| `tests/test_my_react.py` | 离线测试（假客户端，无需 API key） | Task 2-5 逐步增长 |
| `pyproject.toml` | 新增 `openai` 依赖（由 `uv add` 修改） | Task 1 |

---

### Task 1: 脚手架与依赖

**Files:**
- Create: `my_ReAct/__init__.py`
- Modify: `pyproject.toml`（由 `uv add openai` 自动修改）

**Interfaces:**
- Consumes: 无
- Produces: 可导入的空包 `my_ReAct`；`openai` 可导入

- [ ] **Step 1: 添加 openai 依赖**

Run: `uv add openai`
Expected: `pyproject.toml` 的 `dependencies` 出现 `openai>=...`，`uv.lock` 更新，无报错。

- [ ] **Step 2: 创建包占位文件**

Create `my_ReAct/__init__.py`（空文件，0 字节即可）。

- [ ] **Step 3: 验证包与依赖可用**

Run: `uv run python -c "import openai, my_ReAct; print('openai', openai.__version__)"`
Expected: 打印 openai 版本号，无异常。

- [ ] **Step 4: 进度记录**

无 git 仓库，跳过提交。建议提交信息：`feat(my-react): scaffold package and add openai dependency`

---

### Task 2: `@tool` 装饰器与 schema 生成

**Files:**
- Create: `my_ReAct/tools.py`（本任务只写到 `tool()` 为止）
- Test: `tests/test_my_react.py`（新建）

**Interfaces:**
- Consumes: 无
- Produces: `my_ReAct.tools.tool`（装饰器，接收 `Callable`，返回 `Tool`）、`my_ReAct.tools.Tool`（dataclass，字段 `name: str`、`description: str`、`parameters: dict`、`func: Callable`）、`my_ReAct.tools.TYPE_MAP`（`{int: "integer", float: "number", str: "string", bool: "boolean"}`）

- [ ] **Step 1: 写失败测试**

Create `tests/test_my_react.py`:

```python
import pytest

from my_ReAct.tools import tool


def test_tool_builds_openai_schema_from_function():
    @tool
    def multiply(a: int, b: int) -> int:
        """Multiply two integers."""
        return a * b

    assert multiply.name == "multiply"
    assert multiply.description == "Multiply two integers."
    assert multiply.parameters == {
        "type": "object",
        "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
        "required": ["a", "b"],
    }
    assert multiply.func(37, 19) == 703


def test_tool_supports_zero_parameters():
    @tool
    def ping() -> str:
        """Ping."""
        return "pong"

    assert ping.parameters == {"type": "object", "properties": {}, "required": []}


def test_tool_missing_docstring_gives_empty_description():
    @tool
    def no_docs(x: str) -> str:
        return x

    assert no_docs.description == ""


def test_tool_rejects_unsupported_annotation():
    with pytest.raises(TypeError, match="supported types"):

        @tool
        def bad(items: list) -> str:
            return ""


def test_tool_rejects_default_values():
    with pytest.raises(TypeError, match="default"):

        @tool
        def with_default(a: int = 1) -> int:
            return a
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_my_react.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'my_ReAct.tools'`（或 ImportError: cannot import name 'tool'）。

- [ ] **Step 3: 实现 tools.py（装饰器部分）**

Create `my_ReAct/tools.py`:

```python
"""工具声明与分发 —— 上行翻译层。

角色对应 langchain 源码：
- @tool 装饰器 ≈ langchain_core/tools/convert.py
- schema 格式 ≈ langchain_core/utils/function_calling.py 的 convert_to_openai_tool
详见 docs/react-source-walkthrough.md 第 12 章。
"""
from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Callable, get_type_hints

# Python 类型标注 → JSON Schema 类型映射表（装饰器的核心机密）
TYPE_MAP: dict[type, str] = {
    int: "integer",
    float: "number",
    str: "string",
    bool: "boolean",
}


@dataclass
class Tool:
    """一个可被模型调用的工具：函数本体 + 发给模型的 JSON schema。"""

    name: str
    description: str
    parameters: dict[str, Any]
    func: Callable[..., Any]


def tool(func: Callable[..., Any]) -> Tool:
    """@tool 装饰器：从函数的名字、docstring、签名推导 Tool。

    - 参数必须带 TYPE_MAP 内的类型标注，否则装饰时抛 TypeError
    - 不支持默认值参数（保持 schema 最简，明确失败）
    - 零参数合法：properties == {}，required == []
    """
    properties: dict[str, Any] = {}
    required: list[str] = []
    # 解析类型标注为真实类型（兼容定义在 from __future__ import annotations 模块里的函数）
    hints = get_type_hints(func)
    for param_name, param in inspect.signature(func).parameters.items():
        if param.default is not inspect.Parameter.empty:
            raise TypeError(
                f"tool '{func.__name__}': parameter '{param_name}' has a default "
                "value, which is not supported (keep the schema minimal)"
            )
        json_type = TYPE_MAP.get(hints.get(param_name))
        if json_type is None:
            supported = ", ".join(t.__name__ for t in TYPE_MAP)
            raise TypeError(
                f"tool '{func.__name__}': parameter '{param_name}' has annotation "
                f"{hints.get(param_name)!r}; supported types: {supported}"
            )
        properties[param_name] = {"type": json_type}
        required.append(param_name)

    return Tool(
        name=func.__name__,
        description=inspect.getdoc(func) or "",
        parameters={"type": "object", "properties": properties, "required": required},
        func=func,
    )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_my_react.py -v`
Expected: 5 个测试全部 PASS。

- [ ] **Step 5: 进度记录**

无 git 仓库，跳过提交。建议提交信息：`feat(my-react): @tool decorator generating OpenAI function schemas`

---

### Task 3: `schemas_for()` 与 `call_tool()`（分发与容错）

**Files:**
- Modify: `my_ReAct/tools.py`（追加两个函数 + `import json`）
- Test: `tests/test_my_react.py`（追加）

**Interfaces:**
- Consumes: `Tool`、`tool`（Task 2）
- Produces:
  - `schemas_for(tools: list[Tool]) -> list[dict]` —— 返回 `[{"type": "function", "function": {"name", "description", "parameters"}}, ...]`
  - `call_tool(tool_call, tools_by_name: dict[str, Tool]) -> str` —— `tool_call` 为 duck type，需有 `.id`、`.function.name`、`.function.arguments`（JSON 字符串）；永不抛异常，错误转为描述性字符串

- [ ] **Step 1: 写失败测试**

Append 到 `tests/test_my_react.py`（并在文件顶部 import 区加入 `import json`、`from types import SimpleNamespace`、`from my_ReAct.tools import call_tool, schemas_for`）：

```python
def _fake_tool_call(name, args, call_id="call_1"):
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=json.dumps(args)),
    )


@tool
def multiply(a: int, b: int) -> int:
    """Multiply two integers."""
    return a * b


@tool
def div(a: int, b: int) -> float:
    """Divide a by b."""
    return a / b


def test_schemas_for_wraps_tools_in_openai_envelope():
    assert schemas_for([multiply]) == [
        {
            "type": "function",
            "function": {
                "name": "multiply",
                "description": "Multiply two integers.",
                "parameters": {
                    "type": "object",
                    "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
                    "required": ["a", "b"],
                },
            },
        }
    ]


def test_call_tool_executes_and_stringifies_result():
    result = call_tool(
        _fake_tool_call("multiply", {"a": 37, "b": 19}),
        {"multiply": multiply},
    )
    assert result == "703"


def test_call_tool_unknown_tool_lists_available():
    result = call_tool(_fake_tool_call("divide", {"a": 1}), {"multiply": multiply})
    assert result == "Unknown tool 'divide'. Available: multiply"


def test_call_tool_invalid_json_arguments():
    bad_call = SimpleNamespace(
        id="call_1",
        function=SimpleNamespace(name="multiply", arguments="{not json"),
    )
    result = call_tool(bad_call, {"multiply": multiply})
    assert result.startswith("Invalid JSON arguments for tool 'multiply'")


def test_call_tool_error_becomes_message():
    result = call_tool(_fake_tool_call("div", {"a": 1, "b": 0}), {"div": div})
    assert result == "Error executing tool 'div': division by zero"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_my_react.py -v`
Expected: FAIL —— `ImportError: cannot import name 'call_tool' from 'my_ReAct.tools'`。

- [ ] **Step 3: 在 tools.py 追加分发实现**

在 `my_ReAct/tools.py` 顶部 import 区加入 `import json`（`from typing import Any, Callable` 保持），文件末尾追加：

```python
def schemas_for(tools: list[Tool]) -> list[dict[str, Any]]:
    """生成 OpenAI API 的 tools 参数（上行翻译的最后一步）。"""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in tools
    ]


def call_tool(tool_call: Any, tools_by_name: dict[str, Tool]) -> str:
    """执行单个 tool_call。任何错误都转成描述性字符串，永不抛出。

    对应 langgraph ToolNode._run_one 的容错行为（tool_node.py:1014）：
    错误作为观察结果回给模型，让它自我纠正，而不是炸掉循环。
    """
    name = tool_call.function.name
    target = tools_by_name.get(name)
    if target is None:
        available = ", ".join(sorted(tools_by_name))
        return f"Unknown tool '{name}'. Available: {available}"

    try:
        args = json.loads(tool_call.function.arguments)
    except json.JSONDecodeError as exc:
        return f"Invalid JSON arguments for tool '{name}': {exc}"

    try:
        result = target.func(**args)
    except Exception as exc:  # 工具错误 → 消息，喂回模型
        return f"Error executing tool '{name}': {exc}"

    return str(result)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_my_react.py -v`
Expected: 10 个测试全部 PASS。

- [ ] **Step 5: 进度记录**

无 git 仓库，跳过提交。建议提交信息：`feat(my-react): schemas_for and call_tool with error-to-message handling`

---

### Task 4: `run_agent()` 循环

**Files:**
- Create: `my_ReAct/agent.py`
- Test: `tests/test_my_react.py`（追加假客户端与 5 个循环测试）

**Interfaces:**
- Consumes: `Tool`、`schemas_for`、`call_tool`（Task 2-3）；`client` 为 duck type，需支持 `client.chat.completions.create(model=..., messages=..., tools=...)`，返回对象的 `.choices[0].message` 具有 `.content` 与 `.tool_calls`
- Produces: `run_agent(question: str, *, tools: list[Tool], client, model: str, system_prompt: str = DEFAULT_SYSTEM_PROMPT, max_iterations: int = 10, verbose: bool = True) -> str`；`DEFAULT_SYSTEM_PROMPT: str`

- [ ] **Step 1: 写失败测试**

Append 到 `tests/test_my_react.py`（import 区加入 `from my_ReAct.agent import run_agent`、`from my_ReAct.tools import schemas_for`——后者若已导入则跳过）：

```python
class FakeClient:
    """按脚本返回响应的 openai.OpenAI 替身（duck typing）。"""

    def __init__(self, responses):
        self._responses = list(responses)
        self.requests = []
        self.chat = SimpleNamespace(completions=self)

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return self._responses.pop(0)


def _ai(content=None, tool_calls=None):
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _tc(name, args, call_id="call_1"):
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=json.dumps(args)),
    )


TEST_TOOLS = [multiply]  # multiply 定义于 Task 3 的测试代码中


def test_run_agent_returns_direct_answer():
    client = FakeClient([_ai(content="Paris is the capital of France.")])
    answer = run_agent(
        "What is the capital of France?",
        tools=TEST_TOOLS, client=client, model="fake-model", verbose=False,
    )
    assert answer == "Paris is the capital of France."
    assert len(client.requests) == 1
    request = client.requests[0]
    assert request["model"] == "fake-model"
    assert request["tools"] == schemas_for(TEST_TOOLS)
    assert request["messages"][0]["role"] == "system"
    assert request["messages"][1] == {
        "role": "user",
        "content": "What is the capital of France?",
    }


def test_run_agent_executes_tool_and_loops_back():
    client = FakeClient([
        _ai(content=None, tool_calls=[_tc("multiply", {"a": 37, "b": 19}, "call_1")]),
        _ai(content="The answer is 703."),
    ])
    answer = run_agent(
        "Calculate 37 times 19.",
        tools=TEST_TOOLS, client=client, model="fake-model", verbose=False,
    )
    assert answer == "The answer is 703."
    assert len(client.requests) == 2

    second_messages = client.requests[1]["messages"]
    assistant_msg = second_messages[2]
    assert assistant_msg["role"] == "assistant"
    assert assistant_msg["tool_calls"][0]["function"]["name"] == "multiply"
    # "703" 只能来自真实执行 multiply(37, 19) → 证明工具真的跑了
    assert second_messages[3] == {
        "role": "tool",
        "tool_call_id": "call_1",
        "content": "703",
    }


def test_run_agent_recovers_from_unknown_tool():
    client = FakeClient([
        _ai(content=None, tool_calls=[_tc("divide", {"a": 6, "b": 3}, "call_1")]),
        _ai(content="Sorry, I can only multiply."),
    ])
    answer = run_agent(
        "Divide 6 by 3.",
        tools=TEST_TOOLS, client=client, model="fake-model", verbose=False,
    )
    assert answer == "Sorry, I can only multiply."
    tool_msg = client.requests[1]["messages"][3]
    assert "Unknown tool 'divide'" in tool_msg["content"]
    assert "multiply" in tool_msg["content"]


def test_run_agent_feeds_tool_errors_back_to_model():
    client = FakeClient([
        _ai(content=None, tool_calls=[_tc("div", {"a": 1, "b": 0}, "call_1")]),
        _ai(content="Division by zero is undefined."),
    ])
    answer = run_agent(
        "Divide 1 by 0.",
        tools=[div], client=client, model="fake-model", verbose=False,
    )
    assert answer == "Division by zero is undefined."
    tool_msg = client.requests[1]["messages"][3]
    assert tool_msg["content"] == "Error executing tool 'div': division by zero"


def test_run_agent_stops_after_max_iterations():
    client = FakeClient([
        _ai(content=None, tool_calls=[_tc("multiply", {"a": 1, "b": 1})])
        for _ in range(3)
    ])
    with pytest.raises(RuntimeError, match="3 iterations"):
        run_agent(
            "Loop forever.",
            tools=TEST_TOOLS, client=client, model="fake-model",
            max_iterations=3, verbose=False,
        )
    assert len(client.requests) == 3
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_my_react.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'my_ReAct.agent'`。

- [ ] **Step 3: 实现 agent.py**

Create `my_ReAct/agent.py`:

```python
"""ReAct 循环 —— 调度层。

角色对应 langchain 源码：langchain/agents/factory.py 的 model_node +
model_to_tools 条件边。退出条件就是 factory.py:1867 那句经典判断：
tool_calls 为空 → 结束。详见 docs/react-source-walkthrough.md 第 6 章。

与框架的区别：没有图、没有 Message 类——消息状态就是 OpenAI wire format
的普通 dict 列表，协议格式本身就是状态。
"""
from __future__ import annotations

from typing import Any

from my_ReAct.tools import Tool, call_tool, schemas_for

DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful assistant. Use the available tools when they help; "
    "answer directly when they don't."
)


def run_agent(
    question: str,
    *,
    tools: list[Tool],
    client: Any,
    model: str,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    max_iterations: int = 10,
    verbose: bool = True,
) -> str:
    """运行 ReAct 循环，返回模型的最终文本回答。

    client 为依赖注入：生产传 openai.OpenAI(...)，测试传 FakeClient。
    """
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": question},
    ]
    tools_by_name = {t.name: t for t in tools}
    schemas = schemas_for(tools)

    for iteration in range(1, max_iterations + 1):
        response = client.chat.completions.create(
            model=model, messages=messages, tools=schemas
        )
        msg = response.choices[0].message

        assistant_message: dict[str, Any] = {
            "role": "assistant",
            "content": msg.content,
        }
        if msg.tool_calls:
            assistant_message["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ]
        messages.append(assistant_message)

        if not msg.tool_calls:  # ← 经典退出条件
            if verbose:
                print(f"[round {iteration}] 最终回答")
            return msg.content

        for tc in msg.tool_calls:
            if verbose:
                print(
                    f"[round {iteration}] 调用工具 "
                    f"{tc.function.name}({tc.function.arguments})"
                )
            observation = call_tool(tc, tools_by_name)
            if verbose:
                print(f"[round {iteration}] 观察: {observation}")
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": observation,
                }
            )

    raise RuntimeError(
        f"Agent did not finish within {max_iterations} iterations"
    )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_my_react.py -v`
Expected: 15 个测试全部 PASS。

- [ ] **Step 5: 进度记录**

无 git 仓库，跳过提交。建议提交信息：`feat(my-react): run_agent ReAct loop with classic exit condition`

---

### Task 5: demo 入口 `main.py`

**Files:**
- Create: `my_ReAct/main.py`
- Test: `tests/test_my_react.py`（追加 3 个测试）

**Interfaces:**
- Consumes: `run_agent`（Task 4）、`tool`/`schemas_for`（Task 2-3）；环境变量 `OPENAI_API_KEY`、`OPENAI_MODEL`、`OPENAI_BASE_URL`
- Produces: `build_client() -> openai.OpenAI`、`TOOLS: list[Tool]`（`[multiply, get_current_time, get_weather]`）、`QUESTIONS: list[str]`、`main() -> None`

- [ ] **Step 1: 写失败测试**

Append 到 `tests/test_my_react.py`（import 区加入 `from my_ReAct import main as demo`）：

```python
def test_build_client_requires_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        demo.build_client()


def test_build_client_passes_base_url(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.com/v1")
    client = demo.build_client()
    assert "example.com/v1" in str(client.base_url)


def test_demo_tools_have_expected_schemas():
    schemas = schemas_for(demo.TOOLS)
    assert [s["function"]["name"] for s in schemas] == [
        "multiply",
        "get_current_time",
        "get_weather",
    ]
    # get_current_time 是零参数工具
    assert schemas[1]["function"]["parameters"] == {
        "type": "object",
        "properties": {},
        "required": [],
    }
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_my_react.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'my_ReAct.main'`。

- [ ] **Step 3: 实现 main.py**

Create `my_ReAct/main.py`:

```python
"""demo 入口：跑三个固定问题，打印 ReAct 循环过程与最终答案。

运行：uv run python my_ReAct/main.py（需要 .env 里的 OPENAI_API_KEY）
"""
from __future__ import annotations

import os
from datetime import datetime

from dotenv import load_dotenv
from openai import OpenAI

from my_ReAct.agent import run_agent
from my_ReAct.tools import tool

QUESTIONS = [
    "Use the multiply tool to calculate 37 times 19.",
    "What time is it now?",
    "What's the weather like in Tokyo and Paris?",
]


@tool
def multiply(a: int, b: int) -> int:
    """Multiply two integers."""
    return a * b


@tool
def get_current_time() -> str:
    """Get the current date and time."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@tool
def get_weather(city: str) -> str:
    """Get the weather for a city (simulated data)."""
    return f"{city}: sunny, 22°C (simulated)"


TOOLS = [multiply, get_current_time, get_weather]


def build_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is missing. Add it to .env.")
    options: dict[str, str] = {"api_key": api_key}
    if base_url := os.getenv("OPENAI_BASE_URL"):
        options["base_url"] = base_url
    return OpenAI(**options)


def main() -> None:
    load_dotenv()
    client = build_client()
    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    for question in QUESTIONS:
        print(f"\n=== 问题: {question} ===")
        answer = run_agent(question, tools=TOOLS, client=client, model=model)
        print(f"\n最终答案: {answer}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_my_react.py -v`
Expected: 18 个测试全部 PASS。

- [ ] **Step 5: 进度记录**

无 git 仓库，跳过提交。建议提交信息：`feat(my-react): demo entry with three questions and env handling`

---

### Task 6: 学习笔记 `my_ReAct/README.md`

**Files:**
- Create: `my_ReAct/README.md`

**Interfaces:**
- Consumes: 已实现的 `tools.py` / `agent.py` / `main.py`
- Produces: 覆盖 spec §7 四部分的学习笔记

- [ ] **Step 1: 写 README**

Create `my_ReAct/README.md`:

````markdown
# my_ReAct：从零实现的最简 ReAct Agent

只依赖 `openai` SDK，不用 langchain/langgraph。手写 langchain `create_agent`
替你做的全部事情：工具 schema 生成、model↔tools 循环、错误恢复、循环护栏。

## 怎么跑

```powershell
uv sync                       # 安装依赖
Copy-Item .env.example .env   # 填入 OPENAI_API_KEY
uv run python my_ReAct/main.py
uv run pytest -q              # 离线测试（不需要 API key）
```

## 它是怎么工作的

```
用户问题 → [model] ──有 tool_calls──→ 执行工具 → 观察结果 ─┐
              ↑                                             │
              └─────────────── 回模型 ◄──────────────────────┘
              │
              └──无 tool_calls──→ 返回最终答案（经典退出条件）
```

全部逻辑就是 `agent.py` 里一个 while 循环 + 一个 `if not msg.tool_calls` 判断。

## 模型怎么知道该调工具？

**不是本项目的代码决定的，是模型自己决定的。** 模型厂商对模型做过 function
calling 训练：请求里带上工具描述后，模型自己判断要不要调、调哪个、传什么参数，
判断结果以响应的 `tool_calls` 字段回来。本项目只做两件事：

1. **上行翻译**：`@tool` 把 Python 函数翻译成模型看得懂的 JSON schema，
   放进请求的 `tools` 字段
2. **下行调度**：读响应的 `tool_calls`——非空就执行工具、把结果作为
   `role: "tool"` 消息追加回去再问一轮；空了就结束

完整链路见 `docs/react-source-walkthrough.md` 第 12 章。

## Python 装饰器入门

```python
@tool
def multiply(a: int, b: int) -> int:
    """Multiply two integers."""
    return a * b
```

`@tool` 是语法糖，上面这段等价于：

```python
def multiply(a: int, b: int) -> int:
    """Multiply two integers."""
    return a * b

multiply = tool(multiply)   # 名字 multiply 从此指向 tool() 的返回值
```

三个要点：

1. **函数是一等对象**——可以像值一样传给 `tool()`
2. **装饰器就是"接收函数、返回东西"的普通函数**——没有黑魔法
3. 常规装饰器返回包装后的函数；我们的 `@tool` 直接返回一个 `Tool` 对象
   （携带原函数 + schema）——装饰器可以把被装饰的名字替换成任何东西

## `@tool` 逐行拆解（对应 tools.py）

schema 的每个字段来自函数的一个属性：

| JSON 字段 | 来源 | 机制 |
|---|---|---|
| `function.name` | `func.__name__` | Python 函数自带名字属性 |
| `function.description` | `inspect.getdoc(func)` | 即 docstring |
| `parameters.properties` | `inspect.signature(func).parameters` + `typing.get_type_hints(func)` | 遍历参数；类型标注经 `get_type_hints` 解析为真实类型（字符串标注也可用），再按 `TYPE_MAP` 翻译：`int→integer`、`float→number`、`str→string`、`bool→boolean` |
| `parameters.required` | 所有参数（不支持默认值） | 最简约束 |

这正是 langchain `@tool` + `convert_to_openai_tool` 做的事，只是我们只用 40 行
写出来了。

## 与 langchain 源码的对应

| 本项目 | 替代的 langchain/langgraph 源码 | 导览章节 |
|---|---|---|
| `@tool` + schema 生成 | `langchain_core/tools/convert.py` + `utils/function_calling.py` | 第 12.3 节 |
| `call_tool`（错误转消息） | `langgraph/prebuilt/tool_node.py:_run_one` | 第 7 章 |
| `run_agent` 循环与退出条件 | `langchain/agents/factory.py:1867` | 第 6 章 |
| messages dict 列表 | `AIMessage` / `ToolMessage` 消息类 | 第 12.5 节 |
````

- [ ] **Step 2: 校验 README 内的链接与文件名**

Run: `uv run python -c "import my_ReAct.tools, my_ReAct.agent, my_ReAct.main; print('imports ok')"`
Expected: 打印 `imports ok`（确认 README 提到的模块都存在）。人工通读 README，确认与代码一致。

- [ ] **Step 3: 进度记录**

无 git 仓库，跳过提交。建议提交信息：`docs(my-react): learning notes on decorators and langchain mapping`

---

### Task 7: 最终验收

**Files:** 无新增

- [ ] **Step 1: 全量测试**

Run: `uv run pytest -q`
Expected: 25 个测试全部通过（本项目原有 7 个 + my_ReAct 18 个；既有测试必须保持绿色）。

- [ ] **Step 2: 静态确认无框架依赖**

Run: `uv run python -c "import pathlib,re; pat=re.compile(r'^\s*(import|from)\s+(langchain|langgraph)'); bad=[f'{p}:{i+1}' for p in pathlib.Path('my_ReAct').rglob('*.py') for i,line in enumerate(p.read_text(encoding='utf-8').splitlines()) if pat.match(line)]; print('FAIL', bad) if bad else print('no framework imports'); assert not bad"`

（只检查 import/from 行；docstring 中对 langchain 源码的教学性提及是有意保留的，不算违反约束。）

说明：README.md 不是 .py，不在检查范围（笔记里提到 langchain 是正常的）。
Expected: 打印 `no framework imports`，退出码 0。

- [ ] **Step 3: 真实运行验证（需要 .env 中有可用 OPENAI_API_KEY）**

Run: `uv run python my_ReAct/main.py`
Expected（逐条核对）：
- 问题 1：打印出调用 `multiply` 的过程，最终答案包含 `703`
- 问题 2：模型调用 `get_current_time`，答案含当前时间
- 问题 3：模型调用一到两次 `get_weather`，答案包含两个城市的天气

若问题 1 模型直接心算未调工具（小概率，见 spec §8），重跑一次；持续不调则
检查 system prompt 是否生效。

- [ ] **Step 4: 对照验收标准清单**

逐条核对 spec §6.2：

```
实现 tools.py        → 测试 1 通过 ✓
实现 agent.py        → 测试 2-6 通过 ✓
实现 main.py         → uv run pytest -q 全绿 ✓
真实验证             → main.py 三个问题答案符合预期 ✓
学习笔记             → README.md 含装饰器原理 + 链路映射表 ✓
```

- [ ] **Step 5: 进度记录**

无 git 仓库，跳过提交。若用户此时初始化 git，建议首条提交信息涵盖全部任务：
`feat: my_ReAct — minimal ReAct agent from scratch with tests and learning notes`
