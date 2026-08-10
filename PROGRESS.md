# 项目进度记录

学习项目：从零搭一个最小 agent 框架（参考 pi / pig-mono）。**透明度优先于通用性，不奔生产。**
本文件记录每个阶段做了什么、改了哪些文件、验证方式，方便复盘。

## 当前结构（2026-08）

```
my-pi-agent/
├── packages/
│   ├── my-agent-core/     # 框架层（src 布局，Python 包 my_agent_core）
│   │   ├── tools.py       # Tool 类 + ToolResult + tool() 装饰器
│   │   ├── registry.py    # ToolRegistry（注册表）
│   │   ├── events.py      # 事件 dataclass（8 个，继承 Event 基类）
│   │   ├── agent.py       # Agent 类（单层：循环 + 工具执行）
│   │   └── main.py        # demo
│   └── my-agent-llm/      # 模型边界层（src 布局，Python 包 my_agent_llm）
│       ├── client.py      # LLM 门面（chat/stream/achat/achat_stream）
│       ├── config.py      # Config
│       ├── models.py      # Message / Response / StreamChunk
│       └── providers/     # openai / deepseek / anthropic
└── docs/superpowers/      # 本地设计文档 + 计划（不进 git）
```

---

## 已完成阶段

### 阶段 1：工具层 pydantic 化（2026-08-03）

**目标**：手写 `TYPE_MAP`（只支持 int/float/str/bool 四种标量）→ pydantic 动态建模。

- 规格：`docs/superpowers/specs/2026-08-03-pydantic-tool-schema-design.md`
- 提交：`f14f330` `19f40ba` `6666f0c` `964236e` `8638a33`
- **改了什么**：
  - 删除 `TYPE_MAP`；`@tool` 改用 `pydantic.create_model` 从函数签名动态建模
  - `Tool` 新增 `model` 字段——schema 生成与参数校验共用同一个 pydantic 模型
  - `call_tool` 执行前用 `model_validate` 校验 + 类型强转（`"37"` → 37）
  - 参数类型支持 pydantic 全集（list/dict/Optional/嵌套/默认值）
  - 新增 `tests/test_tools.py`（tests/ 首个文件）
- **过程中的关键教训**：规格假设「pydantic v2 默认严格区分 bool/int」被实测证伪（lax 模式接受 bool→int），补了 `BeforeValidator` 守卫。
- **验证**：21 个离线测试全绿，demo 真实运行通过（703 / 时间 / 天气）。

### 阶段 2：删 bool 守卫（2026-08-03）

**目标**：用户决定宽松——不拦 bool→int 强转，换更少代码。

- 提交：`3b83cd1` `bf6c263`
- **改了什么**：删 `_reject_bool_*` / `_NUMERIC_GUARDS`；`true` 传给 int 参数被强转成 1。
- **验证**：测试 21 → 20（删 `bool_not_accepted_as_int`）。

### 阶段 3：工具层类化重构（2026-08-03）

**目标**：`dataclass Tool + 自由函数` → `Tool 类 + ToolResult + ToolRegistry`（对齐 pig-mono 旧版形态）。

- 规格：`docs/superpowers/specs/2026-08-03-tool-class-design.md`
- 提交：`926d88c` `d7b8c57` `3c26139` `57ad571`
- **改了什么**：
  - `Tool` 改为类：`to_openai_schema()` / `execute()` / `__call__`，支持 `name`/`description`/`params_model` 覆盖
  - 新增 `ToolResult`（ok/data/error + serialize，永不抛）
  - 新增 `registry.py`：`ToolRegistry`（register/unregister/get/get_schemas/execute(tool_call)）
  - `agent.py` 改用 registry；删除 `schemas_for` / `call_tool` 自由函数
  - `tool()` 改为工厂装饰器（支持 `@tool` 与 `@tool(name=...)`）
- **过程中的关键教训**：最终评审抓到一个真实回归——Task 2 删 `call_tool` 时 `agent.py` 签名的 `list[Tool]` 注解悬空引用，`get_type_hints` 会 NameError（补回 import 修复）。
- **验证**：29 个离线测试全绿（test_tools 18 + test_registry 11）。

### 阶段 4：删翻译函数（2026-08-03）

**目标**：用户决定去掉 `_clean_schema` / `_format_validation_error` 两个翻译层，schema 与错误消息直接用 pydantic 原始输出。

- 提交：`6df40fc`
- **改了什么**：`to_openai_schema()` 直接返回 pydantic 原始 schema（带 title）；`execute` 校验失败直接 `str(exc)`。
- **验证**：测试相应调整后全绿（schema 断言改逐字段、错误断言匹配 pydantic 原文）。

### 阶段 5：目录重组（2026-08-03）

**目标**：`my_agent_core/` 移入 `packages/my-agent-core`（src 布局，独立 uv 项目），对齐 pig-mono 的 monorepo 结构。

- 提交：`603380f` `0e8bb4b`
- **改了什么**：
  - 包移入 `packages/my-agent-core/`，src 布局 + hatchling 构建
  - pyproject name 改为 `my-agent-core`
  - **过程中解决的坑**：加 `[build-system]` 后 `dependencies` 一度被 Edit 错放进 `[tool.hatch.build.targets.wheel]` 段导致依赖装不上（修正归位）
  - `.gitignore` 加入 `CLAUDE.md` 与 `docs/superpowers/`（本地私有文档，不上传远程 GitHub）
- **验证**：29 个测试全绿，demo 运行链通（429 配额限制除外）。

### 阶段 6：模型边界层 `my-agent-llm`（2026-08-03）

**目标**：独立「模型边界层」包——统一 `LLM` 类屏蔽 provider 差异，三 provider（openai/deepseek/anthropic）。

- 规格：`docs/superpowers/specs/2026-08-03-my-agent-llm-design.md`
- 提交：`2e8d53c` `d41b272` `2b1d4ef` `5b5ae4b` `dfe3ef0` `822517a` `3ca1356`
- **改了什么**：
  - `LLM` 门面：`chat`/`stream`/`achat`/`achat_stream` + 按 provider 路由 + kwargs 透传（只透传不碰 SDK）
  - `Config`（pydantic frozen）；`Message`/`Response`/`StreamChunk` 数据模型（tool_calls 统一 OpenAI 形状）
  - `OpenAIProvider`（基准翻译）→ `DeepSeekProvider`（继承 + reasoning_content 提取）→ `AnthropicProvider`（block 双向翻译 + web_search 增强）
  - 假 SDK 注入测试缝隙（`client=` 参数），全部离线测试
- **过程中的关键教训**：
  - 最终评审抓到 **Critical：`achat_stream` 异步生成器契约**——基类声明协程语义、provider 实现异步生成器，内部矛盾（裁定统一为异步生成器）
  - 修复波次又引入 **回归：`LLM.chat` 注入 `max_tokens=None` 废掉 anthropic 4096 回落**（复审抓到，第二轮修复为源头不注入）
- **验证**：33 个离线测试全绿，无 warning。

### 阶段 6.1：流式 tool_calls 聚合修复 + 注册表拆分（2026-08-06，未提交）

**目标**：修复「openai/deepseek 流式不聚合 tool_calls」的文档违约；顺带拆出 provider 注册表、补基类构造契约。

- **改了什么**：
  - `providers/registry.py`（新增）：`PROVIDER_REGISTRY` 注册表从 `client.py` 拆出（跨模块引用，去下划线正名）
  - `_base.py`：补抽象 `__init__(self, config: Config)` 构造契约；`achat_stream` 抽象标记 `yield` 改 `yield StreamChunk(content="")`（修 pyright 返回类型）
  - `openai.py`：新增模块级 `_ToolCallAccumulator`（按 index 聚合增量 tool_calls 片段）；`stream`/`achat_stream` 聚合 tool_calls + 捕获 usage，结束补发末块
  - `deepseek.py`：复用 `_ToolCallAccumulator`，流式聚合 tool_calls + usage + reasoning；四个覆盖方法参数注解补齐（与 openai 基准一致）
  - 新增 3 个流式聚合测试（openai 同步 / openai 异步 / deepseek 带 reasoning），先红后绿
- **过程中的关键教训**：
  - 原注释「v1 简化：末块由调用方汇总」**无文档背书**——spec §7.2 与计划 docstring 都要求「末块带完整 tool_calls + usage」，是实现时静默偏离
  - OpenAI 兼容流式把 tool_call 分片送达（id/name 只出现一次、arguments 是碎片 JSON），必须按 index 键控拼接
  - pig-mono 内部流式**不一致**：openai 用 tool-aware 完整版，deepseek/azure/groq 用 `iter_openai_stream_choices` 简版（只有文本、`break` 在 finish_reason、吃不到 usage）。我们两端对齐到完整版，deepseek 比 pig-mono 的还完整
- **验证**：my-agent-llm 33→36 测试全绿；my-agent-core 34 测试不受影响。

### 阶段 7：agent 层接入 `my-agent-llm`（已完成）

**目标**：`run_agent` 从裸 `openai.OpenAI` 改为用统一 `LLM` 类 + `Message`。

- 规格：`docs/superpowers/specs/2026-08-03-agent-llm-integration-design.md`
- 提交：`6035bdc` `f9138cd` `本次提交`
- **改了什么**：
  - `run_agent` 签名 `client+model` → `llm` 对象；messages 从 wire dict → `list[Message]`
  - `ToolRegistry.execute` 收协议 dict（`tool_call["function"]["name"]`），agent 直接喂 `Response.tool_calls`
  - `main.py` `build_client()` → `build_llm()`（`.env` 映射到 `Config`）
  - 新增 `tests/test_agent.py`（假 LLM 离线测循环）
- **过程中的关键教训**：`Response.tool_calls` 是协议 dict 而非 SDK 对象——registry 接口从「属性对象」改为「dict」以对齐，避免 agent 里造中间形状。
- **验证**：`uv run python -m pytest -q` 全绿（34 个）；demo 链路通到真实 API 但被 401 拦下（`.env` key 失效/过期），最终答案未验证。

### 阶段 8：单层 Agent 类 + 事件（2026-08-06）

**目标**：`run_agent` 函数 → pig-mono 式单层 `Agent` 类（状态 + 循环 + 工具执行），适配 my-agent-llm。

- 规格：`docs/superpowers/specs/2026-08-01-my-agent-framework-design.md`（2026-08-06 修订版）
- 计划：`docs/superpowers/plans/2026-08-06-single-agent-class.md`
- 提交：`30bbf51` `58bacf9` `ee13328` `229096d` `ef94c74` `e1b9629`（worktree 分支 `worktree-phase2-single-agent`）
- **改了什么**：
  - `agent.py`：`run_agent` → `Agent` 类（`run`/`reset`/`_prepare_tool`/`_execute_tool`）；`loop.py`/`llm.py` 不存在（单层）
  - `events.py`（新增）：8 个事件 dataclass，`AssistantMessageAdded.message` 为 `Message` 对象
  - 中间件：`_prepare_tool`（解析 + `before_tool` 拦截/改写）+ `_execute_tool(tc, args)`（执行 + `after_tool`），拦截用 `raise ToolBlocked`
  - `main.py` demo 改用 `Agent` + `on_event` 打印循环过程
  - `__init__.py` 导出公共 API（`Agent`/`tool`/`Tool`/`ToolResult`/`ToolRegistry`/`ToolBlocked`/事件）
  - 测试：`test_agent.py` 迁移 + 扩充（5→13），新增 `test_events.py`（10）
- **过程中的关键教训**：
  - 单层形态下循环无法脱离 Agent 独立测试，测试缝隙靠注入鸭子类型 `FakeLLM`（`Agent(llm=FakeLLM(...))`）保住；`LLM.chat` 本身就是缝隙，不需要抽象 `llm_call` 函数
  - 工具执行复用 `ToolRegistry.execute` 外包中间件，不手写六段管道；`before_tool` 改写 args 需重序列化回协议 dict（`registry.execute` 内部会重解析）
  - **ToolCallStart 时序回归**：把 `_execute_tool` 设计成「一把梭执行完才返回 args」导致 start 事件在工具执行后发射——评审抓出，拆 `_prepare_tool` + `_execute_tool` 两阶段修复
  - `run()` 裸 `json.loads` 打穿「永不抛」——畸形 JSON 参数会让循环崩溃，解析收敛进 `_prepare_tool` 由守卫兜住
- **验证**：`uv run python -m pytest -q` 全绿（53 个：17+12+8+10，agent 8→13）；demo 真跑三题通过（703 / 时间 / 双城天气）。

### 阶段 8.1：事件集对齐 pi 生命周期（2026-08-06）

**目标**：事件集 8→10，对齐 pi 的生命周期模型（Agent/Turn/Message/Tool 四组成对）。

- 计划：`docs/superpowers/plans/2026-08-06-event-lifecycle-refactor.md`
- 提交：`4f1ead8` `9fa879b`（worktree 分支 `worktree-event-lifecycle`）
- **改了什么**：
  - `events.py`：删 `AssistantMessageAdded`；加 `TurnEnd`/`MessageStart`/`MessageUpdate`/`MessageEnd`/`ToolExecutionUpdate`；`ToolCallStart`/`ToolCallEnd` 改名 `ToolExecutionStart`/`ToolExecutionEnd`；`AgentEnd` 加 `messages`（4 字段，messages 在前）
  - `agent.py`：`run()` 按 pi 时序发射——`MessageStart/End` 对 user/assistant/tool 都发，`ToolExecution*` 代替 `ToolCall*`，`TurnEnd(message, tool_results)` 每轮结束发，`AgentEnd` 带 messages 副本
  - `main.py`/`__init__.py`：demo 打印 + 公共 API 同步新事件（含 `emit` 导出）
- **过程中的关键教训**：`MessageUpdate`/`ToolExecutionUpdate` 为异步流式预留（同步不发射）；`MessageStart/End` 对每条进 transcript 的消息都发（pi 语义，非仅 assistant）；中间态下 `__init__.py` 引用旧事件会让全量 pytest 收集失败——重命名事件时消费点（`__init__`/`main.py`）须同 commit 同步
- **验证**：`uv run python -m pytest -q` 全绿（58 个：17+12+14+15）；demo 真跑三题通过（print_events 用新事件名）。

### 阶段 8.2：hook 统一（事件+中间件 → hook 注册表，2026-08-06）

**目标**：扩展机制从「事件观察（on_event）+ 中间件干预（before_tool/after_tool/ToolBlocked）」统一为「hook 注册表」（仿 CC）。

- 计划：`docs/superpowers/plans/2026-08-06-hook-unification.md`
- 提交：`adbb49c` `5a7cb37` `21b9c50` `e3ba480`（worktree 分支 `worktree-hook-unification`）
- **改了什么**：
  - `events.py`：加 `HookResult`（block/reason/updated_args/updated_result）+ `Interceptable` 标记；`ToolExecutionStart/End` 继承 `Interceptable`（可被 hook 干预）
  - `agent.py`：删 `on_event`/`before_tool`/`after_tool` 参数；加 `_hooks` 注册表 + `register_hook`/`unregister_hook`/`_emit`；`_prepare_tool`/`_execute_tool` 用 HookResult（拦截/改参数/改结果）
  - `tools.py`：删 `ToolBlocked`
  - `main.py`/`__init__.py`：demo 用 `register_hook`；公共 API 加 `HookResult`/`Interceptable`
- **过程中的关键教训**：
  - hook 回调返回 None = 纯观察、返回 HookResult = 干预；同一事件可挂多个 hook、非 None 短路
  - `ToolExecutionStart/End` 触发点移入 `_prepare_tool`/`_execute_tool`（干预结果要在工具执行前/后拿到）
  - **hook 异常语义分裂**：工具路径 hook 异常转错误字符串（保住「tool_calls 必配对」不变式），观察路径 hook 异常向上抛（视为使用方 bug）——设计文档 §4.2/§8 原先自相矛盾，本次消解
- **验证**：`uv run python -m pytest -q` 全绿（63 个：17+12+14+20）；demo 真跑三题通过（multiply=703 / 时间 / 双城天气）。

---

## 未来路线（v1 路线图，见 `packages/my-agent-core/README.md`）

- 阶段 2：单层 `Agent` 类 + 事件（已完成）
- 阶段 3：session 管理
- 阶段 4：context 管理
- 阶段 5：skill 机制
- 阶段 6：动态工具
- coding agent 层（`my_coding_agent`）——框架层完成后
