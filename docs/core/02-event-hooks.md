# 事件驱动与生命周期拦截体系 (`my_agent_core.events`)

- **定位**：Agent 神经系统与可观测拦截总线 (`packages/my-agent-core/src/my_agent_core/events.py`)
- **核心类**：`Event`, `Interceptable`, `HookResult`, `HookRegistry`
- **12 大生命周期事件**：`AgentStart`, `AgentEnd`, `TurnStart`, `TurnEnd`, `MessageStart`, `MessageUpdate`, `MessageEnd`, `ToolExecutionStart`, `ToolExecutionUpdate`, `ToolExecutionEnd`, `ContextCompacted`, `UserInput`, `BeforeModelCall`

---

## 一、架构设计与定位

`events.py` 是 Agent 的神经系统，兼具两大能力：

1. **生命周期可观测性（Observability）**：对外广播 Agent 内部每一轮循环、每一次模型流式生成、每一个工具执行事件；
2. **五大生命周期拦截决策点（Interception Points）**：支持扩展挂载 Hook 对输入、系统提示词、模型上下文视图、工具入参和出参进行原地改写或阻断。

```text
               用户输入 (User Prompt)
                         │
                         ├─► [1. UserInput] ────────────► 前置改写或阻断
                         ├─► [2. AgentStart] ───────────► 动态改写首条 System Prompt
                         │
                         ▼
               进入 Agent ReAct 异步循环
                         │
                         ├──► [3. BeforeModelCall] ─────► 临时改写发往大模型的上下文 view
                         │
                         │    LLM 返回 tool_call:
                         │    ├──► [4. ToolExecutionStart] ──► 参数修补或阻断拦截
                         │    ├──► (执行工具真实逻辑)
                         │    └──► [5. ToolExecutionEnd] ────► 篡改返回给模型的 tool 出参
                         │
                         └──► [TurnEnd / AgentEnd]
```

---

## 二、统一干预模型：`HookResult`

所有可拦截事件（继承自 `Interceptable`）的回调函数均共享统一强类型的 `HookResult` 数据结构：

```python
@dataclass(frozen=True)
class HookResult:
    """Hook 回调的干预结果。返回 None = 纯观察，返回 HookResult = 强干预。"""
    block: bool = False
    reason: str | None = None

    # 决策点 1: 改写用户输入文本
    updated_input: str | None = None

    # 决策点 2: 动态改写 System Prompt
    updated_system_prompt: str | None = None

    # 决策点 3: 临时改写发给大模型的 messages 视图
    updated_messages: list[Message] | None = None

    # 决策点 4: 改写工具入参
    updated_args: dict | None = None

    # 决策点 5: 改写工具出参
    updated_result: str | None = None
```

---

## 三、核心机制与设计不变式

### 1. 临时视图隔离 vs Session 零污染不变式（Zero-Pollution Invariant）

在 `BeforeModelCall` 中，扩展若返回 `updated_messages`（例如临时注入一条 `[EPHEMERAL WARNING]`）：

- **只修改** 当前这次发给大模型的局部 `view` 变量；
- **绝不追加** 进 `self.messages` 内存列表，也**绝不落盘**进 `session.jsonl`；
- 保障了会话树存储与持久化历史的纯粹性与真实确定性。

### 2. 流式 Token 级实时熔断（`MessageUpdate`）

在大模型流式生成的过程中，增量事件 `MessageUpdate` 同样支持 `Interceptable`。若扩展检测到违规或危险输出内容，返回 `HookResult(block=True)` 即可毫秒级掐断流式输出，并且框架会**直接丢弃未完成的半截文本**（不写入 Session 树），彻底避免模型在下一轮产生“断句续写”的严重幻觉。

### 3. 短路拦截与错误隔离

- 多个 Hook 订阅同一事件时，第一个返回 `HookResult(block=True)` 或非空干预字段的 Hook 会立即短路生效；
- Hook 执行异常被框架内部安全捕获，防止第三方插件异常打崩核心生命周期。
