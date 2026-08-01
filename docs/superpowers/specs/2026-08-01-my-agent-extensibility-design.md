# 设计文档：my_agent_core 运行时可扩展性 —— 动态工具 + 可注入策略

- **日期**：2026-08-01
- **状态**：待实现
- **位置**：`my_agent_core/`，修订框架文档（`run_loop` 签名、事件集、`Agent` API）
  与 context 文档（`ContextManager`、`Agent` 参数）
- **设计参考**：pi `agent-harness.ts`（`setTools` / `activeToolNames` /
  `prepareNextTurn` 每 turn 刷新）、`agent-loop.ts` 的 `transformContext`、
  coding-agent 的 `session_before_compact` 自定义压缩

## 0. 背景：定位调整

用户最终明确（2026-08-01）：my_agent_core 走 **pig-mono 式两层结构**——
pig-mono（`D:/code/python/pig-mono`）是 pi 的 **Python 移植版**，为本项目
直接参考：先做 `my_agent_core` **框架层**（对应 `pig-agent-core`），再用它搭
独立的 **coding agent 层**（对应 `pig-coding-agent`）。原则不变：尽量
简洁，不奔生产。

对既有设计的影响：五份文档（框架 / session / context / skills / 本文档）
归属**框架层**，技术内容不受影响——对应 pig-agent-core 的模块划分
（`agent.py` / `session*.py` / `context.py` / `skills.py` / `tools/registry.py`）。
coding agent 层（CLI 入口、coding 系统提示、权限门控、工具组装等）独立成包、
另行设计。本文档的两项增强同时服务两层：动态工具是 agent-as-tool /
自演进工具集 / MCP 式外部工具源的前置（pig-agent-core 亦有 `tools/registry.py`）；
可注入策略让框架行为可被上层 coding agent 定制。

## 1. 背景与目标

用户明确要补的两项设计：

1. **动态工具注册/注销**——运行中增删工具（pi 的 `addedToolNames` 体系
   的精简版）；
2. **内建策略可注入化**——把 `ContextManager`、压缩策略从"内建默认"开放
   为构造参数（pi 的 `transformContext` / 自定义压缩钩子）。

### 1.1 已确认的需求（澄清记录）

| 问题 | 决定 |
|---|---|
| 动态工具的生效粒度 | **turn 边界**：注册/注销在下一 turn 生效；turn 内快照一致（schemas 与分发表每 turn 重建一次） |
| 名字冲突 | 显式失败（`ValueError`），不覆盖；想覆盖先 `unregister_tool` |
| 工具注册表的归属 | **代码状态，不是会话状态**——不进 session 文件（与 pi 不同，见 §2.2-3） |
| 可注入策略的组合方式 | 管线式：内建压缩（若启用）先跑，`transform_context` 后跑、有最终决定权 |
| `transform_context` 异常 | 向上抛（fail-loud，用户的代码 bug）；与内建压缩摘要失败的"降级宽容"刻意不同 |

### 1.2 非目标（YAGNI）

- 全量/激活子集两层名单（pi 的 `activeToolNames`，服务 UI 勾选场景，本项目无 UI）
- `addedToolNames` 式"从 transcript 某点起引入工具"标记——那是 provider 层
  prompt cache 优化（延迟工具加载），本项目没有 provider 层，不适用
- 工具注册表变更持久化（pi 的 `active_tools_change` session entry）
- 压缩细粒度旋钮开放（触发比例、切点策略）——`transform_context` 已是完全
  逃生舱，且切点配对是不变式不是策略（§2.2-5）
- MCP 协议本身、扩展式工具加载器——配方级（§3.4），机制已由 `register_tool` 覆盖

## 2. 架构

```
动态工具                              可注入策略
──────                              ──────────
Agent.register_tool(tool)           Agent(..., transform_context=fn,
Agent.unregister_tool(name)                compaction_summarizer=fn)
  │ 改动 self.tools、发射 ToolsChanged      │
  ▼                                          ▼
run_loop(get_tools=lambda: self.tools)  Agent._llm_call:
  每 turn：                              view = ctx.prepare(messages)   # 内建压缩（可注入 summarizer）
    turn_tools = get_tools()    ← 快照    view = transform_context(view) # 用户钩子（最终决定权）
    schemas / 分发表按快照重建            openai_chat(client, model, view, schemas)
```

### 2.1 与 pi 的角色对应

| my_agent_core | pi | 取舍说明 |
|---|---|---|
| `register_tool` / `unregister_tool` | `setTools` / 扩展 `registerTool` | 同：运行时可变、发事件（`ToolsChanged` ↔ `tools_update`）。异：单个增删 API 而非整体替换；无激活子集 |
| `get_tools` turn 快照 | `prepareNextTurn` 每 turn 刷新 `turnState.activeTools` | 同语义：turn 内一致、turn 边界生效 |
| 名字冲突 → `ValueError` | 重名工具校验（`validateUniqueNames` 报错） | 同：显式失败 |
| 注册表不持久化 | `active_tools_change` session entry | **刻意不同**（§2.2-3） |
| `transform_context` 参数 | `transformContext` 钩子（agent-loop.ts:289） | 同：LLM 边界、非破坏性视图。异：与内建压缩管线组合（内建先、钩子后） |
| `compaction_summarizer` 参数 | `session_before_compact` 扩展钩子 / `compact(customInstructions)` | 精简：注入"摘要函数"（纯函数 `messages → str`），不是"整个压缩流程的事件钩子" |
| （无） | `addedToolNames` + provider 延迟工具加载 | 不适用：无 provider/cache 层 |

### 2.2 关键设计决策

1. **turn 快照一致性**。每 turn 开始时 `turn_tools = get_tools()`，该 turn 的
   schemas 与工具分发表都从这份快照重建。推论：
   - turn 进行中的注册 → **下一 turn** 生效（模型下一轮才看到新 schema）；
   - turn 进行中注销某工具 → 不影响在途 turn（同一 assistant 消息里对它的
     挂起调用仍按快照执行），下一 turn 不再提供；
   - 工具在执行中注册工具（自演进场景）→ 天然安全，下一 turn 可见。
2. **名字冲突 = 错误，不是覆盖**。`register_tool` 撞名抛 `ValueError`；
   要替换就 `unregister_tool` + `register_tool`（显式两步，意图清晰）。
3. **工具注册表是代码状态，不是会话状态**。pi 持久化 `active_tools_change`
   是因为它的工具集由扩展/UI 勾选驱动，跨会话要恢复用户选择；my_agent_core 的
   工具由代码定义（构造函数 + `register_tool` 调用），恢复会话时工具集由
   **当前代码**决定，transcript 里的历史工具调用只是历史。少一种 entry
   类型，少一套恢复逻辑。
4. **可注入策略的管线顺序**：`_llm_call` 内先内建压缩（`ctx.prepare`，
   若 `context_budget` 启用），后 `transform_context`。钩子看到并可以
   改写/推翻压缩结果（包括完全换成自己的窗口策略）。契约：纯函数、
   非破坏性（不改传入 list）、异常向上抛（fail-loud，与内建摘要失败的
   降级宽容刻意区分——内建失败是"优化没做成"，钩子失败是"用户代码坏了"）。
5. **不开放压缩细粒度旋钮**。触发比例、保留量有参数够了；切点对齐 user
   边界是协议不变式（切开 tool 配对 = API 拒绝），不是可配置策略。真要
   完全不同的压缩方案，`transform_context` 就是逃生舱，或
   `context_budget=None` 关掉内建、全自己来。
6. **agent-as-tool 与 MCP 是配方，不是机制**（§3.4）。`register_tool` +
   `Tool` 抽象已经足够：子代理工具 = 一个内部跑 `Agent` 的 `@tool` 函数；
   外部工具源 = 一个把外部描述翻译成 `Tool` 对象并 `register_tool` 的加载器。

## 3. 组件接口

### 3.1 `Agent` 动态工具 API（agent.py 修订）

```python
class Agent:
    def register_tool(self, tool: Tool) -> None:
        """运行时注册。撞名 → ValueError。发射 ToolsChanged(action="registered")。
        生效时机：当前 run 进行中的下一 turn，或下一次 run()。"""

    def unregister_tool(self, name: str) -> None:
        """运行时注销。未知名字 → ValueError。发射 ToolsChanged(action="unregistered")。
        不影响在途 turn（turn 快照已取）。"""
```

`Agent.tools` 从"构造时拷贝的列表"变为**可变注册表**（公开可读，
`register/unregister` 是唯一写入口——不允许外部直接改 list 绕过事件，
框架文档 §4.5 的 tools setter 语义相应修订为只读视图）。

### 3.2 `run_loop` 签名修订（loop.py，框架文档 §4.4 同步）

```python
def run_loop(
    messages: list[dict],
    *,
    get_tools: Callable[[], list[Tool]],   # ← 原 tools: list[Tool]
    llm_call: ..., ...
) -> LoopOutcome:
    """伪代码修订点：
        while ...:
            emit(TurnStart(iteration))
            turn_tools = get_tools()                      # ← 每 turn 快照
            schemas = schemas_for(turn_tools)
            tools_by_name = {t.name: t for t in turn_tools}
            assistant = llm_call(messages, schemas)
            ...
    独立测试 run_loop 时传 lambda: [...] 即可（FakeLLM 测试不受影响）。"""
```

`Agent._llm_call` 绑定处相应传 `get_tools=lambda: self.tools`。
六段管道的 `execute_one` 用当 turn 的 `tools_by_name`（不变）。

### 3.3 可注入策略参数（Agent / ContextManager，context 文档 §4 同步）

```python
class Agent:
    def __init__(self, ...,
                 transform_context: Callable[[list[dict]], list[dict]] | None = None,
                 compaction_summarizer: Callable[[list[dict]], str] | None = None):
        """transform_context：每次 LLM 请求前、内建压缩之后应用；纯函数、
        非破坏性、异常上抛。compaction_summarizer：注入 ContextManager，
        替换内建 pi 风格结构化摘要（签名：待摘要消息列表 → 摘要文本）。"""

class ContextManager:
    def __init__(self, budget, llm_call, keep_recent_tokens=None,
                 summarizer: Callable[[list[dict]], str] | None = None):
        """summarizer=None → 内建：经 llm_call 做结构化摘要（现有行为）。
        prepare() 步骤 4 改为调用 summarizer(messages[1:cut])。"""
```

### 3.4 配方（文档级，不写进代码）

```python
# agent-as-tool：子代理包装成工具（自演进/分工的最小形态）
sub = Agent(client=..., model=..., tools=[...], system_prompt="检索专员...")

@tool
def research(query: str) -> str:
    """Delegate a research sub-task to a sub-agent."""
    return sub.run(query) or ""

agent.register_tool(research)

# MCP 式外部工具源：加载器 = 翻译器 + register_tool
for spec in mcp_client.list_tools():          # 外部协议（未来）
    agent.register_tool(tool_from_mcp_spec(spec))
```

## 4. 与既有机制的交互

- **事件集 7→8**：新增 `ToolsChanged(action: str, name: str)`，
  `action ∈ {"registered", "unregistered"}`（框架文档 §4.3 同步）
- **session**：注册表不进文件（决策 3）；恢复会话时工具集由当前代码决定。
  transcript 中历史 tool 消息引用的旧工具名只是历史，不需任何修复
- **context**：`transform_context` 产出的视图只影响发送，transcript 与
  session 文件不变（与 `ContextManager.prepare` 同一非破坏性语义）
- **skills**：`read_skill` 工具经 `register_tool` 语义注册（skill 设计里
  是构造时置于 tools 首位，本设计后等价于初始化时注册）；动态注销
  `read_skill` 合法（skill 清单仍在 system prompt，但加载不了——模型会
  收到未知工具错误并自适应；不防护这种自残配置）
- **中间件**：动态注册的工具走同一条六段管道，`before_tool`/`after_tool`
  天然覆盖（可按 `name` 对新工具做权限门控——产品层权限模型的现成落点）

## 5. 数据流

**动态工具（工具注册工具）**：

```
turn 1：模型调 bootstrap() → 该工具执行中 agent.register_tool(echo)
        → ToolsChanged("registered", "echo") 发射
        → turn 1 快照不变（bootstrap 正常完成）
turn 2：TurnStart → turn_tools = get_tools() 含 echo
        → 本轮 schemas 含 echo → 模型可调 echo("...")
```

**可注入策略管线**：

```
messages（完整 transcript，95k tokens，budget=100k）
  ▼ ctx.prepare()        内建压缩 → [system, 摘要, 尾部]（31k）
  ▼ transform_context()  用户钩子：比如再塞一条"当前 git 分支: main"的注入消息
  ▼ openai_chat(view)    模型所见 = 压缩视图 + 用户注入
transcript 全程不变
```

## 6. 错误处理

| 故障 | 位置 | 处理 |
|---|---|---|
| `register_tool` 撞名 | `Agent` | `ValueError`（列现有工具名） |
| `unregister_tool` 未知名字 | `Agent` | `ValueError` |
| `transform_context` 抛异常 | `Agent._llm_call` | 向上抛（fail-loud；中断本 turn，transcript 不受影响） |
| `transform_context` 返回非法消息 | 下一次 API 调用 | API 报错上抛（与框架 LLM 错误处理一致） |
| `compaction_summarizer` 抛异常 | `ContextManager.prepare` | 与内建摘要失败同语义：降级不压缩，返回原视图 |
| turn 进行中注销、同 turn 又有对它的挂起调用 | `execute_one` | 按 turn 快照照常执行（决策 1） |

## 7. 测试与验收标准

### 7.1 动态工具（`tests/test_dynamic_tools.py`，FakeLLM 驱动）

| # | 测试 | 验证点 |
|---|---|---|
| 1 | 多轮间注册 | `register_tool` 后第二次 `run()` → FakeLLM 第二次请求的 tools 含新工具 |
| 2 | run 中注册（工具注册工具） | FakeLLM：turn 1 调 `bootstrap` → 断言 turn 2 请求的 tools 含新名字，且 turn 1 请求不含 |
| 3 | 注销 | `unregister_tool` 后下一 run 请求 tools 不含它；transcript 历史不变 |
| 4 | 冲突与未知 | 撞名 register → `ValueError`；未知名 unregister → `ValueError` |
| 5 | turn 快照一致性 | 一轮两个 tool_calls，第一个执行中注销第二个工具 → 第二个仍按快照执行成功 |
| 6 | `ToolsChanged` 事件 | register/unregister 各发射一次，action/name 正确 |
| 7 | agent-as-tool 配方 | 子代理工具（内层 FakeLLM）被外层模型调用，返回子代理答案 |

### 7.2 可注入策略（并入 `tests/test_context.py`）

| # | 测试 | 验证点 |
|---|---|---|
| 8 | 管线顺序 | 同时启用内建压缩与 `transform_context` → 请求视图先被压缩、再过钩子（钩子输入是压缩后视图） |
| 9 | 仅钩子无压缩 | `context_budget=None` + `transform_context` 注入一条消息 → 请求含注入、transcript 不含 |
| 10 | 钩子异常 fail-loud | `transform_context` 抛异常 → `run()` 抛出；transcript 未被污染 |
| 11 | 自定义 summarizer | 传入 summarizer → 压缩发生时**无**内建摘要 LLM 请求，summarizer 收到 messages[1:cut]、返回值进入视图 |
| 12 | summarizer 失败降级 | summarizer 抛异常 → 不压缩、原视图发出（与内建摘要失败同语义） |

### 7.3 验收标准

```
run_loop get_tools 化 + Agent register/unregister → #1-#7 通过
transform_context + compaction_summarizer          → #8-#12 通过
全量回归                                           → uv run pytest -q 全绿（四份既有设计测试不回归）
```

## 8. 文档联动与实现安排

**框架文档修订**（本次同步）：§1 记录定位调整；§4.3 事件 7→8
（`ToolsChanged`）；§4.4 `run_loop` 的 `tools` 参数改 `get_tools`、
伪代码按 turn 取快照；§4.5 `Agent` 增加 `register_tool`/`unregister_tool`、
`tools` 语义改为只读视图；修订记录两条。

**context 文档修订**（本次同步）：§4.1 `ContextManager` 增 `summarizer`
参数、`prepare` 步骤 4 改调 summarizer；§4.2 `Agent` 增 `transform_context`/
`compaction_summarizer` 参数与管线契约；修订记录一条。

**实现安排**（README 同步）：
- 可注入策略（#8-#12）**并入 v1 阶段 5**（只是两个可选参数，成本近零）；
- 动态工具（#1-#7）为**新增阶段 7**（依赖阶段 3 的 Agent 完成）。

## 9. 演进路线（pi 对应物）

1. **激活子集**：`set_active_tools(names)` + 全量/激活两层（pi `activeToolNames`）
   ——产品层有工具开关 UI 时再做
2. **注册表持久化**：`active_tools_change` 式 session entry（pi 同名机制）
   ——依赖 session typed entries（session 文档 §9）
3. **`addedToolNames` 式延迟加载**：仅当引入 provider/cache 层才有意义
4. **MCP 协议加载器**：把外部工具源翻译成 `Tool` + `register_tool`
   （机制已备，缺协议实现）

## 10. 修订记录

- 2026-08-01：初版。用户决定：动态工具（turn 快照生效、撞名报错、
  注册表不持久化）+ 可注入策略（管线组合、钩子 fail-loud）。实现安排：
  可注入并入 v1 阶段 5，动态工具为阶段 7。定位：pig-mono 式两层
  （框架层对应 pig-agent-core，coding agent 层对应 pig-coding-agent）；
  pig-mono 是 pi 的 Python 移植版、为直接参考。
