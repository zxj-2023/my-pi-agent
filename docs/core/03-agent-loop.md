# 单层 Agent 与纯函数微内核调度设计规范 (`my_agent_core.agent` & `loop`)

- **定位**：Agent 执行中枢、ReAct 微内核状态机与转录本自愈引擎 (`packages/my-agent-core/src/my_agent_core/agent.py`, `loop.py`, `tool_history.py`)
- **核心组件**：
  - `run_agent_loop`：无状态纯函数异步生成器微内核（约 110 行优雅状态机）
  - `_assistant_turn` & `_execute_tools_turn`：专职子生成器车间
  - `_provider_context` & `repair_tool_history`：上下文前置清洗与转录本自愈引擎
  - `Agent`：轻量有状态外壳（`AgentHarness`），对外暴露 `prompt_stream` 一等公民事件流与 `subscribe` 观察者接口
- **关键 API**：`agent.prompt_stream(user_input)`, `agent.run(user_input)`, `agent.subscribe(listener)`, `agent.steer(msg)`, `agent.follow_up(msg)`, `agent.abort()`

---

## 一、架构设计演进：从单体上帝类到 Tau 风格分治微内核

在早期版本中，`Agent` 类是一个集状态持有、事件分发、双通道广播、网络请求、多协议适配、参数序列化与工具执行于一体的“大泥球”。

在对标 **Tau (`tau-ai`)** 与 **Pi (`@earendil-works/pi-coding-agent`)** 的架构重塑后，调度体系实现了清晰的分层分治：

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│ 【外壳层: Agent (AgentHarness)】                                            │
│   • 负责组件组装（Session、LLM、ToolRegistry、Hooks、ContextManager）       │
│   • 持有内存会话与消息队列（Steering / Follow-up 队列）                      │
│   • 暴露 prompt_stream(user_input) 异步事件生成器与 subscribe() 观察者      │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │ 消费生成器事件流
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 【微内核层: run_agent_loop (loop.py)】(~110 行无状态纯函数异步生成器)       │
│                                                                             │
│ while True: (外层 Follow-up 宏观任务流转)                                   │
│   while has_more_tools or pending_messages: (内层 ReAct 循环)               │
│     1. 清洗并注入 pending_messages (Steering 纠偏)                          │
│     2. yield TurnStart(iteration)                                           │
│     3. 上下文准备 _ctx.prepare() ➔ Hook 3: BeforeModelCallHook (零污染视图) │
│     4. 委托模型车间: async for ev in _assistant_turn(...)                    │
│     5. 委托工具车间: async for ev in _execute_tools_turn(...)                │
│     6. 严格闭环当前轮次: yield TurnEnd(...)                                 │
│     7. 收割 steer 即时转向                                                  │
│   收割 follow_up 追问                                                       │
│ yield AgentEnd(...)                                                         │
└──────────────┬───────────────────────────────┬──────────────────────────────┘
               │ 委托子生成器                  │ 委托子生成器
               ▼                               ▼
┌──────────────────────────────┐ ┌────────────────────────────────────────────┐
│ 车间 ①: _assistant_turn      │ │ 车间 ②: _execute_tools_turn                │
│ (模型流式推理车间)           │ │ (工具批处理执行车间)                       │
│ • 首 Chunk 发射 MessageStart │ │ • 阶段 A (Preflight):                      │
│ • 逐字 yield MessageUpdate   │ │   按声明顺序率先广播 ToolExecutionStart    │
│ • 接收完整 Response 实体     │ │   调用 before_tool_call (ToolCallHook)     │
│ • 发射 MessageEnd 终态定型   │ │ • 阶段 B (Execution): 并发批执行工具 (dict)│
│ • 取消/异常时优雅闭环        │ │ • 阶段 C (Completion):                     │
│                              │ │   调用 after_tool_call (ToolResultHook)    │
│                              │ │   广播 ToolExecutionEnd                    │
│                              │ │   按序发射 role="tool" 的 MessageStart/End │
│                              │ │ • 阶段 D (Self-Healing):                   │
│                              │ │   中途取消自动补齐断头调用                 │
└──────────────────────────────┘ └────────────────────────────────────────────┘
```

---

## 二、微内核子生成器分治机制 (`loop.py`)

### 1. 专职模型推理车间：`_assistant_turn`

- **流式增量与状态定型**：
  首个 Chunk 到达时发射 `MessageStart(assistant)`；在流式生成中逐字发射 `MessageUpdate` 驱动终端打字机；流式结束时直接接收模型边界层交付的完整 `Response` 实体，发射 `MessageEnd` 定型。
- **取消与异常 Never-Throw**：
  若检测到 `CancellationToken.is_cancelled()`，优雅中断并标记 `stop_reason="cancelled"`；模型报错时封装为错误消息，保证上层轮次能安全闭环。

### 2. 专职工具执行车间：`_execute_tools_turn`

- **Pi 时序 Preflight 保证**：
  在审批与执行前，**率先按 source order 发射 `ToolExecutionStart`**，使 UI 能够毫秒级渲染工具准备运行状态。
- **原生结构化字典派发**：
  直接消费 `ToolCall.args: dict`，调用 `before_tool_call` 审批改参，并直接将字典提交给 `ToolRegistry.execute_batch` 执行，**全程 0 行 JSON 编解码**。
- **断头调用集中自愈**：
  若工具执行前夕或执行中途收到取消信号，通过 `_synthesize_interrupted_tool_calls` 为所有未执行的调用自动生成 `Tool call interrupted by user` 错误结果，绝不产生悬空断头调用。

---

## 三、上下文前置清洗与转录本自愈 (`tool_history.py`)

大模型提供商（如 OpenAI、Anthropic）对上下文格式有着极其严苛的校验规则：

- **禁止悬空断头调用**：Assistant 发起了 `tool_calls`，后面必须紧随对应 ID 的 `tool` 消息，否则直接报 API 400；
- **禁止孤儿结果**：没有对应 `tool_calls` 的 `role="tool"` 消息会被拒绝；
- **禁止空失败轮次**：以 `stop_reason="error"` 结尾且 `content=""` 的中断消息会导致上下文语法错误。

### 1. `_provider_context` 前置清洗

在每次向大模型发送消息列表前，微内核自动执行 `_provider_context(messages)`：

1. 剔除无正文且以异常中断结尾的终端 assistant 失败轮次；
2. 串联 `repair_tool_history` 进行转录本拓扑自愈。

### 2. `repair_tool_history` 三阶段确定性状态机

```text
原始乱序/断头消息
       │
       ▼ Phase 1 (建立索引): 收集所有 Assistant 节点的 tool_calls 声明
       ▼ Phase 2 (孤儿与重复清洗): 从后往前扫描，丢弃无主结果与重复结果
       ▼ Phase 3 (重排与断头补齐): 严格按 Assistant 声明顺序重排 Tool 消息，
                                  对缺失结果的断头调用自动合成
                                  role="tool", content="Tool call interrupted by user"
       │
       ▼
格式 100% 严谨合法的消息历史 (免疫任何 LLM API 400 校验死锁)
```

---

## 四、外壳装配：`Agent` (`AgentHarness`)

`Agent` 类蜕变为轻量外壳，负责生命周期资源的组装与管理：

### 1. 一等公民事件流：`prompt_stream`

调用方可以直接以异步迭代器的方式消费微内核发射的每一个纯只读事件：

```python
agent = Agent(llm=llm, tools=[...])

async for event in agent.prompt_stream("帮我重构这个模块"):
    if isinstance(event, MessageUpdate):
        print(event.chunk.content, end="", flush=True)
    elif isinstance(event, ToolExecutionStart):
        print(f"\n[Tool Start] {event.tool_name} with {event.args}")
    elif isinstance(event, AgentEnd):
        print(f"\n[Finished] Total iterations: {event.iterations}")
```

### 2. 观察者模式：`subscribe`

支持向 Agent 注册只读监听函数：

```python
agent.subscribe(lambda event: print(f"Audit log: {type(event).__name__}"))
```

### 3. 便利门面：`run`

经典阻塞式调用，内部纯粹消费 `prompt_stream` 并在 `AgentEnd` 时提取 `final_text` 返回：

```python
async def run(self, user_input: str) -> str | None:
    final_text = None
    async for event in self.prompt_stream(user_input):
        if isinstance(event, AgentEnd):
            final_text = event.final_text
    return final_text
```

### 4. 协作式中断：`abort`

通过 `agent.abort()` 触发内部 `CancellationToken.cancel()`，流式推理与工具执行车间将在下一个检查点安全终止，并完成断头结果自动合成与原子落盘，**绝不向 Session 写入半截脏数据**。
