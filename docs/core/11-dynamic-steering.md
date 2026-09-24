# 动态干预机制与两层循环设计规范 (`my_agent_core.message_queue`)

- **定位**：Pi 风格即时转向（Steer）与排队追问（Follow-up）双层调度引擎 (`packages/my-agent-core/src/my_agent_core/message_queue.py`)
- **核心类**：`MessageType`, `QueuedMessage`, `MessageQueue`
- **主要实现**：`message_queue.py`, `agent.py`

---

## 一、架构设计与定位

传统 Agent 执行是一个封闭不可中断的单层循环，难以应对外部实时纠偏或任务无缝衔接。
本模块对标 Pi 与 pig-mono，实现了 **「动态干预消息队列（`MessageQueue`） + 两层循环（Two-Level Loop）」** 架构：

- **内层循环（Inner ReAct Loop）**：驱动微观步骤推理与工具执行。在安全点消费 **`steer`** 即时转向指令，支持在工具批执行间隙或大模型输出阶段即时纠偏，不丢弃已有上下文；
- **外层循环（Outer Task Loop）**：驱动宏观任务生命周期。在当前任务自然结束（无工具调用且无 steering）的边界消费 **`follow_up`** 追问指令，自动无缝衔接下一段任务。

```text
                           Agent.run(user_input)
                                     │
                                     ▼
                     [UserInput & AgentStart 拦截点]
                                     │
                     pending_messages = [user_input]
                                     │
 ┌───────────────────────────────────▼────────────────────────────────────────┐
 │ 【外层循环 (Outer Loop)】: 驱动宏观任务生命周期与 Follow-up 队列           │
 │ while True:                                                                │
 │   has_more_tool_calls = True                                               │
 │                                                                            │
 │   ┌────────────────────────────────────────────────────────────────────┐   │
 │   │ 【内层循环 (Inner Loop)】: 驱动微观 ReAct 步骤与 Steer 即时转向    │   │
 │   │ while has_more_tool_calls or len(pending_messages) > 0:            │   │
 │   │                                                                    │   │
 │   │   1. 【安全点 ① 注入消息】:                                        │   │
 │   │      遍历 pending_messages ➔ 写入 session 树 ➔ 追加 self.messages │   │
 │   │      pending_messages.clear()                                      │   │
 │   │                                                                    │   │
 │   │   2. 【上下文与推理】:                                             │   │
 │   │      view = ctx.prepare(messages) ➔ BeforeModelCall 拦截           │   │
 │   │      assistant_msg, tool_calls = await llm.achat_stream(view)      │   │
 │   │      写入 session 树 ➔ 追加 self.messages                          │   │
 │   │                                                                    │   │
 │   │   3. 【工具执行与分流】:                                           │   │
 │   │      if tool_calls:                                                │   │
 │   │          tool_results = await registry.execute_batch(tool_calls)   │   │
 │   │          写入 session 树 ➔ 追加 self.messages                      │   │
 │   │          has_more_tool_calls = True                                │   │
 │   │      else:                                                         │   │
 │   │          has_more_tool_calls = False                               │   │
 │   │          final_text = assistant_msg.content                        │   │
 │   │                                                                    │   │
 │   │   4. 【安全点 ② & ③ 检查 Steer 转向】:                             │   │
 │   │      if message_queue.has_steering():                              │   │
 │   │          pending_messages = message_queue.get_steering_messages()  │   │
 │   │          # 关键: 即使 has_more_tool_calls=False,                    │   │
 │   │          # 因 pending_messages > 0, 内层循环不退出, 继续 ReAct!    │   │
 │   │                                                                    │   │
 │   │   5. TurnEnd 事件派发                                              │   │
 │   └────────────────────────────────────────────────────────────────────┘   │
 │                                                                            │
 │   # 内层循环自然结束 (无 tool_calls 且无 steering)                         │
 │   if message_queue.has_followup():                                         │
 │       pending_messages = message_queue.get_followup_messages()             │
 │       continue  # 开启外层循环新一轮，无缝驱动 Follow-up 任务!             │
 │                                                                            │
 │   break # 队列全清空，任务彻底完成                                         │
 └───────────────────────────────────┬────────────────────────────────────────┘
                                     │
                                     ▼
                            [AgentEnd 事件派发]
                            return final_text
```

---

## 二、核心类与数据结构

### 1. `MessageType` 与 `QueuedMessage`

```python
class MessageType(str, Enum):
    STEERING = "steering"  # 内层循环即时转向（安全点打断）
    FOLLOWUP = "followup"  # 外层循环排队追问（任务完成后驱动）

@dataclass
class QueuedMessage:
    content: str
    type: MessageType
    created_at: float = field(default_factory=time.time)
```

### 2. `MessageQueue` 队列管理

- **双模消费机制**：
  - `steering_mode`：`"one-at-a-time"`（默认，单步纠偏）或 `"all"`（一次性全部注入）；
  - `followup_mode`：`"one-at-a-time"`（默认，逐个任务推进）或 `"all"`。
- **公共状态探针**：
  - `add_steering(msg)` / `add_followup(msg)`
  - `has_steering()` / `has_followup()`
  - `get_steering_messages()` / `get_followup_messages()`
  - `get_status() -> str`（如 `"Queued: 1 steering, 2 follow-up"`）
  - `clear()`

---

## 三、三大安全点与设计不变式

1. **安全点 ①：Turn 起点原子落盘**：
   - 无论是初始 Prompt、Steer 转向还是 Follow-up 追问，在送入模型前**必须统一调用 `session.add_message("user", ...)` 原子写盘**，保持会话分支回溯 100% 确定性。
2. **安全点 ②：工具批执行完毕后的 Steer 拦截**：
   - 工具执行完后检查 `has_steering()`，将转向指令与工具结果一同在下一轮提示词中呈现给模型。
3. **安全点 ③：无工具文本输出时的 Steer 拦截（防止早退）**：
   - 当大模型生成了最终答复文本（无 tool_calls），但流式输出期间注入了 Steer，内层循环**不退出**，直接把 Steer 指令追加进上下文并 `continue` 开启下一轮推理。
4. **取消隔离（`abort()` 保证）**：
   - 调用 `agent.abort()` 时立即清空 `message_queue` 并置 `_aborted = True`，立即跳出双层循环，绝不执行遗留的 Follow-up 追问。
5. **首轮工具执行完毕后交付契约（Turn-Boundary Delivery Contract）**：
   - 若初始已传入 Prompts 任务，首轮推理严格仅消费初始任务；
   - 在任务刚触发到首轮工具执行期间进入队列的转向指令，**严格在首轮工具全部执行完毕后、次轮推理发起前交付**。
   - 彻底避免在第 1 轮将初始 Prompt 与 Steering 消息并列塞入模型导致的“复合长句”误读歧义。

---

## 四、前端 TUI 待发区呈现规范 (`interactive-mode.ts`)

为了 100% 对齐 Pi 原厂终端交互规范，Steering 与 Follow-up 在 TUI 表现层具备统一的视口对接与按键拦截能力：

1. **运行期回车默认转向 (Smart Steer Routing)**：
   - 当智能体处于忙碌/流式生成或工具执行期间（`isStreaming || isWorking || isSubmitting`），用户在输入框键入**任何普通文本**或 `/steer <msg>` 并敲回车，**默认 100% 作为 Steering 即时插话**送入内核；
   - 处于空闲态时按回车直接发起常规提问。
2. **全平台快捷追问 (`Ctrl+Q` Follow-up)**：
   - **空闲态**：按下 `Ctrl+Q` 行为等价于直接按回车，立即提交执行；
   - **运行态**：按下 `Ctrl+Q` 自动将当前输入框内容提取为 **Follow-up 排队追问**，追加至编辑器历史并清空输入框，调用 `bridge.followUp(...)` 推入内核队列，等待当前宏观任务彻底完成后自动顺延执行。
3. **输入框上方待发区呈现 (Pending Dock)**：
   - 回车或 `Ctrl+Q` 后输入框立即清空，在输入框上方挂载灰暗色（`theme.dim`）排队指示：
     ```text
     Steering: 暂停
     Follow-up: 随后构建项目
       ↳ Alt+Q to edit all queued messages
     ```
   - 在当前工具批次未结束前，插话**停留在待发区，不抢先挂载到主聊天历史**，给用户清晰的交付预期；
   - 当内核完成当前轮工具并在次轮通过 `message_start(role="user")` 正式交付时，自动从 Pending 区移除，并无感移入主聊天记录区。
4. **全量召回编辑 (`Alt+Q` / `Alt+Up`) 与内核队列清空**：
   - 处于待发状态的所有消息（无论是 Steering 还是 Follow-up）支持按 `Alt+Q` 或 `Alt+Up` 一键全量合并弹回输入框（多条以双换行 `\n\n` 拼接）；
   - 前端立即清空本地待发列表，并同步发起 RPC `clear_queue`，确保内核底层队列同步清空，杜绝已撤回消息滞后误执行。
5. **Escape 中断联动回填**：
   - 在运行态按下 `Esc` 中断时，除了向内核发送 `abort` 停止流式输出外，自动触发全量召回，将未送出的待发排队消息无缝还原至输入框，便于用户即刻修改并重发。

---

## 五、内核与 RPC 队列接口规范

- `MessageQueue.clear() -> list[QueuedMessage]`：清空并返回当前排队消息；
- `Agent.clear_queue() -> list[QueuedMessage]`：代理清空微内核排队消息；
- `CodingAgent.clear_queue() -> list[Any]`：业务外观层清空排队消息；
- RPC 方法 `clear_queue`：
  - 请求：`{"jsonrpc": "2.0", "id": 1, "method": "clear_queue", "params": {}}`
  - 响应：`{"jsonrpc": "2.0", "id": 1, "result": {"cleared": true, "count": 2}}`

