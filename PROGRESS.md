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
│   │   ├── events.py      # 事件 dataclass（10 个，继承 Event 基类）
│   │   ├── agent.py       # Agent 类（单层：循环 + 工具执行 + hook 注册表）
│   │   ├── session.py     # SessionEntry + SessionTree + Session（树 + JSONL 原子落盘）
│   │   ├── session_store.py  # SessionStore（会话仓库，workspace 隔离）
│   │   ├── context.py     # ContextManager（四层压缩管线：落盘/裁中间/占位/摘要）
│   │   └── main.py        # demo
│   └── my-agent-llm/      # 模型边界层（src 布局，Python 包 my_agent_llm）
│       ├── client.py      # LLM 门面（chat/stream/achat/achat_stream）
│       ├── config.py      # Config
│       ├── models.py      # Message / Response / StreamChunk
│       └── providers/     # openai / deepseek / anthropic
```

---

## 已完成阶段

### 阶段 1：工具层 pydantic 化（2026-08-03）

**目标**：手写 `TYPE_MAP`（只支持 int/float/str/bool 四种标量）→ pydantic 动态建模。

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
  - `.gitignore` 加入 `CLAUDE.md`（本地私有文档，不上传远程 GitHub）
- **验证**：29 个测试全绿，demo 运行链通（429 配额限制除外）。

### 阶段 6：模型边界层 `my-agent-llm`（2026-08-03）

**目标**：独立「模型边界层」包——统一 `LLM` 类屏蔽 provider 差异，三 provider（openai/deepseek/anthropic）。

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

- 提交：`4f1ead8` `9fa879b`（worktree 分支 `worktree-event-lifecycle`）
- **改了什么**：
  - `events.py`：删 `AssistantMessageAdded`；加 `TurnEnd`/`MessageStart`/`MessageUpdate`/`MessageEnd`/`ToolExecutionUpdate`；`ToolCallStart`/`ToolCallEnd` 改名 `ToolExecutionStart`/`ToolExecutionEnd`；`AgentEnd` 加 `messages`（4 字段，messages 在前）
  - `agent.py`：`run()` 按 pi 时序发射——`MessageStart/End` 对 user/assistant/tool 都发，`ToolExecution*` 代替 `ToolCall*`，`TurnEnd(message, tool_results)` 每轮结束发，`AgentEnd` 带 messages 副本
  - `main.py`/`__init__.py`：demo 打印 + 公共 API 同步新事件（含 `emit` 导出）
- **过程中的关键教训**：`MessageUpdate`/`ToolExecutionUpdate` 为异步流式预留（同步不发射）；`MessageStart/End` 对每条进 transcript 的消息都发（pi 语义，非仅 assistant）；中间态下 `__init__.py` 引用旧事件会让全量 pytest 收集失败——重命名事件时消费点（`__init__`/`main.py`）须同 commit 同步
- **验证**：`uv run python -m pytest -q` 全绿（58 个：17+12+14+15）；demo 真跑三题通过（print_events 用新事件名）。

### 阶段 8.2：hook 统一（事件+中间件 → hook 注册表，2026-08-06）

**目标**：扩展机制从「事件观察（on_event）+ 中间件干预（before_tool/after_tool/ToolBlocked）」统一为「hook 注册表」（仿 CC）。

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

### 阶段 3：session 管理（2026-08-10）

**目标**：会话持久化——树结构 + rewind + fork + 跨进程续聊 + 多会话仓库 + workspace 隔离（pig-mono/pi 式）。

- 提交：`dc6a0a8` `28625a0` `8ae1f25` `abdc90b` `04ba33e` `2684ab3` `c5527e4` `adfa02b` `a51978d` `ee8dca3`（worktree 分支 `session-management` → `session-fork` → `session-store-rename` → `session-no-version` → `session-workspace`）
- **改了什么**：
  - `session.py`（新增）：`SessionEntry`（pydantic，id/parent_id/timestamp/role/content/metadata）+ `SessionTree`（entries + current_id 指针；add_entry / get_current_path / get_path_to_entry / rewind）+ `Session`（add_message 逐条原子全量重写 / load / get_current_path_messages / rewind / reset）
  - `session_store.py`（新增，原名 store.py）：`SessionStore` —— create / list（倒序）/ open（前缀匹配 + 歧义报错）/ delete / fork；id = 时间戳-hex，碰撞重试
  - `agent.py`：`session=` 参数（有则 run() 内逐条落盘、构造/续跑时恢复上下文；无则纯内存向后兼容）；`reset()` 同步清树重写文件
  - 文件格式：header 行（id/created_at/cwd/current_id/root_id）+ entry 行 JSONL；`type/version` 已删
  - workspace 隔离：会话目录 = `<workspace>/.my_agent_core/sessions`（pig-mono 式），跨项目天然隔离
  - `__init__.py`/README：导出 Session/SessionTree/SessionStore；阶段 3 勾选
- **过程中的关键教训**：
  - 树 + 指针：rewind = 改 `current_id` 一个变量，旧分支留档可无限切回；上下文 = 沿 parent 回溯的路径；只存 parent_id 是回溯路径的最小实现（down 遍历用 entries 全量扫描）
  - 原子写：临时文件 + fsync + os.replace——任何时刻崩溃文件都是完整快照；每次 add_message 全量重写换崩溃安全
  - fork 在仓库层（路径生成是 Store 的职责，与 create 一致）；pig-mono 的 fork 在 Session 层是因它的 Session 自己管路径
  - **plan bug**：测试用 `s1.id[:12]` 前缀在同秒 create 时确定性歧义（id 前 15 字符是时间戳），改 `[:20]` 修复（reviewer 确认无更优替代）
  - **final review 抓到 F1**：同 Agent rewind 后续跑内存 messages 不重同步 → LLM 收到含废弃分支尾的矛盾上下文；修 `run()` 开头同步到 session 当前指针（非 rewind 情形幂等）
  - **final review 误判驳回 F2**：声称 max_iterations 耗尽时文件有孤儿 assistant(tool_calls)——核实 for 循环在 while 体内必然执行、tool 消息必然落盘，配对完整
  - type/version 是冗余标签：防误读的硬防线是目录隔离（glob *.jsonl）+ 必要字段校验（load 要求 id/created_at 存在）
  - workspace 隔离（pig-mono 式）：root 为绝对路径时直接用（测试兼容），相对时解析为 workspace/root
- **验证**：`uv run python -m pytest -q` 全绿（86 个：原 63 + session/store 23）。

### 阶段 4：context 管理（2026-08-11）

**目标**：超 budget 上下文自动压缩——四层管线（L3 落盘 → L1 裁中间 → L2 占位 → L4 摘要）+ usage 锚定估算 + retainedTail 缓存，Agent 集成压缩策略、事件通知与会话内缓存持久化。

- 提交：`4b5925f` `168168b` `e74a610` `014b0ba` `575da36`（worktree 分支 `context-management`）
- **改了什么**：
  - `session.py`：`SessionEntry` 加 `type` 字段；新增 `add_summary_cache` / `get_full_history_messages`；`rewind` 加护栏
  - `context.py`（新增）：`ContextManager` 四层管线（L3 落盘 → L1 裁中间 → L2 占位 → L4 摘要）+ usage 锚定 + retainedTail 缓存（prepare / 缓存复用 / 迭代再摘要 / 摘要失败降级不压缩）
  - `agent.py`：`context_budget=` 参数、`run()` 内 prepare、`compact()` 手动触发、`ContextCompacted` 事件发射
  - `__init__.py` / README：导出 `ContextManager`；阶段 4 勾选
- **过程中的关键教训**：
  - 摘要消息必须 user 角色且 persona 保留（设计文档 §2.2，fix round 1）
  - snip off-by-one（占位符计数）
  - force_compact 需强制 cut（"无条件摘要"）
- **验证**：`uv run python -m pytest -q` 全绿（108 个：原 86 + context/agent 22）；`from my_agent_core import ContextManager` 导入通过。

---

## 未来路线（v1 路线图，见 `packages/my-agent-core/README.md`）

- 阶段 2：单层 `Agent` 类 + 事件（已完成）
- 阶段 3：session 管理（已完成）
- 阶段 4：context 管理（已完成）
- 阶段 5：skill 机制
- 阶段 6：动态工具
- 阶段 7：memory 记忆系统
- 阶段 8：task 系统（todo + plan 核心，框架层）
- 阶段 9：MCP 与 plugin
- coding agent 层（`my_coding_agent`）——框架层完成后（含 plan 模式交互层）
