# 模型边界层与工具调用结构化重塑实施计划 (Phase 20)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 彻底消灭核心调度微内核（`loop.py`）中的四重 JSON 序列化翻转（4x JSON Ping-Pong）和 OpenAI Wire 私有传输协议泄漏，使 `my-agent-llm` 成为第一公民结构化数据（`ToolCall.args: dict`、`TurnOutcome` 枚举、`Response.to_message()`）的权威生产者，净化 `context.py` 的同步嗅探，实现 100% 清洁架构与全量回归验证。

**Architecture:**

1. **结构化实体第一公民**：在 `my-agent-llm/models.py` 中升级 `ToolCall` 为 `(id: str, name: str, args: dict[str, Any], error: str | None)`。Provider（OpenAI、DeepSeek、Anthropic）在装配工具调用时，在模型边界内直接反序列化 arguments 为 `dict`（Anthropic 原生直接采用 `block.input`，零字符串编解码）。
2. **终止状态中立化**：在 `my-agent-llm/models.py` 中引入对标 `pig-llm` 的 `TurnOutcome`（`COMPLETED`, `TOOL_CALLS`, `LENGTH`, `CONTENT_FILTER`, `ABORTED`, `PROVIDER_ERROR`, `UNKNOWN`）与 `normalize_finish_reason`，抹平各大模型厂商私有方言差异。
3. **消除微内核编解码脏活**：重构 `my-agent-core/loop.py` 中的 `_execute_tools_turn`，直接消费已解析的 `ToolCall`，0 行 `json.loads`/`json.dumps` 字符串代码，直连 `ToolExecutionStart`、`before_tool_call` 与 `ToolRegistry`。
4. **工具注册表原生字典分发**：升级 `ToolRegistry.execute_tool` 与 `execute_batch`，支持直接接收结构化 `name` 与 `args: dict`，消灭第二轮 `json.loads`。
5. **微内核纯异步净化**：剔除 `context.py` 中的 `hasattr(self.llm, "achat")` 鸭子类型分支，强制遵守纯原生异步契约。

**Tech Stack:** Python 3.11+, `asyncio`, `pydantic` v2, `pytest`, `basedpyright`.

**Spec:** `docs/core/18-llm-boundary-and-tool-call-model-redesign.md`

## Global Constraints

- 目标 Python 3.11+，保持 4 空格缩进与严格类型注解。
- 零容忍向后兼容垫片：严禁引入 `X = Y` 别名、`__getattr__` 动态导出或过渡适配层。
- 100% 离线测试契约：测试套件使用 `conftest.py` 中的 `FakeLLM`，无需网络或真实 API 密钥。
- Never-Throw 保证：模型层反序列化参数失败时，不抛崩溃异常，而是标记 `ToolCall.error`，核心微内核据此生成合法的 `ToolResult(ok=False, error=...)`，使模型可自我修正。
- 协议配对不变式：工具调用必须严格保序产出配对的 `ToolExecutionStart`、`ToolExecutionEnd` 以及 `role="tool"` 的 Message。

---

## File Structure

```text
packages/my-agent-llm/
├── src/my_agent_llm/
│   ├── models.py              # 升级: ToolCall(id, name, args: dict, error), TurnOutcome, normalize_finish_reason, Response
│   └── providers/
│       ├── _base.py           # Provider 抽象契约
│       ├── openai.py          # 升级: _ToolCallAccumulator 在 finish() 反序列化 JSON 填充 args
│       ├── deepseek.py        # 升级: 继承自 OpenAI，装配结构化 ToolCall
│       └── anthropic.py       # 升级: 原生采用 block.input (dict)，消灭 json.dumps
└── tests/
    └── test_models_and_providers.py # 覆盖: 结构化 ToolCall、TurnOutcome 映射与流式组装

packages/my-agent-core/
├── src/my_agent_core/
│   ├── loop.py                # 重构: _execute_tools_turn 纯字典派发，消灭 4 次 json.loads/dumps
│   ├── registry.py            # 升级: execute_tool/execute_batch 支持结构化 (name, args: dict)
│   ├── context.py             # 净化: 剔除 hasattr(llm, "achat")，强制纯异步调用
│   └── tool_history.py        # 适配: _get_tool_calls 支持结构化 ToolCall 字典
└── tests/
    ├── conftest.py            # 升级: FakeLLM 产出结构化 ToolCall 与 TurnOutcome
    ├── test_loop_subgenerators.py # 更新: 验证 _execute_tools_turn 零字符串解析
    ├── test_registry.py       # 更新: 验证 ToolRegistry 原生字典执行
    └── test_context.py        # 验证: 纯异步摘要调用
```

---

### Task 1: 模型层 `my-agent-llm` 升级（结构化 `ToolCall`、`TurnOutcome` 与 Providers 装配）

**Files:**

- Modify: `packages/my-agent-llm/src/my_agent_llm/models.py`
- Modify: `packages/my-agent-llm/src/my_agent_llm/providers/openai.py`
- Modify: `packages/my-agent-llm/src/my_agent_llm/providers/deepseek.py`
- Modify: `packages/my-agent-llm/src/my_agent_llm/providers/anthropic.py`
- Modify: `packages/my-agent-llm/tests/test_client.py` (或新增 `test_models.py`)

**Interfaces:**

- Produces:
  - `TurnOutcome(str, Enum)`: `COMPLETED = "completed"`, `TOOL_CALLS = "tool_calls"`, `LENGTH = "length"`, `CONTENT_FILTER = "content_filter"`, `ABORTED = "aborted"`, `PROVIDER_ERROR = "provider_error"`, `UNKNOWN = "unknown"`.
  - `normalize_finish_reason(reason: str | None, has_tool_calls: bool = False) -> TurnOutcome`.
  - `ToolCall(BaseModel)`: `id: str`, `name: str`, `args: dict[str, Any] = Field(default_factory=dict)`, `error: str | None = None`.
  - `Response.outcome`: 返回 `TurnOutcome`.
  - `Response.to_message()`: 将自身转为 `Message(role="assistant", content=..., metadata={"tool_calls": [...], "stop_reason": ...})`.
  - `StreamChunk.response`: 终态 chunk 携带已完成反序列化的完整 `Response`.

- [ ] **Step 1: 编写针对新模型层的失败测试**

在 `packages/my-agent-llm/tests/test_models.py` 中编写测试用例：

1. 测试 `ToolCall` 初始化：接收 `id`, `name`, `args: dict`；
2. 测试 `TurnOutcome` 映射：`"stop" -> COMPLETED`, `"end_turn" -> COMPLETED`, `"tool_calls" -> TOOL_CALLS`, `"tool_use" -> TOOL_CALLS`, `"length" -> LENGTH`；
3. 测试 `Response.to_message()` 产出的元数据包含规范化 `tool_calls`（含 `args` 字典）与 `stop_reason`；
4. 测试 Anthropic provider 提取 `block.input` 直接生成 `ToolCall.args: dict`。

- [ ] **Step 2: 运行测试并确认红灯**

```bash
cd packages/my-agent-llm && uv run python -m pytest tests/test_models.py -q
```

- [ ] **Step 3: 实现 `models.py` 与各 Providers**

1. 在 `models.py` 中实现 `TurnOutcome`、`normalize_finish_reason` 与 `ToolCall`；
2. 在 `openai.py` 的 `_ToolCallAccumulator.finish()` 中对拼装完的 arguments 执行 `json.loads`，反序列化为 `dict` 存入 `ToolCall.args`；若 JSON 非法，记录 `ToolCall.error` 且 `args={}`；
3. 在 `anthropic.py` 中直接将 `block.input`（已是 dict）赋给 `ToolCall(args=block.input)`，彻底删除 `json.dumps` 转换；
4. 更新各 Provider 的 `chat`, `achat`, `stream`, `achat_stream` 产出结构化 `ToolCall` 与 `final_response`。

- [ ] **Step 4: 运行 `my-agent-llm` 测试并确认全绿**

```bash
cd packages/my-agent-llm && uv run python -m pytest -q
```

- [ ] **Step 5: 提交代码**

```bash
git add packages/my-agent-llm
git commit -m "feat(llm): 升级结构化 ToolCall、引入 TurnOutcome 状态机并消除 Anthropic 冗余 dumps"
```

---

### Task 2: 升级 `registry.py` 原生字典分发与净化 `context.py`

**Files:**

- Modify: `packages/my-agent-core/src/my_agent_core/registry.py`
- Modify: `packages/my-agent-core/src/my_agent_core/context.py`
- Modify: `packages/my-agent-core/tests/test_registry.py`
- Modify: `packages/my-agent-core/tests/test_context.py`

**Interfaces:**

- Produces:
  - `ToolRegistry.execute_tool(name: str, args: dict[str, Any] | str, tool_call_id: str | None = None) -> ToolResult`: 支持入参直接为 `dict`，跳过 `json.loads`；若为 `str` 则兜底解析。
  - `ToolRegistry.execute_batch(calls: Sequence[tuple[str, dict[str, Any]] | dict[str, Any]]) -> list[ToolResult]`: 支持直接传入 `(name, args_dict)` 元组列表并发执行。
  - `ContextManager._call_summarizer()`: 移除 `hasattr(self.llm, "achat")`，直接调用 `await self.llm.achat(messages=msgs, tools=[])`。

- [ ] **Step 1: 编写失败测试**

在 `packages/my-agent-core/tests/test_registry.py` 中添加用例：

1. 直接用字典 `args={"a": 1, "b": 2}` 调用 `execute_tool("add", {"a": 1, "b": 2})`，验证免 JSON 字符串解析成功执行；
2. 传入 `(name, args)` 结构调用 `execute_batch`；
在 `packages/my-agent-core/tests/test_context.py` 中验证 `ContextManager` 纯异步调用。

- [ ] **Step 2: 运行测试确认红灯**

```bash
cd packages/my-agent-core && uv run python -m pytest tests/test_registry.py tests/test_context.py -q
```

- [ ] **Step 3: 实现 `registry.py` 与 `context.py`**

1. 修改 `ToolRegistry.execute_tool`，入参类型扩展支持直接传 `args: dict[str, Any]`；若传入已经是字典，直接跳过 `try/except json.loads`；
2. 修改 `ToolRegistry.execute_batch`，支持列表项为 `tuple[str, dict]` 或已解析好的字典对象；
3. 清理 `context.py` 第 484 行，只保留 `resp = await self.llm.achat(messages=msgs, tools=[])`。

- [ ] **Step 4: 运行测试确认绿灯**

```bash
cd packages/my-agent-core && uv run python -m pytest tests/test_registry.py tests/test_context.py -q
```

- [ ] **Step 5: 提交代码**

```bash
git add packages/my-agent-core/src/my_agent_core/registry.py packages/my-agent-core/src/my_agent_core/context.py packages/my-agent-core/tests/test_registry.py packages/my-agent-core/tests/test_context.py
git commit -m "refactor(core): ToolRegistry 支持原生字典执行，context 纯异步化"
```

---

### Task 3: 调度微内核 `loop.py` 重构（彻底消灭 4 重 JSON 序列化）与 `tool_history.py` 适配

**Files:**

- Modify: `packages/my-agent-core/src/my_agent_core/loop.py`
- Modify: `packages/my-agent-core/src/my_agent_core/tool_history.py`
- Modify: `packages/my-agent-core/tests/conftest.py`
- Modify: `packages/my-agent-core/tests/test_loop_subgenerators.py`
- Modify: `packages/my-agent-core/tests/test_tool_history.py`

**Interfaces:**

- Consumes:
  - `ToolCall(id, name, args: dict, error)` from `my_agent_llm.models`.
  - `registry.execute_batch` with `(name, args)` from `Task 2`.
- Produces:
  - `_execute_tools_turn`: 接收 `Sequence[ToolCall | dict[str, Any]]`。如果元素具备 `tc.name` 与 `tc.args`（字典），直接消费，0 行 `json.loads`！
  - 遇到 `tc.error`（解析错误），直接生成失败的 `ToolResult`，不发生未捕获异常。
  - `_get_tool_calls(msg: Message)`: 统一从 `msg.metadata["tool_calls"]` 提取结构化调用信息。

- [ ] **Step 1: 编写失败测试**

1. 在 `test_loop_subgenerators.py` 中，编写直接向 `_execute_tools_turn` 传入结构化 `ToolCall(id="1", name="add", args={"a": 2, "b": 3})` 的用例；
2. 验证产生的 `ToolExecutionStart` 的 `args` 严格匹配字典；
3. 验证参数改写 Hook 接收与修改字典无阻；
4. 验证当 `ToolCall.error` 存在时，产生 `is_error=True` 的 `ToolExecutionEnd` 与错误消息。

- [ ] **Step 2: 运行测试确认红灯**

```bash
cd packages/my-agent-core && uv run python -m pytest tests/test_loop_subgenerators.py -q
```

- [ ] **Step 3: 重构 `loop.py` 与更新 `conftest.py`**

1. 更新 `conftest.py` 中的 `FakeLLM`：在 `achat_stream` 产出终态 `StreamChunk.response` 时装配结构化 `ToolCall(args=...)`；
2. 重写 `loop.py` 中的 `_execute_tools_turn`：
   - 遍历 `tool_calls`，统一解包为 `(idx, tc_id, name, args: dict, err)`；
   - 彻底删除第 250-270 行的 `raw_args = func.get("arguments", "{}")` 和 `json.loads`；
   - 彻底删除第 310 行的 `calls_to_run = [{..., "arguments": json.dumps(args)}]` 拼串代码，直接构造 `[(name, args)]` 提交给 `registry.execute_batch`；
3. 适配 `tool_history.py` 中的 `_get_tool_calls`，确保同时支持提取带有 `name`/`args` 键的字典。

- [ ] **Step 4: 运行 `test_loop_subgenerators.py` 和 `test_tool_history.py` 确认绿灯**

```bash
cd packages/my-agent-core && uv run python -m pytest tests/test_loop_subgenerators.py tests/test_tool_history.py -q
```

- [ ] **Step 5: 提交代码**

```bash
git add packages/my-agent-core/src/my_agent_core/loop.py packages/my-agent-core/src/my_agent_core/tool_history.py packages/my-agent-core/tests/conftest.py packages/my-agent-core/tests/test_loop_subgenerators.py packages/my-agent-core/tests/test_tool_history.py
git commit -m "refactor(core): loop.py 直接消费结构化 ToolCall，彻底消除 4 重 JSON 编解码死循环"
```

---

### Task 4: 全量离线回归与真实 DeepSeek API 端到端验证

**Files:**

- Test all: `packages/my-agent-core/tests/`, `packages/my-agent-llm/tests/`, `packages/my-coding-agent/tests/`
- Verification script: `packages/my-agent-core/test_run.py`

**Interfaces:**

- 验证全量 382+ 离线测试无任何回归；
- 验证所有静态类型检查（`lsp_diagnostics`）零错误；
- 验证端到端真实大模型调用（数学运算工具调用与实时流式输出）。

- [ ] **Step 1: 运行核心层与模型层全量测试**

```bash
cd packages/my-agent-llm && uv run python -m pytest -q
cd ../my-agent-core && uv run python -m pytest -q
cd ../my-coding-agent && uv run python -m pytest -q
```

- [ ] **Step 2: 静态类型检查与代码精简审查（pi-simplify）**

调用 `lsp_diagnostics` 检查所有修改的文件，确保无任何类型与语法警告。

- [ ] **Step 3: 运行真实 DeepSeek API 测试**

运行包含工具调用的测试脚本，确认流式输出中 Tool 调用平滑执行，日志中无任何 JSON 序列化反序列化报错：

```bash
cd packages/my-agent-core && uv run python -c "
import asyncio, os
from dotenv import load_dotenv
load_dotenv('.env')
from my_agent_llm import LLM
from my_agent_core.agent import Agent
from my_agent_core.tools import tool

@tool
def add(a: int, b: int) -> int:
    '''加法计算'''
    return a + b

async def main():
    llm = LLM(provider='deepseek', api_key=os.environ.get('DEEPSEEK_API_KEY'), model='deepseek-chat', base_url='https://api.deepseek.com')
    agent = Agent(llm=llm, tools=[add])
    async for event in agent.prompt_stream('计算 123 + 456'):
        print(f'Event: {type(event).__name__}')

asyncio.run(main())
"
```

- [ ] **Step 4: 最终提交**

```bash
git commit -am "chore: 完成 Phase 20 全量离线回归与端到端真实 API 验证"
```
