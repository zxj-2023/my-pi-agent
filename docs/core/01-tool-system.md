# 工具系统设计规范 (`my_agent_core.tools`)

- **定位**：框架核心层工具原语 (`packages/my-agent-core/src/my_agent_core/tools/`)
- **核心类**：`Tool`, `@tool`, `ToolRegistry`, `ToolResult`
- **主要实现**：`tools/core.py`, `registry.py`

---

## 一、架构设计与定位

工具系统是 Agent 与外部环境交互的手和脚。`my-agent-core` 的工具系统设计强调三点：

1. **自动提取契约**：基于 Pydantic 从 Python 函数动态生成标准化 Function Calling Schema；
2. **Never-Throw 架构保证**：工具异常绝不上抛打崩主程序，包装为结构化错误引导 LLM 自愈；
3. **并发批执行分流**：支持声明式 `is_parallel_safe` 并发加速与严格保序回填。

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
  (register / execute_batch / get_schemas)
```

---

## 二、核心类与机制

### 1. `@tool` 装饰器与 Pydantic 动态建模

```python
@tool(name="calculator", description="计算算术表达式")
def calculate(expr: str, precision: int = 2) -> float:
    ...
```

- 底层使用 `pydantic.create_model` 从函数形参、类型注解与默认值动态合成参数验证模型；
- 自动生成符合 OpenAI / Anthropic 规范的 JSON Schema 字典。

### 2. `Tool` 实体对象

- **`raw_schema` 支持**：支持直接接收外部/远程传入的 JSON Schema 字典（如 MCP 远程工具），无需定义本地 Python 函数签名；
- **`is_parallel_safe` 标记**：声明式只读并发安全标记。当大模型单轮返回多个并发工具调用时，`ToolRegistry.execute_batch` 利用 `asyncio.gather` 并行执行，将多工具串行调用的 $O(N)$ 耗时降为 $O(1)$。

### 3. `ToolResult` 与 Never-Throw 保证

```python
@dataclass
class ToolResult:
    ok: bool
    data: Any = None
    error: str | None = None
```

- 任何参数校验失败（`ValidationError`）或业务执行异常，统一在 `Tool.execute()` 内部被 `try...except` 拦截；
- 转换为 `ToolResult(ok=False, error="...")` 并格式化为 `role="tool"` 消息喂回大模型，由模型进行下一轮自我纠错。

---

## 三、`ToolRegistry` 注册表调度

- **注册与查表**：`register(tool)`、`unregister(name)`、`get(name)`、`get_schemas()`；
- **批执行调度 (`execute_batch`)**：
  - 自动识别批次中哪些工具是 `is_parallel_safe=True` 并行执行，哪些是串行执行；
  - 执行完毕后，严格按照大模型最初发起 Tool Calls 的索引顺序重组回填进 Session 树，保证确定性。
