# 单层 Agent 与原生异步 ReAct 循环设计规范 (`my_agent_core.agent`)

- **定位**：Agent 核心执行中枢与内联状态机 (`packages/my-agent-core/src/my_agent_core/agent.py`)
- **核心类**：`Agent`
- **关键 API**：`run(user_input)`, `invoke_skill(name, instructions)`, `reset()`, `compact()`, `abort()`

---

## 一、架构设计与定位

`Agent` 是整个框架的核心中枢。我们摒弃了复杂的状态图机制（如 LangGraph），采用了清晰的 **单层架构（Single-Layer Architecture）**：

- **状态集中**：单一 `Agent` 类直接持有 `LLM` 门面、`ToolRegistry` 注册表、`Session` 会话树、`ContextManager` 上下文管线与 `HookRegistry` 事件总线；
- **原生异步 ReAct 循环**：在 `Agent.run()` 中直接以异步原生 `while` 循环完成 Reason ➔ Act ➔ Observe 状态迭代；
- **生命周期编排**：协调决策拦截点、流式中断丢弃与多工具批执行回填。

```text
                           Agent.run(user_input)
                                     │
                                     ▼
                ┌────────────────────────────────────────┐
                │ 1. 决策点 1: UserInput 前置拦截改写     │
                │ 2. 写入 Session 树并生成 user Message  │
                │ 3. 决策点 2: AgentStart 动态系统提示词 │
                └────────────────────┬───────────────────┘
                                     │
                                     ▼ (进入 ReAct 异步循环)
    ┌─────────────────────────────────────────────────────────────────┐
    │ while iteration < max_iterations:                               │
    │   1. _ctx.prepare(messages) ➔ 产出压缩上下文视图 view            │
    │   2. 决策点 3: BeforeModelCall 临时视图改写 (Session 零污染)    │
    │   3. llm.achat_stream(view, tools) ➔ 流式接收 Token             │
    │      └─ MessageUpdate Hook 实时熔断监控 (丢弃未完成半截)        │
    │   4. 检查是否有 tool_calls:                                     │
    │      ├─ 无 ➔ 结束循环，发射 AgentEnd，返回最终回答文本           │
    │      └─ 有 ➔ 5. 批准备与 ToolExecutionStart 参数拦截/阻断       │
    │              6. registry.execute_batch (全只读并发/含写保序串行) │
    │              7. ToolExecutionEnd 篡改出参                       │
    │              8. 严格保序回填 Session 树与 messages              │
    └─────────────────────────────────────────────────────────────────┘
```

---

## 二、关键机制与实现细节

### 1. 经典退出条件与最大迭代保护

- **自然退出**：当大模型在一轮推理后不再发起任何 `tool_calls` 时，循环自然终止，触发 `AgentEnd(stop_reason="end_turn")` 并返回文本答案；
- **迭代保护**：支持配置 `max_iterations`，达到上限时安全退出并返回 `None`。

### 2. 状态重置与多轮恢复

- **`reset()`**：清空会话树，并重新从磁盘读取 Memory 记忆快照、重新拼装首条 System Message，恢复为全新会话起点；
- **`abort()`**：异步取消正在运行的任务，将内部状态标记为 `_aborted = True`，并在流式循环中立即截断且**不向 Session 写入半截脏数据**。

### 3. 三态资源自动装配

构造函数 `Agent.__init__` 支持统一的三态装配模式：

- `skill_dirs`：`None` 自动探测 `<cwd>/.agents/skills` / `[]` 禁用 / 自定义路径；
- `subagent_dirs`：`None` 自动探测 `<cwd>/.agents/agents` / `[]` 禁用 / 自定义路径；
- `extension_dirs`：`None` 自动探测 `<cwd>/.agents/extensions` / `[]` 禁用 / 自定义路径；
- `memory_dir`：`None` 自动探测 `<cwd>/.my_agent_core/memory` / `False` 显式禁用 / 自定义路径；
- `plugin_dirs`：`None` 自动探测 `<cwd>/.agents/plugins` / `[]` 禁用 / 自定义路径。
