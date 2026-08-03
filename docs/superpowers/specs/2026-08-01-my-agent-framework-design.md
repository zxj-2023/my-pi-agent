# 设计文档：my_agent_core 框架层 —— 参考 pi agent-core 打造精简 agent 框架

- **日期**：2026-08-01
- **状态**：待实现
- **位置**：`my_agent_core/`（框架层，本项目内）
- **设计参考**：pi（`D:/code/python/pi/packages/agent`）；pig-mono
  （`D:/code/python/pig-mono`，pi 的 Python 移植版）为直接参考
- **前序文档**：`docs/superpowers/specs/2026-07-31-my-react-agent-design.md`（本文档是它的演进）

## 1. 背景与目标

`my_agent_core` 已完成 2026-07-31 设计的全部交付：最简 ReAct 循环（`tools.py` / `agent.py` /
`main.py`）+ 完整离线测试。循环、工具注册、schema 生成、消息状态都已亲手写过一遍。

**目标**：把 `my_agent_core` 演进为 **pig-mono 式两层结构**的**框架层**（对应
`pig-agent-core`）；日后用它搭独立的 **coding agent 层**（对应 `pig-coding-agent`，
另行设计）。两层都是学习性实现，不奔生产；透明度与可理解性优先于通用性。
本文档及 session / context / skills / 可扩展性四份后续文档 = 框架层设计。

**研习对象**：pi（earendil-works/pi-mono）的 `packages/agent`（pi-agent-core）——
约 2200 行的核心运行时，分三层：

- `agent-loop.ts`（`runLoop`）：**无状态循环纯函数**，所有行为经 `AgentLoopConfig` 钩子注入
- `agent.ts`（`Agent` 类）：**有状态外壳**，持有 transcript、把循环事件折叠成状态、管理运行生命周期
- `stream-fn.ts`（`StreamFn`）：**唯一 LLM 边界**，`(model, context, options) → 事件流`，
  契约是"永不抛异常，错误编码进消息的 stopReason"

pi 还有 `harness/`（会话持久化、上下文压缩、skills、内置 bash/read/write 工具），
在 pi 里同样属于 agent 包。本项目把 **session / context / skills 选择性纳入
框架层**（独立文档）；内置工具集的归属留待 coding agent 层设计时讨论。

### 1.1 已确认的需求（澄清记录）

| 问题 | 决定 |
|---|---|
| 目标范围 | pig-mono 式两层：本文档 = 框架层（对应 pig-agent-core），coding agent 层另行设计；学习性实现，不奔生产 |
| LLM 边界 | 只支持 OpenAI 兼容；wire format dict 即内部消息格式；不做 provider 抽象 |
| 执行模型 | 纯同步先行；async 列入演进清单（`llm_call` 留作单一缝隙） |
| 扩展点 | 生命周期事件（单一 `on_event` 回调）+ 工具中间件（`before_tool` / `after_tool`） |
| 整体形态 | 方案 A：两层分离（无状态 `run_loop` + 有状态 `Agent`） |
| 循环护栏 | `max_iterations` 参数保留，默认 `None` = 不限（沿用 2026-07-31 的用户决定） |
| 系统提示词 | 无默认（沿用 2026-07-31 决定，对齐 `create_agent` 哲学） |

### 1.2 非目标（YAGNI，明确不做）

- 多 provider 适配层（精简版 pi-ai）
- 流式输出（streaming）、async 实现
- 工具并行执行（一轮多个 tool_calls 仍 for 循环串行）
- steering / followUp 消息队列、`prepareNextTurn` / `shouldStopAfterTurn` 钩子
- Message 类 / 双层消息（pi 的应用层 `AgentMessage` vs LLM 层 `Message` + `convertToLlm`）
- 工具结果双结构（pi 的 `content` 喂模型 + `details` 给 UI）——结果就是 `str`
- 重试 / 退避
- 事件订阅列表（单一回调够用）
- 推理内容回传（多轮连续性）、按 provider 的思考预算 / effort 分级控制（pi 的 `ThinkingLevel`）

## 2. 架构

pi 核心三层，本项目取两层——`convertToLlm` 那层因为没有自定义消息类型直接砍掉：

```
Agent (agent.py) —— 有状态外壳
  持有 messages（transcript 即状态）、tools、client/model、钩子
  run(text) → 追加 user 消息 → 调 run_loop → 返回最终文本
  reset() → 清空 transcript（保留 system prompt）
        │
run_loop (loop.py) —— 无状态纯函数
  (messages, get_tools, llm_call, 钩子) → 就地追加消息，返回 LoopOutcome
  工具调用管道（查找→解析→校验→before→执行→after）全在这里
        │
llm_call (llm.py) —— 唯一 LLM 缝隙
  openai_chat(client, model, messages, tools) → assistant 消息 dict
  SDK 响应对象 → wire dict 的"上行翻译"也在这里
  未来 async 化 / 换 provider 只改这一处
```

### 2.1 与 pi agent-core 的角色对应

| my_agent_core | pi packages/agent | 取舍说明 |
|---|---|---|
| `loop.py` 的 `run_loop` | `agent-loop.ts` 的 `runLoop` | 同：无状态纯函数，行为靠参数注入。异：pi 有内外双循环（followUp/steering），本项目只有单循环 |
| 工具执行管道（loop.py 内部） | `prepareToolCall` → `executePreparedToolCall` → `finalizeExecutedToolCall` | pi 的 prepare 含兼容垫片（`prepareArguments`）+ schema 校验 + 门禁；本项目砍垫片，保留执行前 schema 校验（手写精简版）与 `before_tool` 门禁，共六阶段 |
| `Agent` 类 | `agent.ts` 的 `Agent` | 同：持有 transcript、绑定钩子、组装循环。异：pi 维护派生状态（`isStreaming`、`pendingToolCalls`）并管理并发运行；本项目无派生状态、同步单线程 |
| `events.py` 的 8 个事件 | `AgentEvent` 联合类型（9 种） | 砍掉 `message_start/update/end` 三段式（无流式），保留轮次与工具生命周期；`ContextCompacted` / `ToolsChanged` 由 context / 可扩展性设计引入 |
| `llm.py` 的 `openai_chat` | `stream-fn.ts` 的 `StreamFn` | 同：唯一 LLM 边界。**契约相反**：pi 永不抛（错误编码进 stopReason 保住事件序列）；本项目直接抛异常（同步 Python 更直接，见 §2.2 决策 4） |
| reasoning 提取（llm.py 内） | provider 层 `ThinkingContent` 内容块 + `thinkingSignature` 回传 + 流式累积 | 三字段探测（借鉴 pi），归一到 `reasoning_content` 键；不回传、不流式累积、不做思考预算分级 |
| messages（wire dict 列表） | `AgentMessage` + `convertToLlm` | 砍掉双层，协议格式本身就是状态（沿用 2026-07-31 哲学） |
| 单一 `on_event` 回调 | `subscribe()` 监听器集合 | 简化为单回调 |
| `before_tool` / `after_tool` | `beforeToolCall` / `afterToolCall` | 同：可拦截、可改写。异：pi 用返回值 `{block: true}` 表达拦截；本项目用 `raise ToolBlocked` |
| `transform_context` 参数 | `transformContext` 钩子 | 同：LLM 边界视图变换；与内建压缩可组合（见可扩展性文档） |
| （无） | steering/followUp 队列、`shouldStopAfterTurn` | 不做（§1.2） |
| session / context / skills 文档 | `harness/` 的会话持久化、上下文压缩、skills | 纳入框架层（独立文档） |
| （无） | `harness/tools/`（bash/read/write/edit） | 内置工具集归属待定（coding agent 层设计时讨论） |

### 2.2 关键设计决策

1. **两层分离**。`run_loop` 是无状态纯函数（transcript 由调用方持有、就地追加），
   `Agent` 只是把状态与钩子绑在一起的组装器。回报：循环可用 `FakeLLM` 完全离线测试，
   不需要构造 Agent；这也是 pi 的核心一课。
2. **消息状态 = OpenAI wire format 的普通 dict 列表**（沿用 2026-07-31 决策 1）。
   只面向 OpenAI 格式时协议格式本身就是状态，不定义 Message 类。
3. **`llm_call` 单一缝隙**。循环只依赖 `(messages, tools_schema) -> assistant dict`
   这一个函数。未来 async 化时 `openai_chat` 换成 async 版本、`run_loop` 换成 async
   版本即可，缝隙位置与 pi 的 `StreamFn` 一致。本期不为 async 做任何提前设计。
4. **错误：工具路径永不抛，LLM 路径直接抛**。工具路径（未知工具、坏 JSON、校验失败、
   工具异常、中间件拦截或异常）一律转成错误结果字符串写回 transcript——因为存在一条核心不变式：
   **每个 `tool_calls` 必须配上对应的 tool 结果消息**，中途抛出会留下未配对调用，
   下一次 API 请求直接被拒。LLM API 错误则直接向上传播（v1 不做重试）：pi 把错误
   编码进消息是为了保住 TUI 的事件序列，同步库没有这个约束，fail loud 更 Pythonic。
5. **事件是通知，不是状态来源**。pi 的 `Agent.processEvents` 是事件 reducer，把事件
   折叠成派生状态（`pendingToolCalls` 等）供 UI 使用。同步版没有并发、没有流式片段，
   不需要派生状态——`messages` 就是全部状态。将来真需要（如做 TUI），再加一个
   消费 `on_event` 的 reducer，接口无需变化。
6. **助手消息在 `llm.py` 里翻译成 wire dict**。SDK 响应对象止步于 `openai_chat`，
   循环与 transcript 只见 dict（沿用 2026-07-31 决策 4：携带 `tool_calls` 的助手消息
   必须显式构造追加，即使 `content` 为空）。
7. **思考内容：归一化提取，但不回传**。借 pi 的三字段探测（厂商字段名不统一）与
   "翻译层包办一切"的立场；不学 pi 的 `ThinkingContent` 内容块、流式累积与
   signature 回传——v1 非流式，提取退化为调用完成后读一个字段。归一结果挂在
   assistant wire dict 的 `reasoning_content` 键上，transcript 与
   `AssistantMessageAdded` 事件原样携带（UI/日志自取），发往模型前剥离
   （纯 OpenAI 端点对 messages 中未知字段返回 400；pi 按 provider 条件回传
   需要 provider 层，不做）。

## 3. 模块结构

在现有文件上演进：

```
my_agent_core/
├── __init__.py      # 公共 API：Agent, tool, Tool, ToolBlocked, 事件类型
├── tools.py         # 基本不动：@tool 装饰器、Tool、schemas_for。call_tool 迁出（由 loop.py 接管执行）
├── llm.py           # 新增：openai_chat（SDK 边界 + 双向翻译：响应→wire dict、发送前剥离 reasoning，~40 行）
├── events.py        # 新增：事件 dataclass（~30 行）
├── loop.py          # 新增：run_loop + 工具执行管道 + LoopOutcome + ToolBlocked（~160 行）
├── agent.py         # 重写：run_agent 函数 → Agent 类（~60 行）
└── main.py          # 更新：demo 改用 Agent API
tests/
└── test_my_agent.py # 迁移：schema 测试保留，循环测试改用 FakeLLM 驱动 run_loop/Agent
```

## 4. 组件接口

### 4.1 `tools.py`（不变，仅移除 `call_tool`）

`Tool`、`@tool`、`schemas_for` 保持现状（现有 5 个 schema 测试继续全绿）。
`call_tool` 的执行职责并入 `loop.py` 的管道（中间件是循环行为，不是工具行为），
函数本身删除。

### 4.2 `llm.py`

```python
def openai_chat(client: OpenAI, model: str, messages: list[dict], tools: list[dict]) -> dict:
    """唯一 LLM 缝隙。发一次 chat.completions.create，双向翻译：

    回程（响应 → wire dict）：
        {"role": "assistant", "content": ...,
         "tool_calls": [...]}                    # 无调用时不带 tool_calls 键
        {"role": "assistant", ..., "reasoning_content": ...}   # 提取到推理内容时
    依次探测 reasoning_content / reasoning / reasoning_text 三个候选字段
    （借鉴 pi：各厂商字段名不统一，如 llama.cpp 用 reasoning_content），
    取第一个非空的，归一挂到 reasoning_content 键；都没有则不挂此键。

    去程（wire dict → 请求）：发送前剥离所有 assistant 消息上的 reasoning_content
    键（不回传——纯 OpenAI 端点对 messages 中未知字段返回 400；
    DeepSeek 式的多轮连续性回传见 §8 演进路线）。

    契约：API / 网络错误直接抛异常，由调用方处理（v1 不重试）。
    """
```

### 4.3 `events.py`

```python
@dataclass(frozen=True)
class Event: ...                          # 基类，仅用于类型标注 Callable[[Event], None]

@dataclass(frozen=True)
class AgentStart: ...
@dataclass(frozen=True)
class TurnStart:               iteration: int
@dataclass(frozen=True)
class AssistantMessageAdded:   message: dict          # 已追加进 transcript 的助手消息
@dataclass(frozen=True)
class ToolCallStart:           call_id: str; name: str; args: dict
@dataclass(frozen=True)
class ToolCallEnd:             call_id: str; name: str; result: str; is_error: bool
@dataclass(frozen=True)
class AgentEnd:                final_text: str | None; iterations: int; stop_reason: str
                               # stop_reason: "end_turn" | "max_iterations"
@dataclass(frozen=True)
class ContextCompacted:        tokens_before: int; tokens_after: int; summarized_count: int
                               # context 管理完成一次摘要压缩时发射（见 context 管理设计文档）
@dataclass(frozen=True)
class ToolsChanged:            action: str; name: str
                               # action: "registered" | "unregistered"（见可扩展性设计文档）
```

契约：`on_event` 不应抛异常（抛了会中断循环，视为使用方 bug，不做兜底）。

### 4.4 `loop.py`

```python
class ToolBlocked(Exception):
    """before_tool 拦截工具调用时抛出；reason 会变成错误结果喂回模型。"""

@dataclass(frozen=True)
class LoopOutcome:
    final_text: str | None     # 正常结束时为模型最终文本；max_iterations 耗尽时为 None
    iterations: int            # 实际发生的 LLM 调用次数
    stop_reason: str           # "end_turn" | "max_iterations"

def run_loop(
    messages: list[dict],      # 调用方持有的 transcript，就地追加
    *,
    get_tools: Callable[[], list[Tool]],   # 每 turn 取快照：动态注册/注销 turn 边界生效（见可扩展性文档）
    llm_call: Callable[[list[dict], list[dict]], dict],
    max_iterations: int | None = None,   # 默认不限（沿用 2026-07-31 决定）
    on_event: Callable[[Event], None] | None = None,
    before_tool: Callable[[str, dict], dict] | None = None,
    after_tool: Callable[[str, dict, str, bool], str] | None = None,
) -> LoopOutcome:
    """伪代码（这就是全部逻辑；emit = on_event，为 None 时为空操作）：
        emit(AgentStart)
        iteration = 0
        while max_iterations is None or iteration < max_iterations:
            iteration += 1
            emit(TurnStart(iteration))
            turn_tools = get_tools()                     # 每 turn 快照（见可扩展性文档）
            schemas = schemas_for(turn_tools); tools_by_name = {t.name: t for t in turn_tools}
            assistant = llm_call(messages, schemas)      # API 错误 → 直接向上抛
            messages.append(assistant)
            emit(AssistantMessageAdded(assistant))
            tool_calls = assistant.get("tool_calls")
            if not tool_calls:                            # ← 经典退出条件
                emit(AgentEnd(assistant["content"], iteration, "end_turn"))
                return ...
            for tc in tool_calls:
                result, is_error = execute_one(...)       # 永不抛，见下
                messages.append({"role": "tool", "tool_call_id": tc["id"],
                                 "content": result})
        emit(AgentEnd(None, iteration, "max_iterations"))
        return ...
    """
```

`execute_one`（loop.py 内部函数，`call_tool` 的升级版）——六段管道，
任何一步失败都落到同一条路（错误字符串 + `is_error=True`）：

```
1. tools_by_name.get(name)      → 未命中 → "Unknown tool 'X'. Available: a, b"（沿用现有措辞）
2. json.loads(arguments)        → 失败   → "Invalid JSON arguments for tool 'X': ..."（沿用；现由 ToolRegistry.execute 负责）
                                  结果非 dict → "Invalid arguments for tool 'X': expected JSON object"
3. tool.model.model_validate(args) → ValidationError → 校验错误字符串（逐条列出，pi 风格，见下；含类型强转）
4. before_tool(name, args)      → ToolBlocked(reason) → "Tool 'X' blocked: reason"
                                  其他异常           → "Error in before_tool for 'X': ..."
                                  正常返回           → 用返回的 args（可被改写）继续
5. tool.func(**args)            → 异常   → "Error executing tool 'X': ..."（沿用）
                                  成功   → result = str(返回值)
6. after_tool(name, args, result, is_error)
                                → 异常   → 错误字符串（同一条路）
                                  正常返回 → 用返回的 result（可被改写）
```

```python
# —— 已由 2026-08-03-pydantic-tool-schema-design.md 取代 ——
# 校验不再是手写函数，而是 Tool 上的 pydantic 参数模型：
#
#     validated = tool.params_model.model_validate(args)  # 校验 + 类型强转（"37" → 37）
#     # ValidationError → _format_validation_error(name, exc) → 逐条错误字符串
#
# 原三条规则全部由 pydantic 覆盖：
# - 缺必填   → pydantic required 检查（装饰器生成的模型字段即真实签名）
# - 类型不符 → pydantic 类型检查（bool→int 强转不算错，属宽松取舍，见 2026-08-03 规格）
# - 多余参数 → 动态模型 extra="forbid"
# 错误消息直接沿用 pydantic 原始 msg，逐条列出（pi 风格）：
#
#     Validation failed for tool "get_weather":
#       - city: Field required
#       - retries: Input should be a valid integer
#       - verbose: Extra inputs are not permitted
```

### 4.5 `agent.py`

```python
class Agent:
    def __init__(self, *, client, model, tools=(), system_prompt=None,
                 max_iterations=None, on_event=None, before_tool=None, after_tool=None,
                 session=None,                                        # session 文档
                 context_budget=None, keep_recent_tokens=None,        # context 文档
                 transform_context=None, compaction_summarizer=None,  # context + 可扩展性文档
                 skill_dirs=None):                                    # skills 文档
        """各参数语义见对应文档；要点：
        - system_prompt 默认 None（沿用旧决定）：给了就成为 transcript 第 0 条消息；
          skill_dirs 启用时框架在尾部追加 skill 清单块（skills 文档 §2.2-4）
        - session：文件路径；存在 → 恢复（文件为准），不存在 → 创建；turn 边界落盘
        - context_budget 为 None = 不启用压缩
        - transform_context：内建压缩之后的视图变换，最终决定权，fail-loud
        - skill_dirs 为 None = 无 skill 机制（向后兼容）"""
        self.messages: list[dict] = []   # 公开可读：transcript 即全部状态，透明优于封装
        self.tools: list[Tool]           # 可变注册表：公开可读，写入口仅 register/unregister_tool
        self.session_path: Path | None   # 公开可读（无 session 时 None）
        self.skills: list[Skill]         # 公开可读（无 skill_dirs 时 []）；skill_diagnostics 同
        ...                              # 其余参数原样存字段

    def run(self, user_input: str) -> str | None: ...    # 追加 user 消息 → run_loop → 最终文本
    def resume_run(self) -> str | None: ...              # session 文档：不追加新 user 的崩溃续跑
    def register_tool(self, tool: Tool) -> None: ...     # 运行时注册，撞名 ValueError，下一 turn 生效
    def unregister_tool(self, name: str) -> None: ...    # 运行时注销，未知名 ValueError（可扩展性文档）
    def invoke_skill(self, name: str, instructions: str = "") -> str | None: ...  # skills 文档：显式调用
    def reset(self) -> None: ...                         # 清 transcript（留 system）、重写 session 文件、清压缩缓存

    def _llm_call(self, messages, schemas) -> dict:      # 缝隙绑定 + 压缩管线（context 文档 §4.2）
        ...
```

### 4.6 `__init__.py` 公共 API

`Agent`、`tool`、`Tool`、`ToolBlocked`、8 个事件类型、`Event`。

## 5. 数据流

以 `agent.run("What's the weather like in Tokyo and Paris?")` 为例：

```
事件序列                                transcript（messages）演化
─────────────────────────────────────────────────────────────────
AgentStart                              [system?, user]
TurnStart(iteration=1)
  llm_call(messages, [3 个 schema])
  ★ 模型判断：需要工具，发起两个调用
AssistantMessageAdded                   += {assistant, content:null,
                                             tool_calls:[Tokyo, Paris]}
ToolCallStart(call_1, get_weather, {city:"Tokyo"})
ToolCallEnd(call_1, ..., "Tokyo: sunny, 22°C (simulated)", False)
                                        += {tool, call_1, "Tokyo: sunny..."}
ToolCallStart(call_2, ...) / ToolCallEnd(call_2, ...)
                                        += {tool, call_2, "Paris: cloudy..."}
TurnStart(iteration=2)
  llm_call(...)
  ★ 模型判断：信息够了
AssistantMessageAdded                   += {assistant, "Tokyo is sunny 22°C; Paris..."}
AgentEnd(final_text="Tokyo is sunny...", iterations=2, stop_reason="end_turn")
```

循环出口两个：**模型不再发起 tool_calls**（`end_turn`）与 `max_iterations` 耗尽
（`max_iterations`，默认不启用）。与 2026-07-31 版相同：模型也可能分多轮各调一次，
循环天然支持——每轮都带上完整历史重新请求。

## 6. 错误处理

原则（沿用 2026-07-31，与 pi 工具路径一致）：**工具层错误转消息回给模型，
循环/配置/LLM 层错误直接抛**。

| 故障 | 位置 | 处理 |
|---|---|---|
| LLM API / 网络错误 | `openai_chat` | 直接抛 → 穿出 `run_loop` → 穿出 `Agent.run()` → 调用方处理 |
| 模型幻觉出不存在的工具名 | `execute_one` 步骤 1 | 错误字符串 + `is_error=True`，模型可自我纠正 |
| 模型生成的参数 JSON 非法 / 非对象 | 步骤 2 | 错误字符串（`json.loads` 失败信息或 "expected JSON object"） |
| 模型参数缺必填 / 类型不符 / 多余参数 | 步骤 3 | `tool.model.model_validate`（pydantic）逐条列出违规成错误字符串，工具不执行 |
| `before_tool` 拦截 | 步骤 4 | `ToolBlocked` → 错误字符串 "Tool 'X' blocked: reason"，工具不执行 |
| 中间件自身抛其他异常 | 步骤 4 / 6 | 同样转错误字符串——保住"tool_calls 必配对"不变式 |
| 工具函数抛异常 | 步骤 5 | 错误字符串 "Error executing tool 'X': ..." |
| `on_event` 抛异常 | 事件发射处 | 不兜底，向上抛（视为使用方 bug） |
| 装饰器遇到无标注参数 / *args/**kwargs / 无法建模的类型 | `@tool` | 装饰时（import 阶段）抛 `TypeError`（默认值合法，见 2026-08-03 规格） |
| `OPENAI_API_KEY` 缺失 | `build_client` | 启动时 `RuntimeError`（不变） |

## 7. 测试与验收标准

### 7.1 离线测试（`tests/test_my_agent_core.py`，无需 API key）

旧 `run_agent` 时代的测试已随重构清理删除，本表全部从零编写。
`FakeLLM`：因为缝隙是 `llm_call`（不是 SDK），替身极简——按脚本返回
**wire dict**，记录收到的 `(messages, tools)` 请求（深拷贝，防后续追加污染）：

```python
class FakeLLM:
    def __init__(self, responses: list[dict]): ...   # 助手消息 wire dict 序列
    def __call__(self, messages, tools) -> dict: ... # 记录请求，pop 下一条响应
```

| # | 测试 | 验证点 |
|---|---|---|
| 1 | schema 生成 | `@tool` / `schemas_for` 行为（名字/docstring/类型标注 → pydantic schema；零参数；默认值/Optional/复杂类型；无标注与 *args/**kwargs 报错） |
| 2 | 直接回答路径 | FakeLLM 返回纯 content → 一轮、`stop_reason="end_turn"`、`final_text` 正确 |
| 3 | 工具调用路径 | 一轮 tool_calls + 一轮最终回答 → transcript 中 tool 消息 content 为真实执行结果（配对验证） |
| 4 | 一轮多个 tool_calls | 两个调用各自配对写回 |
| 5 | 未知工具 / 坏 JSON / 工具异常 | 错误字符串写回且循环继续，最终正常结束 |
| 6 | 参数校验（新） | pydantic 校验 + 强转（"37"→37）；缺必填 / 类型不符 / 多余参数 → 错误逐条列出违规，工具未执行（副作用探针）；arguments 非 JSON object → 错误字符串 |
| 7 | `before_tool` 拦截（新） | 抛 `ToolBlocked("no")` → tool 消息含 "blocked: no"，工具函数未被调用（用副作用探针验证） |
| 8 | `before_tool` 改写参数（新） | 返回改写的 args → 工具收到改写值 |
| 9 | `after_tool` 改写结果（新） | 返回改写 result → transcript 中是改写后的文本 |
| 10 | 中间件抛其他异常（新） | 转错误字符串，transcript 不变形（配对不变式成立） |
| 11 | 事件序列（新） | 收集 `on_event` 收到的事件，断言完整顺序（AgentStart → TurnStart → AssistantMessageAdded → ToolCallStart/End... → AgentEnd） |
| 12 | `max_iterations`（新） | 传 `max_iterations=1` 且模型一直发 tool_calls → `stop_reason="max_iterations"`、`final_text=None`；默认 `None` 时行为同旧版 |
| 13 | Agent 多轮 + reset（新） | 连续两次 `run()` 第二次请求含第一轮历史；`reset()` 后只剩 [system]（或空） |
| 14 | `openai_chat` 翻译 | 用一个 duck-type SDK 的假 client：响应 → wire dict（含 `tool_calls` 与不含两种）；三字段探测 reasoning 归一到 `reasoning_content` 键（无推理内容时不挂键）；transcript 中有此键时请求侧 assistant 消息不含它（剥离验证） |
| 15 | demo 相关 | `build_client`（缺 key 报错 / base_url 透传）+ demo 工具 schema |

### 7.2 验收标准（步骤 → 验证方式）

```
tools.py 移除 call_tool + events.py + llm.py   → #1、#14 通过
实现 loop.py                                    → #2-#12 通过（FakeLLM 驱动，离线）
重写 agent.py                                   → #13 通过
更新 main.py + 新建 test_my_agent_core.py       → uv run pytest -q 全绿（#1-#15）
真实验证（需 .env）                             → uv run python -m my_agent_core.main
                                                  问题 1 答案含 703；问题 2 答出当前时间；问题 3 答出两城市天气
```

## 8. 演进路线（v1 之后，每项对标 pi 的对应物）

v1 范围 = 本文档 + session / context / skills / 可扩展性四份独立文档
（实现顺序见 README「TODO：v1 实现路线」）。以下为 v1 之后：

1. **async 化**：`openai_chat` → async 版，`run_loop` → async 版。只动缝隙两侧，
   工具、事件、Agent API 形态不变（pi 全异步，这是它的形态）。
2. **流式事件**：`llm_call` 改吐增量事件，`message_update` 类事件回归
   （pi 的 `message_start/update/end` 三段式）；思考内容改流式累积
   （pi 的 `thinking_start/delta/end`）。
3. **推理内容回传（多轮连续性）**：不只是"去程不剥离"——各端点规则不同：
   DeepSeek 服务端默认读取回传的 reasoning；百炼（本项目实际端点）需要在回传
   字段的同时显式传 `extra_body={"preserve_thinking": True}`，否则模型默认不读
   （开启后历史思考计入输入 token）。这类"按端点的请求参数差异"即是引入薄
   provider 兼容层的信号（pi 的对应物：`requiresReasoningContentOnAssistantMessages`
   compat 标志）。
4. **工具结果结构化**：`str` → `content + details` 双结构
   （pi 的 `AgentToolResult`，UI 与模型各取所需）。

## 9. 风险与备注

- **项目尚未初始化 git**：本设计文档与后续改动都不进版本库，回滚依赖测试网；
  是否 `git init` 由用户决定。
- **wire 格式细节**：SDK 的 `tool_calls[].function.arguments` 是 JSON **字符串**
  而非 dict，`llm.py` 翻译时原样保留（管道步骤 2 才解析）；`FakeLLM` 的测试
  替身也必须保持这一格式。
- **模型行为不确定**：真实运行时模型可能不调工具直接心算 37×19（小概率）；
  验收以离线测试为主、真实运行为辅（同 2026-07-31）。

## 10. 修订记录

- 2026-08-01：初版与核心决定：目标=精简框架；LLM 边界=只 OpenAI 兼容；
  执行模型=纯同步（async 入路线）；扩展点=事件+工具中间件；形态=两层分离；
  `max_iterations` 默认 `None`、system prompt 无默认（沿用 2026-07-31 决定）。
- 2026-08-01：对照 pi 工具机制 → 纳入执行前 schema 校验（pi
  `validateToolArguments` 精简版，手写不引 jsonschema）：管道 5→6 阶段，
  错误处理与测试 #6 相应增加（§2.1/§4.4/§6/§7）。
- 2026-08-01：对照 pi thinking 链路 → 思考内容"提取但不回传"（三字段探测
  归一 + 发送前剥离，§4.2/§2.2 决策 7）；查证百炼官方文档确认"不回传"
  与实际端点默认语义一致（§8-3）。
- 2026-08-01：汇总四份独立设计的联动：session（持久化提前入 v1，`Agent`
  增 `session` 参数）、context（摘要压缩，事件集 6→7 `ContextCompacted`，
  `context_budget` 等参数）、skills（system prompt 组装，`skill_dirs` /
  `invoke_skill`）、可扩展性（`run_loop` 的 `tools` → `get_tools`，事件集
  7→8 `ToolsChanged`，`register_tool` / `unregister_tool`、`transform_context`）。
- 2026-08-01：定位定稿：pig-mono 式两层——`my_agent_core` 框架层对应
  `pig-agent-core`，再用它搭独立的 coding agent 包对应 `pig-coding-agent`；
  pig-mono（`D:/code/python/pig-mono`）是 pi 的 Python 移植版、为直接参考。
  五份运行时文档归属框架层；标题与 §1 相应修订。
