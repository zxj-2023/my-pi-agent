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
- 将 `session.py` 领域下沉为清晰的 **`session/` 子包**，拆分数据模型、纯树算法与存储驱动（支持纯内存存储快速单测）。

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
 │   • 职责：持有纯对话状态、消息队列缓冲、管理事件订阅者，不包含复杂的业务组装逻辑        │
 └─────────────┬──────────────────────────────┴─────────────────────────────┬──────────────┘
               │                                                            │
               ▼ 驱动                                                       ▼ 修复
 ┌───────────────────────────────────────────┐ ┌───────────────────────────────────────────┐
 │  纯函数无状态微内核 (run_agent_loop)      │ │  对话历史自愈引擎 (tool_history.py)       │
 │   • 纯异步生成器:                         │ │   • repair_tool_history(messages)         │
 │     run_agent_loop(...) ->                │ │   • 自动缝合未闭合的 ToolCall             │
 │     AsyncIterator[AgentEvent]             │ │   • 丢弃孤儿结果、保序重排                 │
 │   • 纯状态机：只负责与模型交互、调工具、  │ │   • 保证发送给 LLM 的历史 100% 合法        │
 │     发射事件、两层循环换挡收割            │ └───────────────────────────────────────────┘
 └─────────────────────┬─────────────────────┘
                       │ 读写会话
                       ▼
 ┌─────────────────────────────────────────────────────────────────────────────────────────┐
 │                          领域下沉的会话子系统 (session/)                                │
 │   • entries.py : 强类型 SessionEntry 实体定义                                           │
 │   • tree.py    : 纯内存 DAG 树遍历算法（祖先回溯、LCA 计算，零 I/O）                    │
 │   • storage.py : 存储契约抽象（SessionStorage: InMemoryStorage vs JsonlStorage）       │
 │   • jsonl.py   : 行级原子序列化与反序列化                                               │
 └─────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 三、核心模块详细设计规格 (Module Specifications)

### 3.1 模块一：对话自愈引擎 (`my_agent_core/tool_history.py`)

#### 1. 核心定位

位于 LLM API 调用前置边界的纯函数深度模块。入参为原始消息元组，出参为合法无瑕疵的消息元组以及修复诊断报告。

#### 2. 接口规格

```python
@dataclass(frozen=True, slots=True)
class ToolHistoryRepair:
    messages: tuple[Message, ...]
    changed: bool = False
    synthesized_results: int = 0      # 补齐的悬空结果数
    dropped_orphan_results: int = 0   # 丢弃的孤儿结果数
    dropped_duplicate_results: int = 0# 丢弃的重复结果数
    reordered_results: int = 0        # 调整顺序的结果数

def repair_tool_history(messages: Sequence[Message]) -> ToolHistoryRepair:
    """保证每一条带有 tool_calls 的 Assistant 消息后，都紧跟且仅紧跟对应的 ToolResult。
    
    1. 悬空补齐：若 Assistant 发起了 call_1 但后续未找到 ToolResult，
       自动合成为：Message(role="tool", tool_call_id="call_1", content="Tool call interrupted by user")；
    2. 孤儿丢弃：若存在 tool_call_id 不匹配任何 Assistant tool_call 的 ToolResult，自动剔除；
    3. 保序重排：将位置颠倒的 ToolResult 移动至对应的 Assistant 之后紧邻位置。
    """
```

#### 3. 架构收益

- 彻底解决大模型在工具调用中途被 `abort()` 打断后，下一次启动报 API 400 的死穴；
- 赋予系统像 Erlang 般的“自愈（Self-healing）”韧性。

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
    messages: list[Message],
    tools: ToolRegistry,
    context_manager: ContextManager,
    prompts: Sequence[Message] = (),
    max_turns: int | None = None,
    signal: CancellationToken | None = None,
    get_steering_messages: Callable[[], Sequence[Message]] | None = None,
    get_follow_up_messages: Callable[[], Sequence[Message]] | None = None,
) -> AsyncIterator[AgentEvent]:
    """执行 ReAct 双层事件循环，逐一 yield 出生命周期事件。"""
```

#### 3. 内部循环控制流（对齐 Pi / Tau）

1. **输入初始化**：将 `prompts` 追加进 `messages`，发射 `AgentStart` 与 `TurnStart`；
2. **微观 ReAct 内层循环** (`while has_more_tools or pending:`):
   - 准备临时视图：`view = await context_manager.prepare(messages)`；
   - 发射 `BeforeModelCall` 并允许拦截改写；
   - 调用 `llm.achat_stream`，实时派发 `MessageStart`、`MessageUpdate(delta)`、`MessageEnd`；
   - 若模型发起工具调用：
     - 发射 `ToolExecutionStart`；
     - 检查 `signal.is_cancelled()`；
     - 执行工具调用并收集结果；
     - 发射 `ToolExecutionEnd`；
     - 发射成对的 `TurnEnd`；
     - 检查并消费 `get_steering_messages()`；
   - 若模型未发起工具调用：
     - 发射 `TurnEnd`；
     - 检查并消费 `get_steering_messages()`（若有，继续转内层循环）；
     - 若无，退出内层循环；
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

### 3.4 模块四：会话存储子包重构 (`my_agent_core/session/`)

#### 1. 拆解单文件 `session.py` 为专职模块

```text
packages/my-agent-core/src/my_agent_core/session/
├── __init__.py           # 导出 Session, SessionTree, SessionEntry, SessionStorage
├── entries.py            # SessionEntry dataclass 家族（MessageEntry, LeafEntry 等）
├── tree.py               # 纯内存树算法（LCA 共同祖先、路径回溯、分支分叉，零 I/O）
├── storage.py            # 存储驱动协议与实现（InMemorySessionStorage / JsonlSessionStorage）
└── jsonl.py              # 行级编解码器（Crash-Safe 临时文件与 fsync）
```

#### 2. 存储驱动 Seam（接缝）设计

```python
class SessionStorage(Protocol):
    def append_entry(self, entry: SessionEntry) -> None: ...
    def load_all_entries(self) -> list[SessionEntry]: ...
    def rewrite_history(self, entries: list[SessionEntry]) -> None: ...

class InMemorySessionStorage(SessionStorage):
    """纯内存存储，单测无需创建任何磁盘文件，速度提升 5~10 倍且无磁盘残留。"""

class JsonlSessionStorage(SessionStorage):
    """原子文件追加持久化，支持崩溃恢复。"""
```

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
