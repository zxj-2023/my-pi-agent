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

### 2. 专职工具执行车间：`_execute_tools_turn`（工业级七阶段流水线）

严格对齐 Pi 官方架构契约与 Tau 微内核设计，工具执行划分为七个确定性阶段：

1. **阶段 1：输出截断防御检查 (`_fail_tool_calls_from_truncated_message`)**：
   当检测到模型输出触达 Token 上限被截断（`stop_reason == "length"`）时，断然拒绝执行任何工具，防止流式 salvage 拼出残缺参数导致代码写崩或命令腰斩。自动合成警告错误并回传模型引导重新完整发起调用。
2. **阶段 2：Preflight 广播 (`ToolExecutionStart`)**：
   在审批与执行前，**率先按 source order 广播 `ToolExecutionStart`**，使 UI 能够毫秒级渲染工具准备运行状态。
3. **阶段 3：串并行决策网关 (`ToolRegistry.execute_batch`)**：
   悲观读写分流：全只读安全工具（`is_parallel_safe=True`）启用 `asyncio.gather` 全并发加速；只要包含任一写入/串行工具，整批退化为保序串行执行，防止因果时序倒置。
4. **阶段 4：前置审查审批与改参 (`before_tool_call`)**：
   通过 `_coerce_tool_call` 归一化入参，调用 `before_tool_call` 审批，支持安全阻断（`block`）与参数就地热修改（`updated_args`）。
5. **阶段 5：并发批执行与流式进度回传 (`ToolExecutionUpdate`)**：
   采用 `asyncio.Queue` 与 `loop.call_soon_threadsafe` 跨线程安全桥接，支持长耗时工具（如 Bash 编译或子代理）在运行态向外广播累积快照（Cumulative Snapshot）。生命周期锁存（`accepting_updates`）确保工具返回后丢弃迟到回调。
6. **阶段 6：后置改写与单工具终态广播 (`after_tool_call` & `ToolExecutionEnd`)**：
   调用 `after_tool_call` 支持结果脱敏与改写（`updated_result`），广播包含 `terminate` 状态的 `ToolExecutionEnd`。
7. **阶段 7：转录本保序归档与批量优雅熔断 (`MessageStart/End` & `should_terminate`)**：
   无论并发执行完成顺序如何，回传大模型的 `role="tool"` 消息严格按 Assistant 原始 Source Order 恢复排布。若批次中任一工具（`any()` 语义）或 Hook 返回 `terminate=True`，立即终结 ReAct 循环，保全 `final_text` 并正常交付结果。

### 3. 阶段 5 核心攻坚：生产者-消费者管道与三大技术死结破解

在实现第 5 阶段（并发执行与实时流式进度回传）时，微内核面临了三个看似不可调和的技术冲突：

```text
【冲突 1】异步生成器 vs 并发批量执行
  • 需求 A：多个工具必须并发跑（比如同时读 3 个文件），底层用的是 asyncio.gather(...)；
  • 需求 B：_execute_tools_turn 是一个生成器，必须一有进度就立刻 yield 出去。
  • 痛点：在 asyncio.gather 的深处是不能直接向外层生成器 yield 的！

【冲突 2】主事件循环 vs 工作线程池
  • 需求 A：很多工具是同步的（如普通的 Python 函数、调用操作系统的 bash），必须扔进线程池
           asyncio.to_thread 跑，不能卡死主线程；
  • 痛点：Python 的异步队列 asyncio.Queue 是严格单线程的，工作线程直接碰队列就会崩溃闪退！

【冲突 3】实时流式读取 vs 任务结束防死锁
  • 需求 A：前台必须一直监听队列，只要有日志就拿出来；
  • 痛点：前台怎么知道后台什么时候“全部跑完了”？如果盲目等，后台跑完后前台就会永久卡死（死锁）。
```

#### 破局方案：前后台解耦的“单向传送带”管道模型

```text
┌──【后台 Producer: runner 异步任务】──┐
│                                       │
│  并发执行 tool_1, tool_2, tool_3 ...   │
│                   │                   │
│                   ▼ 产生进度          │
│      on_update("50% complete")        │
│                   │                   │
│                   ▼                   │
│   safe_put_update (线程安全路由)       │
│     ├─ 主线程: queue.put_nowait()     │
│     └─ 工作线程: call_soon_threadsafe │
│                   │                   │
│                   ▼ 写入              │
└─────────────> ┌────────┐ <────────────┘
                │ 异步队列│
                │ queue  │
                └────────┘
                    │
                    ▼ 读取
┌──【前台 Consumer: 生成器主循环】────┐
│                                       │
│  while True:                          │
│      item = await queue.get()         │
│      if item is _SENTINEL: break      │
│      yield item  (实时推给前端 UI!)    │
│                                       │
└───────────────────────────────────────┘
```

- **前台（消费端）**：不直接管具体的工具怎么跑，只负责死盯着一条专用的异步传送带（`Queue`）。只要传送带上有日志，就捡起来 `yield` 给外部界面；
- **后台（生产端）**：把工具的并发批处理打包成一个独立的后台异步任务（`Task`），各个工具在后台并发执行。工具有了进度，就往传送带上放；
- **桥梁（线程安全网关）**：在工作线程和传送带之间架设一个跨线程调度阀（`loop.call_soon_threadsafe`），让工作线程安全地把包裹递给主线程；
- **停机（哨兵机制）**：后台所有活干完了，往传送带最后扔一个独一无二的“打烊牌”（`_SENTINEL = object()`），前台一见此牌立刻收工，绝不死锁。

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
