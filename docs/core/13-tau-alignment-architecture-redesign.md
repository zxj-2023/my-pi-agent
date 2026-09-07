# Tau 对齐与核心框架深度重构设计文档

(Tau Alignment & Deep Module Architecture Redesign)

- **日期**：2026-08-30
- **目标代码库**：`packages/my-agent-core`、`packages/my-coding-agent`
- **对标基准**：`D:\code\python\agent-program\tau\src\tau_agent` 及 Pi 官方微内核架构
- **设计哲学**：基于 `codebase-design` 深度模块化原则（Small Interface, Deep Implementation, Clean Seams）

---

## 一、背景与重构动机 (Background & Motivation)

### 1.1 现状与架构债务分析

目前 `my-pi-agent` 已经完成了 15 个阶段的迭代演进，具备了极其丰富的能力（树状 Session、4 层上下文压缩、两层循环、ToolRegistry 因果并发、TaskStore、BackgroundRunner 等），全量 304 项离线测试全绿。

但在快速演进过程中，框架核心层积累了以下三处**架构债务与代码坏味道**：

1. **`Agent` 类膨胀为“上帝类”（God Object）**：
   - `packages/my-agent-core/src/my_agent_core/agent.py` 目前达到 600 多行，构造函数拥有 18 个参数；
   - 它一人身兼数职：既负责依赖注入组装（Memory、TaskStore、Plugin、Skill、Subagent、Extension、BackgroundRunner），又负责状态维护（messages、queues），还内联着复杂的两层 ReAct 循环；
   - 违反了单一职责原则，模块界面（Interface）过大，接缝（Seam）模糊。

2. **缺少“断头工具调用”自愈机制（Transcript Fragility）**：
   - 当用户按 `Ctrl+C` 中止任务、后台命令异常、或模型输出截断时，对话历史中可能残留只有 `ToolCall` 而无对应 `ToolResultMessage` 的悬空条目；
   - 再次调用 OpenAI / Anthropic API 时会直接触发 400 Bad Request（`tool_use without tool_result`），导致会话损坏；
   - 目前缺乏像 Tau `tool_history.py` 那样确定性的转录本自动修复（Self-healing）能力。

3. **`session.py` 职责过载（Monolithic File）**：
   - 单个 `session.py`（450 行）同时揉杂了数据实体（`SessionEntry`）、DAG 树算法（`SessionTree`）、文件原子落盘（`fsync + replace`）以及仓库管理（`SessionStore`），缺乏存储抽象，测试必须依赖真实临时文件。

4. **事件流未作为一等公民（Event Stream as First-Class Citizen）**：
   - `agent.run(prompt)` 当前直接返回 `final_text: str`，中间事件依赖侧路的 `HookRegistry` 监听；
   - 外部调用者（如 CLI 打字机、TUI 视图、Websocket）无法像消费标准异步迭代器那样自然地 `async for event in agent.run_stream(...)`。

### 1.2 对标 Tau 的重构愿景

借鉴 `tau_agent` 的优雅设计：

- 将 ReAct 循环抽离为**纯函数无状态微内核 (`run_agent_loop`)**；
- 将 `Agent` 瘦身为**轻量有状态外壳 (`AgentHarness`)**，对外暴露极窄接口；
- 引入 **`tool_history.py`**，赋予会话毫秒级自愈与防 API 400 报错的坚固护盾；
- 将 `session.py` 领域下沉为清晰的 **`session/` 子包**，拆分数据模型、纯树算法、状态投影与存储驱动（支持纯内存存储快速单测）；
- 升级消息与工具协议，支持**多块级内容（Thinking/Image/ToolCall）**与**结构化细节隔离（`details`）**；
- 引入 **`_provider_context`** 与 **`tool_history.py`** 双重保护，过滤空失败轮次并自动缝合断头工具调用。

---

## 二、目标架构蓝图与职责分工 (Target Architecture)

重构后的核心层将形成分明的 5 层深度模块结构：

```text
 ┌─────────────────────────────────────────────────────────────────────────────────────────┐
 │                                   产品与应用层 (my-coding-agent)                         │
 │   • 负责装配具体的业务：4大文件工具、MCP客户端、TaskStore、BackgroundRunner、CLI交互     │
 └────────────────────────────────────────────┬────────────────────────────────────────────┘
                                              │ 依赖注入 / 插件挂载
                                              ▼
 ┌─────────────────────────────────────────────────────────────────────────────────────────┐
 │                      核心有状态外壳 (Agent / AgentHarness)                               │
 │   • 极窄对外接口：prompt() / continue_() / steer() / follow_up() / cancel() / subscribe()│
 │   • 职责：持有纯对话状态、消息队列缓冲、管理事件订阅者，通过 SessionState 无锁投影状态  │
 └─────────────┬──────────────────────────────┴─────────────────────────────┬──────────────┘
               │                                                            │
               ▼ 驱动                                                       ▼ 修复
 ┌───────────────────────────────────────────┐ ┌───────────────────────────────────────────┐
 │  纯函数无状态微内核 (run_agent_loop)      │ │  对话历史自愈引擎 (tool_history.py)       │
 │   • 纯异步生成器:                         │ │   • repair_tool_history(messages)         │
 │     run_agent_loop(...) ->                │ │   • 三阶段状态机：预留配对/补齐/去孤儿    │
 │     AsyncIterator[AgentEvent]             │ │   • _provider_context 过滤空失败轮次      │
 │   • 细粒度 Provider 流式事件解耦          │ │   • portable_tool_call_id 跨模型重放      │
 │   • 协作式取消信号 ToolCancellationToken  │ └───────────────────────────────────────────┘
 └─────────────────────┬─────────────────────┘
                       │ 读写会话
                       ▼
 ┌─────────────────────────────────────────────────────────────────────────────────────────┐
 │                          领域下沉的会话子系统 (session/)                                │
 │   • entries.py : 9 种强类型 SessionEntry 实体定义（Discriminated Union）                │
 │   • tree.py    : 纯内存 DAG 树遍历算法（祖先回溯、LCA 计算、防环路检测，零 I/O）        │
 │   • memory.py  : SessionState 纯函数不可变事件溯源折叠投影（无锁瞬态聚合）             │
 │   • storage.py : 纯异步只追加协议（SessionStorage: InMemoryStorage vs JsonlStorage）   │
 │   • jsonl.py   : 行级原子序列化、跨进程锁与未完成 .tmp 碎片自愈清理                     │
 └─────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 三、核心模块详细设计规格 (Module Specifications)

### 3.1 模块一：对话自愈引擎 (`my_agent_core/tool_history.py`) 与上下文前置清洗 (`_provider_context`)

#### 1. 核心定位

位于 LLM API 调用前置边界的纯函数深度模块。入参为原始消息元组，出参为合法无瑕疵的消息元组以及修复诊断报告。

#### 2. 三阶段确定性自愈算法规格 (`repair_tool_history`)

```python
@dataclass(frozen=True, slots=True)
class ToolHistoryRepair:
    messages: tuple[AgentMessage, ...]
    changed: bool = False
    synthesized_results: int = 0      # 补齐的悬空结果数
    dropped_orphan_results: int = 0   # 丢弃的孤儿结果数
    dropped_duplicate_results: int = 0# 丢弃的重复结果数
    reordered_results: int = 0        # 调整顺序的结果数

def repair_tool_history(messages: Sequence[AgentMessage]) -> ToolHistoryRepair:
    """保证每一条带有 tool_calls 的 Assistant 消息后，都紧跟且仅紧跟对应的 ToolResult。
    
    采用 Tau 三阶段状态机实现确定性修复：
    1. Phase 1 (就近预留配对):
       计算每个 tool_call 的期望位置 (message_index + call_offset)。若该位置恰为对应的
       ToolResult，立即将其预留。防止 LLM 复用同名 ID 时前面轮次错误抢夺后续正常结果；
    2. Phase 2 (贪心匹配或补齐中断):
       未就近配对的调用，优先在后续结果池中寻找真实结果；若池为空，自动合成中断结果：
       ToolResultMessage(tool_call_id=call.id, content=[TextContent(text="Tool call interrupted by user")], is_error=True)；
    3. Phase 2.5 (真实结果反超):
       若先前分配了合成中断，但后续发现同 ID 未使用的真实结果，回滚合成并优先采纳真实结果；
    4. Phase 3 (重建转录本、丢弃孤儿与重排):
       按严格紧邻原序重构消息链；未能匹配任何 ToolCall 的孤儿结果自动丢弃，重复结果自动剔除。
    """
```

#### 3. 空终端错误清洗规则 (`_provider_context`)

在送入模型前，微内核必须调用 `_provider_context` 剔除无正文的异常轮次：
```python
def _provider_context(messages: list[AgentMessage]) -> list[AgentMessage]:
    """过滤持久化诊断中的终端空失败轮次，并执行工具调用拓扑修复。"""
    replayable = tuple(
        m for m in messages
        if not (
            isinstance(m, AssistantMessage)
            and m.stop_reason in {"error", "aborted"}
            and not m.content
        )
    )
    return list(repair_tool_history(replayable).messages)
```
- **核心价值**：主流模型 API（OpenAI / Anthropic）对空 assistant 内容（`content: ""`）直接报 400 错误。此清洗既保留了磁盘中的失败诊断审计，又保证了发给模型的重放上下文 100% 满足 API 严格交替格式。

#### 4. 跨模型重放防御（`portable_tool_call_id`）
引入 ID 规范化函数，利用 SHA-256 将任意不规则或超长 ID 转换为满足 `^[A-Za-z0-9_-]{1,64}$` 的便携格式，消除会话从 OpenAI 切换至 Anthropic 时的格式报错。

---

### 3.2 模块二：纯函数 ReAct 微内核 (`my_agent_core/loop.py`)

#### 1. 核心定位

彻底将 ReAct 循环逻辑从类属性中解放出来，变成一个**纯粹、无状态、可被任何宿主直接调用的异步生成器函数**。

#### 2. 函数签名与参数接缝 (Seam)

```python
async def run_agent_loop(
    *,
    llm: LLM,
    model: str | None,
    system: str,
    messages: list[AgentMessage],
    tools: ToolRegistry,
    context_manager: ContextManager,
    prompts: Sequence[AgentMessage] = (),
    max_turns: int | None = None,
    signal: CancellationToken | None = None,
    get_steering_messages: Callable[[], Sequence[AgentMessage]] | None = None,
    get_follow_up_messages: Callable[[], Sequence[AgentMessage]] | None = None,
) -> AsyncIterator[AgentEvent]:
    """执行 ReAct 双层事件循环，逐一 yield 出生命周期事件。"""
```

#### 3. 内部循环控制流与安全流水线（对齐 Pi / Tau）

1. **输入初始化**：将 `prompts` 追加进 `messages`，发射 `AgentStart` 与 `TurnStart`；
2. **微观 ReAct 内层循环** (`while has_more_tools or pending:`):
   - **前置清洗**：`clean_messages = _provider_context(messages)`（剥离空中断消息并自动修复断头 ToolCall）；
   - **准备临时视图**：`view = await context_manager.prepare(clean_messages)`；
   - **模型决策点**：发射 `BeforeModelCall` 并允许拦截改写；
   - **细粒度 Provider 事件流驱动**：
     调用 `llm.stream_events`，实时分流捕获：
     - `ThinkingDeltaEvent` $\to$ 发射 `MessageUpdate(thinking_delta)`（前端可流式折叠显示思考过程）；
     - `TextDeltaEvent` $\to$ 发射 `MessageUpdate(text_delta)`（流式打字机）；
     - `ToolCallDeltaEvent` $\to$ 实时累加工具参数，并可选发射 `ToolCallStart` 提示；
   - **工具执行与细粒度协作取消**：
     若模型发起工具调用：
     - 检查 `signal.is_cancelled()`；若已取消，合成中断结果并退出；
     - 通过 `ToolUpdateCallback` 闭包隔离（`accepting = False` 防迟滞竞争）支持长命令边执行边吐出增量更新（`ToolExecutionUpdateEvent`）；
     - 执行工具调用，捕获多模态内容与 `details` 结构化诊断；
     - 发射 `ToolExecutionEnd`；
     - 发射成对的 `TurnEnd`；
     - 检查并消费 `get_steering_messages()`；
   - 若模型未发起工具调用：
     - 发射成对的 `TurnEnd`；
     - 检查并消费 `get_steering_messages()`（若有，继续转内层循环；若无，退出内层循环）；
3. **宏观自收割外层循环** (`while True:`):
   - 检查 `get_follow_up_messages()`；
   - 若有待处理的后台通知或追问，将其转化为输入，`continue` 开启下一轮；
   - 若队列全清空，退出大循环，发射 `AgentEnd`。

---

### 3.3 模块三：有状态外壳与门面 (`my_agent_core/agent.py` 瘦身)

#### 1. 核心定位

从“什么都管的上帝类”，转变为**“高内聚低耦合的 Reusable Harness”**。

#### 2. 对外 API 契约（保持 100% 向后兼容）

```python
class Agent:
    """轻量有状态 Agent 宿主外壳。"""

    def __init__(
        self,
        llm: LLM,
        session: Session,
        tools: list[Tool] | ToolRegistry,
        system_prompt: str | None = None,
        context_budget: int | None = None,
        max_iterations: int | None = None,
        hooks: list[tuple[type[Event], Callable]] | None = None,
    ):
        ...

    # ── 核心驱动：同时支持生成器与阻塞式便利 API ─────────────
    
    # 方式 A：现代化事件流生成器（面向 TUI / CLI 打字机 / 前端）
    async def prompt_stream(self, prompt: str) -> AsyncIterator[AgentEvent]:
        """流式运行并实时产生事件流。"""

    # 方式 B：经典向后兼容 API（面向现有单测与简单脚本）
    async def run(self, prompt: str) -> str:
        """运行一轮并返回最终文本结果（内部消费 prompt_stream）。"""

    # ── 状态与干预控制 ──────────────────────────────────────
    def steer(self, message: str) -> None: ...
    def follow_up(self, message: str) -> None: ...
    def abort(self) -> None: ...
    def subscribe(self, listener: Callable[[AgentEvent], None]) -> Callable[[], None]: ...
```

#### 3. 业务子系统的解耦策略

- `task_store`、`memory_store` 等不再作为 `Agent.__init__` 的强制依赖；
- 业务系统作为**外置 Adapter / Extension**，在构造完成后通过工具注册与 Hook 挂载（通过统一的组装器或工厂函数提供）；
- `my-coding-agent` 的 `CodingAgent` 作为顶层组装者，对外提供“开箱即用”的全装配体验，而底层的 `Agent` 保持纯洁如白纸。

---

### 3.4 模块四：会话存储子系统 (`my_agent_core/session/`)

#### 1. 拆解单文件 `session.py` 为 5 大专职模块

```text
packages/my-agent-core/src/my_agent_core/session/
├── __init__.py           # 统一导出 Session, SessionTree, SessionEntry, SessionStorage
├── entries.py            # 9 种强类型 SessionEntry 实体（Discriminated Union）
├── tree.py               # 纯内存树算法（LCA 共同祖先、路径回溯、防环路检测，零 I/O）
├── memory.py             # SessionState 纯函数折叠聚合器（事件溯源不可变投影）
├── storage.py            # 纯异步只追加存储协议（InMemorySessionStorage / JsonlSessionStorage）
└── jsonl.py              # 行级编解码、跨进程读写锁与未提交 .tmp 碎片自愈
```

#### 2. 9 种多态条目类型体系 (`entries.py`)

摒弃脆弱的 `lines[0]` Header 字典，改用标准的 Pydantic 判别联合体：
- `SessionInfoEntry`: 记录会话元数据（`cwd`, `title`, `created_at`），作为流首项；
- `MessageEntry`: 包装 `AgentMessage`；
- `ModelChangeEntry`: 记录模型变更；
- `ThinkingLevelChangeEntry`: 记录推理思考等级调整；
- `CompactionEntry`: 记录压缩覆盖的条目 ID 清单与摘要；
- `BranchSummaryEntry`: 分支折叠摘要；
- `LabelEntry`: 用户书签检查点；
- `LeafEntry`: 指向当前分支活动叶节点的指针（分支切换仅需追加一条 LeafEntry，零文件重写）；
- `CustomEntry`: `namespace: str` + `data: dict`，为扩展与遥测提供隔离槽位。

#### 3. 内存状态纯函数折叠投影 (`memory.py`)

```python
@dataclass(frozen=True, slots=True)
class SessionState:
    messages: tuple[AgentMessage, ...]
    model: str | None
    provider: str | None
    thinking_level: str | None
    label: str | None
    active_leaf_id: str | None

    @classmethod
    def from_entries(cls, entries: Sequence[SessionEntry], leaf_id: str | None = None) -> SessionState:
        """纯函数折叠投影：沿根至 leaf_id 的路径条目无锁计算出最新运行时状态。"""
```

#### 4. 纯异步只追加存储契约 (`storage.py`)

```python
class SessionStorage(Protocol):
    async def append(self, entry: SessionEntry) -> None: ...
    async def append_batch(self, entries: Sequence[SessionEntry]) -> None: ...
    async def read_all(self) -> list[SessionEntry]: ...
```
- 彻底废除全量重写 `rewrite_history`，保证“历史发生即不可变”；
- `InMemorySessionStorage`：纯内存字典存储，单测完全脱离文件系统，速度提升 10 倍且零碎片；
- `JsonlSessionStorage`：配合 `.{name}.lock` 跨进程锁与 `_remove_incomplete_temp()` 自动清理崩溃残留碎片。

---

### 3.5 模块五：工具协议与执行上下文升级 (`my_agent_core/tools/`)

#### 1. 多模态与结构化诊断隔离 (`AgentToolResult`)

```python
class AgentToolResult(BaseModel):
    content: list[TextContent | ImageContent] = Field(default_factory=list) # 发给模型的正文
    details: JSONValue = None             # 发给前端 TUI/CLI 的结构化诊断数据
    added_tool_names: list[str] | None = None # 动态新开放的工具集（触发动态 Token 计算）
    terminate: bool | None = None         # 提前终止本轮标记（如交互式提问 handoff）
```

#### 2. 工具级协作取消与状态流式更新

```python
class ToolExecutor(Protocol):
    async def __call__(
        self,
        tool_call_id: str,
        arguments: Mapping[str, Any],
        signal: ToolCancellationToken | None = None,
        on_update: ToolUpdateCallback | None = None,
    ) -> AgentToolResult: ...
```
- 长命令可在内部通过 `signal.is_cancelled()` 协同取消子进程树；
- 执行中可通过 `on_update(partial_result)` 流式回显中间日志，且由闭包 `accepting = False` 隔绝迟滞竞争。

#### 3. 前端展示解耦渲染器 (`ToolCallRenderer` & `ToolResultRenderer`)

- 工具内聚提供参数简写格式化与折叠/展开 Markdown 渲染；
- 单次渲染报错隔离机制（`_renderer_failures_reported`），前端永不因渲染异常崩溃。

---

### 3.6 模块六：消息模型与 Provider 事件流解耦 (`my-agent-llm`)

#### 1. 块级内容体系 (`ContentBlock`)

- `TextContent(type="text", text: str)`
- `ThinkingContent(type="thinking", thinking: str, signature: str | None)`
- `ImageContent(type="image", data: str, mime_type: str)`
- `ToolCall(type="toolCall", id: str, name: str, arguments: dict)`
- `AssistantMessage.content` 为多块有序列表，真实还原思考与调用的交替过程。

#### 2. Provider 流式细粒度事件流

统一 Provider 异步生成器标准事件输出：
- `ThinkingDeltaEvent(thinking_delta: str)`：思考过程流式推送；
- `TextDeltaEvent(text_delta: str)`：正文打字机推送；
- `ToolCallDeltaEvent(call_id, args_delta)`：工具参数实时组装提示；
- `ResponseTiming(time_to_first_output_ms, total_duration_ms)`：高精度首字与交互耗时监控。

---

## 四、渐进式重构路线图 (Implementation Roadmap)

为了保证“改动重大但步步为营、全量测试时刻保持绿灯”，整个重构划分为 **4 个独立里程碑**：

```text
 ┌─────────────────────────────────────────────────────────────────────────┐
 │ Milestone 1: 引入 tool_history.py 对话自愈机制                          │
 │   • 状态：零风险、零破坏现有逻辑                                        │
 │   • 产出：新增 tool_history.py + 单测（悬空缝合、孤儿去重、排序）        │
 │   • 收益：Agent 在 abort 后再启动 100% 免疫 API 400 报错                │
 │   • 估算耗时与影响面：新增 1 个小文件，扩充 1 个单测文件，老代码 0 影响  │
 └────────────────────────────────────┬────────────────────────────────────┘
                                      │
                                      ▼
 ┌─────────────────────────────────────────────────────────────────────────┐
 │ Milestone 2: session/ 目录结构领域下沉与存储抽象                        │
 │   • 状态：结构重构，保持 session.py 兼容导出别名                        │
 │   • 产出：拆分为 entries/tree/storage/jsonl，引入 InMemorySessionStorage│
 │   • 收益：树算法与磁盘 I/O 彻底解耦，单测可完全脱离物理文件             │
 │   • 保证：所有老 import 依然可用（通过 session/__init__.py 别名）       │
 └────────────────────────────────────┬────────────────────────────────────┘
                                      │
                                      ▼
 ┌─────────────────────────────────────────────────────────────────────────┐
 │ Milestone 3: 提炼 loop.py 纯函数微内核与 prompt_stream 事件流           │
 │   • 状态：核心调度器架构进化                                            │
 │   • 产出：提取 run_agent_loop，Agent.run 复用该循环并提供流式迭代器     │
 │   • 收益：循环逻辑纯函数化，外部可直接消费事件流                        │
 │   • 保证：agent.run(prompt) 签名不变，原有测试 100% 照常通过            │
 └────────────────────────────────────┬────────────────────────────────────┘
                                      │
                                      ▼
 ┌─────────────────────────────────────────────────────────────────────────┐
 │ Milestone 4: Agent 类瘦身与业务子系统装配解耦                           │
 │   • 状态：消除上帝类，清理 18 个入参构造函数                            │
 │   • 产出：Agent 瘦身为轻量 Harness，外围业务由 CodingAgent 负责组装    │
 │   • 收益：框架内核达到 Tau 级别的极致纯净与优雅                         │
 └─────────────────────────────────────────────────────────────────────────┘
```

---

## 五、质量与验收铁律 (Quality Invariants)

在推进任何一个步骤时，必须严格恪守以下质量铁律：

1. **测试全绿铁律（Never Break Tests）**：
   重构过程中的每一个提交，全仓库已有的 **304 个离线测试必须 100% 持续通过**，绝不允许功能倒退；
2. **向后兼容性保证（Backward Compatibility）**：
   现有公共 API（如 `await agent.run("...")`、`session.add_message(...)`）保持原有签名与行为，保证老脚本与已有应用零破坏；
3. **Never-Throw 异常隔离**：
   所有新增工具接口与历史自愈算法遵循 Never-Throw 原则，任何格式错误转化为自愈动作或结构化诊断；
4. **100% 离线测试驱动**：
   每一个新增的模块（`tool_history`、`storage`、`run_agent_loop`）必须配备专职的无外部依赖单测。
