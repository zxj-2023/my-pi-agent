# 工具系统设计规范 (`my_agent_core.tools`)

- **定位**：框架核心层工具原语与执行调度引擎 (`packages/my-agent-core/src/my_agent_core/tools/`, `registry.py`)
- **核心类**：`Tool`, `@tool`, `ToolRegistry`, `ToolResult`, `ToolCall`
- **主要实现**：`tools/core.py`, `registry.py`, `tools/builtin/`

---

## 一、架构设计与定位

工具系统是 Agent 与外部物理环境交互的手和脚。`my-agent-core` 的工具系统深度对标 **Tau** 与 **Pi** 的微内核设计，强调四大核心设计不变式：

1. **自动提取契约**：基于 Pydantic v2 从 Python 函数签名动态提取标准化 Function Calling Schema；
2. **结构化 ToolCall 第一公民**：在模型边界层完成参数反序列化，微内核与注册表原生消费字典（`args: dict`），**彻底消灭 4 重 JSON 编解码死循环（4x JSON Ping-Pong）**；
3. **Never-Throw 强稳定性保证**：任何参数校验失败或业务执行异常，统一包装为结构化错误引导 LLM 自我修正，绝不让异常崩溃蔓延至主循环；
4. **并发批执行与因果时序保护**：支持声明式 `is_parallel_safe` 并发加速，并引入“一票否决”严格因果时序降级与保序回填机制。

```text
       普通 Python 函数 / 远程 MCP 工具
                     │
                     ▼
         @tool 包装 或 Tool(raw_schema=...)
                     │
                     ▼
             Tool 实体实例
      (to_openai_schema / execute)
                     │
                     ▼
               ToolRegistry
  (register / execute_tool / execute_batch / get_schemas)
```

---

## 二、核心类与机制

### 1. 结构化 `ToolCall` 实体（一等公民）

```python
class ToolCall(BaseModel):
    """统一结构化工具调用对象（由模型边界层输出）。"""
    id: str
    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
```

- **消除 4x JSON Ping-Pong**：在传统实现中，模型层输出 JSON 字符串 ➔ 核心层解析为字典进行 Hook 检查 ➔ 核心层重新序列化为字符串传给注册表 ➔ 注册表再次反序列化传给函数。
- **现代化重塑**：模型边界层（`my-agent-llm`）直接交付已经完成反序列化的结构化 `ToolCall`（Anthropic 原生直接使用 `block.input` 字典），核心微内核 `loop.py` 与 `ToolRegistry` 全程直接消费原生字典，零多余序列化开销。

### 2. `@tool` 装饰器与 Pydantic 动态建模

```python
@tool(name="calculator", description="计算算术表达式", is_parallel_safe=True, timeout=10.0)
def calculate(expr: str, precision: int = 2) -> float:
    ...
```

- 底层使用 `pydantic.create_model` 从函数形参、类型注解与默认值动态合成参数验证模型；
- 自动生成符合 OpenAI / Anthropic 规范的 Function Calling JSON Schema 字典；
- 运行时在调用真实函数前通过 `params_model.model_validate` 进行强类型校验与宽松类型转换（如 `"37"` 自动转换为 `37`）。

### 3. `Tool` 实体对象

- **`raw_schema` 支持**：支持直接接收外部或远程传入的 JSON Schema 字典（如 MCP 远程工具），无需定义本地 Python 函数签名；
- **`timeout` 超时防护**：配置工具执行超时上限（秒），底层通过 `asyncio.wait_for` 拦截慢操作，超时自动转化为 `ToolResult(ok=False, error="Tool execution timed out after X seconds")`；
- **`is_parallel_safe` 标记**：声明式只读并发安全标记。当大模型单轮返回多个并发工具调用时，`ToolRegistry.execute_batch` 利用 `asyncio.gather` 并行执行，将多工具串行调用的 $O(N)$ 耗时降为 $O(1)$。

### 4. `ToolResult` 与 Never-Throw 保证

```python
@dataclass
class ToolResult:
    """工具执行结果：成功/失败 + 数据或错误消息 + 结构化元数据。"""
    ok: bool
    data: Any = None
    error: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def serialize(self) -> str:
        """转成写入 messages 的字符串。失败时返回错误文本。"""
        if self.ok:
            return str(self.data)
        return self.error or "Unknown error"
```

- 任何参数校验失败（`ValidationError`）、超时（`TimeoutError`）或业务执行异常，统一在 `Tool.execute()` 内部被捕获；
- 转换为 `ToolResult(ok=False, error="...")` 并通过 `serialize()` 生成 `role="tool"` 消息喂回大模型，由模型进行下一轮自我纠错。

---

## 三、`ToolRegistry` 注册表调度与因果时序保护

### 1. 多态分发：`execute_tool`

`ToolRegistry.execute_tool` 支持灵活的入参形式，抹平外部协议差异：

1. **原生结构化传参**：`execute_tool(name="add", args={"a": 1})`
2. **元组传参**：`execute_tool(("add", {"a": 1}))`
3. **实体传参**：`execute_tool(ToolCall(id=..., name="add", args={"a": 1}))`
4. **Wire 字典传参**：`execute_tool({"name": "add", "args": {...}})` 或 `{"function": {"name": "...", "arguments": "..."}}`

如果 `args` 已为 Python 字典，直接跳过 `json.loads`；若为字符串则执行安全解析与异常转译。

### 2. 批执行调度与“一票否决”因果时序保护 (`execute_batch`)

- **因果时序一致性（Causal Consistency）**：
  当大模型在单轮中同时输出多个工具调用（例如 `ToolCall 1 (write: 修改文件)` 与 `ToolCall 2 (read: 确认文件内容)`），绝不能盲目把只读工具提前并发执行，否则会导致 `read` 先于 `write` 读到旧数据（产生严重的因果倒置错误）。
- **一票否决降级机制（Unanimous Parallel / Sequential Fallback）**：
  - **全员只读并发**：当且仅当批次中的**每一个**工具均为 `is_parallel_safe=True` 时，才放行 `asyncio.gather` 并行执行；
  - **含写严格串行**：只要批次中包含**任何一个**写操作（或未知工具），整批工具立即放弃并发，**严格按照大模型输出的原始先后顺序串行执行**，确保因果顺序绝对正确。
- **保序回填（Preserved Order Invariant）**：
  执行完毕后，返回的 `ToolResult` 列表严格与入参 `tool_calls` 的索引位置完全对齐，确保生成的消息历史与模型调用上下文 1:1 保序匹配。
