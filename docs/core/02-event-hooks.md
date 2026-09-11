# 事件驱动与生命周期拦截体系 (`my_agent_core.events` & `hooks`)

- **定位**：Agent 神经系统（只读事实广播）与关键控制流安全门禁拦截总线 (`packages/my-agent-core/src/my_agent_core/events.py`, `hooks.py`)
- **核心模块**：
  - `events.py`：12 种纯只读事实事件（`Event` 基类，不可变数据结构，只单向向外广播）
  - `hooks.py`：五大专职 Hook 决策拦截点（`*Hook` 数据结构）、`HookResult` 统一干预模型与 `HookRegistry`
- **主要实现**：`events.py`, `hooks.py`, `extensions/core.py`

---

## 一、架构设计：正交解耦模型

在对标 **Pi (`@earendil-works/pi-coding-agent`)** 与 **Tau (`tau-ai`)** 的演进中，系统对生命周期机制进行了**彻底正交化重构**：

> **核心设计原则：纯只读事实流 与 双向控制流拦截 彻底物理分离**
>
> - **事实通知（Events）**：纯只读、不可变（`frozen=True`），自动记录时间戳，由核心调度微内核（`loop.py`）单向向外 `yield`，供 UI 渲染、日志跟踪、Web SSE 转发等只读消费，绝无返回值，**彻底废除旧版 `Interceptable` 标记**；
> - **策略门禁（Hooks）**：双向决策拦截点，集中定义于 `hooks.py`。由 `HookRegistry` 统一调度，支持短路阻断（`block=True`）或原地修改数据（改写用户输入、提示词、模型视图、工具参数、工具结果）。

```text
               用户输入 (User Prompt)
                         │
                         ├─► [Hook 1: UserInputHook] ──────► 前置改写输入文本或阻断
                         ├─► [Event: AgentStart] ──────────► 广播启动事实
                         ├─► [Hook 2: AgentStartHook] ─────► 动态改写首条 System Prompt
                         │
                         ▼
               进入 Agent ReAct 异步循环 (run_agent_loop)
                         │
                         ├──► [Event: TurnStart] ──────────► 广播轮次开始
                         ├──► [Hook 3: BeforeModelCallHook] ► 临时改写送给大模型的 view (Session 零污染)
                         │
                         │    委托模型车间 (_assistant_turn):
                         │    ├──► 逐字广播 [Event: MessageUpdate] (打字机增量)
                         │    └──► 发射 [Event: MessageStart / MessageEnd] (Assistant 终态)
                         │
                         │    委托工具车间 (_execute_tools_turn):
                         │    ├──► Preflight 预检: 率先广播 [Event: ToolExecutionStart] (UI 渲染运行态)
                         │    ├──► [Hook 4: ToolCallHook] ───► 安全审批改参或阻断高危命令
                         │    ├──► (并发批执行真实工具逻辑)
                         │    ├──► [Hook 5: ToolResultHook] ─► 篡改出参结果或报错状态
                         │    ├──► Completion 完结: 广播 [Event: ToolExecutionEnd] (按完成顺序)
                         │    └──► 按调用声明顺序发射配对 [Event: MessageStart / MessageEnd] (role="tool")
                         │
                         ├──► 严格闭环当前轮次: 广播 [Event: TurnEnd]
                         └──► 收割 Steer 转向 / Follow-up 追问 ...
                         │
                         ▼
               退出循环: 广播 [Event: AgentEnd]
```

---

## 二、纯只读事实事件体系 (`events.py`)

所有事件继承自 `Event` 基类，不可变（`frozen=True`），使用 `__post_init__` 自动注入系统时间戳：

```python
@dataclass(frozen=True)
class Event:
    """生命周期事实事件基类（纯只读广播，不可变）。"""
    timestamp: float = field(init=False)
```

### 12 大生命周期事件清单

| 分类 | 事件名 | 核心属性 | 广播时机与作用 |
| :--- | :--- | :--- | :--- |
| **宏观生命周期** | `AgentStart` | `system_prompt`, `user_input` | Agent 全流程启动时广播 |
| | `AgentEnd` | `messages`, `final_text`, `iterations`, `stop_reason` | Agent 结束（`"end_turn"` / `"max_iterations"` / `"cancelled"` / `"blocked"` / `"error"`） |
| **微观轮次** | `TurnStart` | `iteration` | 单轮推理循环开始 |
| | `TurnEnd` | `message`, `tool_results` | 单轮推理循环结束（**严格保证成对闭合**，即使中途报错或拦截） |
| **对话流消息** | `MessageStart` | `message` | 某条完整消息加入对话流通知 |
| | `MessageUpdate` | `message`, `chunk` | 流式 Token 增量更新（打字机 UI 实时渲染专用） |
| | `MessageEnd` | `message` | 某条消息内容完全落定时广播 |
| **工具执行** | `ToolExecutionStart` | `tool_call_id`, `tool_name`, `args` | **Preflight 阶段按声明顺序率先广播**，通知 UI 工具正准备运行 |
| | `ToolExecutionUpdate` | `tool_call_id`, `tool_name`, `args`, `partial_result` | 工具流式输出或长时间运行进度广播 |
| | `ToolExecutionEnd` | `tool_call_id`, `tool_name`, `result`, `is_error` | 工具执行完毕，按真实完成顺序发射 |
| **内部状态** | `ContextCompacted` | `tokens_before`, `tokens_after`, `summarized_count` | 触发上下文压缩后广播压缩统计 |
| | `ToolsChanged` | `action`, `name` | 动态注册或注销工具时的通知 |

---

## 三、五大专职 Hook 拦截点与干预模型 (`hooks.py`)

### 1. 五大拦截点契约

```python
@dataclass(frozen=True)
class UserInputHook:
    """Hook 1: 拦截或改写用户原始输入文本。"""
    input_text: str

@dataclass(frozen=True)
class AgentStartHook:
    """Hook 2: 拦截启动或动态重写 system_prompt。"""
    system_prompt: str

@dataclass(frozen=True)
class BeforeModelCallHook:
    """Hook 3: 调模型前 1ms 审查或临时改写发送视图。"""
    messages: list[Message]
    iteration: int

@dataclass(frozen=True)
class ToolCallHook:
    """Hook 4: 工具执行前安全审批、阻断高危命令或改写入参。"""
    tool_call_id: str
    tool_name: str
    args: dict[str, Any]

@dataclass(frozen=True)
class ToolResultHook:
    """Hook 5: 工具执行后改写返回内容或篡改报错状态。"""
    tool_call_id: str
    tool_name: str
    result: str
    is_error: bool
```

### 2. 统一干预结果模型 (`HookResult`)

Hook 监听函数返回 `None` 代表纯观察放行；返回 `HookResult` 代表强行干预控制流：

```python
@dataclass(frozen=True)
class HookResult:
    """Hook 拦截点的统一干预结果。"""
    block: bool = False
    reason: str | None = None
    updated_input: str | None = None
    updated_system_prompt: str | None = None
    updated_messages: list[Message] | None = None
    updated_args: dict[str, Any] | None = None
    updated_result: str | None = None
```

- **阻断控制**：`block=True` 时，状态机根据当前节点优雅中断流程（例如在 `ToolCallHook` 阻断时，直接生成 `ToolResult(ok=False, error=reason)`，不中断整个 Agent；在 `UserInputHook` 阻断时直接退出）；
- **参数改写**：如 `updated_args` 原生接收已解析的 Python 字典并修改，核心微内核直接使用新字典派发执行。

### 3. `HookRegistry` 注册表与调度机制

- **短路求值**：按注册顺序遍历回调，**首个返回非 None `HookResult` 的回调生效并短路**；
- **混合并发与协程自适应**：无缝支持同步函数 `def hook(...)` 与异步协程 `async def hook(...)`；
- **Never-Throw 异常隔离保证**：任何 Hook 回调内部如果抛出未处理异常，`HookRegistry` 捕获异常、记录错误日志并自动跳过，绝不上抛打崩调度循环。

---

## 四、核心设计原则与架构不变式

### 1. 临时视图隔离 vs Session 零污染不变式（Zero-Pollution Invariant）

在 `BeforeModelCallHook` 中，扩展若返回 `updated_messages`（例如临时注入一条临时的 `<TASK_BOARD>` 看板或 `[EPHEMERAL WARNING]`）：

- **只修改** 当前这单次发给大模型的局部 `view` 视图；
- **绝不追加** 进 `self.messages` 内存历史，也**绝不写入持久化 `session.jsonl`**；
- 保障了会话树存储历史的纯粹性与对大模型 Prompt Cache 前缀的最大化命中保护。

### 2. Pi 官方时序契约（Pi Timing Invariant）

工具执行流水线严格对齐 Pi 规范的时序保证：

1. **Preflight 阶段**：在工具真正运行前、在调用 `ToolCallHook` 审批前，**率先按 source order 发射 `ToolExecutionStart`**，确保终端 TUI 或前端界面第一时间渲染出“正在运行”状态指示；
2. **安全门禁阶段**：调用 `ToolCallHook`。若被阻断或改参，在此处完成；
3. **Execution 阶段**：并发执行或串行执行工具；
4. **Completion 阶段**：调用 `ToolResultHook` 篡改出参后，发射 `ToolExecutionEnd`；
5. **消息入流**：按大模型声明的原始先后顺序发射对应 `role="tool"` 的 `MessageStart`/`MessageEnd` 事件。

### 3. 断头调用自愈保证（Dangling ToolCall Invariant）

如果用户在模型生成工具调用后主动取消（`abort`），或模型在流式输出中异常中断：

- 微内核内部自动捕获取消信号；
- 遍历所有未执行的 `tool_calls`，**100% 自动合成为 `role="tool"` 且携带 `Tool call interrupted by user` 的错误消息**；
- 无论何种异常路径退出，**必定发射配对的 `TurnEnd`**，保证大模型下一次调用不会因断头消息触发 API 400 校验死锁。

### 4. 扩展分流机制（`ExtensionAPI.on`）

`packages/my-agent-core/src/my_agent_core/extensions/core.py` 中的 `api.on` 装饰器通过 Python `issubclass` 实现智能类型安全分流：

```python
@api.on(TurnStart)          # 自动识别为 Event 子类 ➔ 注册到只读事件订阅者 (subscribers)
def handle_turn(event: TurnStart):
    print(f"Turn started: {event.iteration}")

@api.on(ToolCallHook)       # 自动识别为 Hook 类 ➔ 注册到 HookRegistry 拦截门禁
def audit_tool(hook: ToolCallHook) -> HookResult | None:
    if hook.tool_name == "bash" and "rm -rf /" in hook.args.get("command", ""):
        return HookResult(block=True, reason="Dangerous command blocked")
    return None
```
