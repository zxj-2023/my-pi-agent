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

---

## 四、深度辨析：宏观串并行 vs 微观同异步（及异步队列的本质）

在工具系统的工程实现中，必须彻底厘清**“宏观批调度的串并行”**与**“微观函数的同异步”**这两个正交维度：

| 维度 | 关心的核心问题 | 决定者 | 核心实现手段 |
| :--- | :--- | :--- | :--- |
| **维度 1：宏观批处理 (并发 vs 串行)** | 这批工具是一起开工，还是排队执行？ | `ToolRegistry.execute_batch` (基于 `is_parallel_safe` 属性) | 并发：`asyncio.gather(...)`；串行：`for` 循环依次 `await` |
| **维度 2：单工具执行 (主线程 vs 子线程)** | 这个工具自身会阻塞事件循环吗？ | `Tool.execute` (基于 `inspect.iscoroutinefunction`) | 异步（`async def`）：主线程协程直接跑；同步（普通 `def`）：扔进系统线程池 `asyncio.to_thread` |

### 1. 异步队列里流动的到底是什么？
>
> **关键认知**：  
> 异步队列 `queue` 里面装的**不是工具执行的最终返回值（`ToolResult`）**！最终结果是在批处理 Task 结束时由 `batch_out = await runner` 一次性拉取的列表。  
> **队列里流动的，纯粹是工具执行中途发射出来的“实时过程流式事件”（`ToolExecutionUpdate`）**。

### 2. 并行与串行在流水线中的具体运行行为

- **并行模式（全只读安全工具）**：
  - 宏观上 `execute_batch` 使用 `asyncio.gather` 同时打出所有工具；
  - 异步协程工具在主事件循环运行，同步阻塞工具被 `asyncio.to_thread` 发配到各个工作子线程运行；
  - 各工具中途产生进度时，主线程直接推入 `queue`，子线程通过 `loop.call_soon_threadsafe` 跨线程安全预约推入 `queue`；
  - 前台生成器实时 `yield` 谁最新产生的事件，呈现交织滚动的流式效果。
- **串行模式（含任一写操作/非安全工具）**：
  - 宏观上 `execute_batch` 退化为顺序 `for` 循环；
  - 工具 1 执行中产生进度流入 `queue` $\to$ 前台实时打印 $\to$ 工具 1 完成；
  - 工具 2 执行中产生进度流入同一个 `queue` $\to$ 前台接着实时打印 $\to$ 工具 2 完成；
  - 整批完成后由 `finally` 注入 `_SENTINEL` 哨兵，队列消费无缝复用，零冗余代码。

---

## 五、实战指南：什么样的工具写成 async def？什么样的工具写成普通 def？

核心判断准则：**工具执行时主要是在“等外部网络/事件”，还是在“消耗本地 CPU/阻塞型操作系统资源”？**

1. **必须/推荐写成【异步工具】（`async def`）**：
   - **子代理委派（Subagent / Task）**：例如 `task`、`delegate_subagent`。等待子 Agent 的整个 LLM 交互与工具循环，必须通过 `await` 挂起；
   - **网络请求与外部服务（Web Search / Crawl / MCP）**：基于 `httpx.AsyncClient` 或 `aiohttp`，等待远程握手与数据传输；
   - **浏览器自动化（Playwright）**：等待 DOM 渲染、页面导航，天然全是非阻塞异步 Promise。
2. **通常写成【同步工具】（普通 `def`）**：
   - **本地小文件读写与外科手术式编辑（`read` / `write` / `edit`）**：本地 SSD 耗时通常小于 1 毫秒，用普通的 `pathlib` 或 `open()` 简洁高效，无额外调度开销；
   - **CPU 密集运算与正则匹配（`grep` / `calculator` / `ast-grep`）**：纯计算无空闲等待，无需 `async`；
   - **封装阻塞式系统库的工具（`bash`）**：调用原生的 `subprocess.run(...)`。
3. **框架的自适应无感桥接（Zero Mental Overhead）**：
   `Tool.execute` 内部根据 `self.is_async` 自动路由：`async def` 直接协程 `await`，普通 `def` 自动包裹 `asyncio.to_thread`。开发者想怎么写就怎么写，既不卡死 Agent 主事件循环，又拥有极致执行性能。
