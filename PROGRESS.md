# 项目进度记录

学习项目：从零搭一个最小 agent 框架（参考 pi / pig-mono）。**透明度优先于通用性，不奔生产。**
本文件记录每个阶段做了什么、改了哪些文件、验证方式，方便复盘。

## 当前结构（2026-09）

```text
my-pi-agent/
├── pyproject.toml                  # ⭐ 全局统一的 Python 构建与依赖配置 (uv)
├── uv.lock                         # 全局唯一的 Python 依赖锁定文件
├── .venv/                          # 全局唯一的 Python 虚拟环境
│
├── src/                            # ⭐ 统合的 Python 业务源码 (完全对标 Tau)
│   ├── my_agent_llm/               # 1. 统一 LLM 直连层 (Antigravity/DeepSeek/OpenAI/Stream)
│   │   ├── client.py               # 统一 LLM 门面 (chat/stream/achat/achat_stream)
│   │   ├── config.py               # Config 配置模型 (pydantic frozen)
│   │   ├── models.py               # Message / Response / StreamChunk
│   │   └── providers/              # Antigravity (Google OAuth) / DeepSeek / OpenAI
│   │
│   ├── my_agent_core/              # 2. 框架微内核层 (ReAct/会话树/压缩/任务系统)
│   │   ├── agent.py                # Agent 纯异步 Harness 外壳
│   │   ├── loop.py                 # run_agent_loop 纯函数无状态微内核与七阶段流水线
│   │   ├── tool_history.py         # 对话转录本三阶段自愈引擎 (API 400 免疫)
│   │   ├── message_queue.py        # MessageQueue 动态干预队列 (Steer & Follow-up)
│   │   ├── task_store.py           # TaskStore 任务状态机与 DAG 依赖图
│   │   ├── background.py           # BackgroundRunner 进程树清理引擎
│   │   ├── session/                # 树状分支持久化会话系统
│   │   ├── context.py              # ContextManager 四层压缩管线 (L3->L1->L2->L4)
│   │   └── skills.py               # Skills 声明式管理与提示词注入
│   │
│   └── my_coding_agent/            # 3. 业务工具与 stdio RPC 服务端 (纯无头架构)
│       ├── agent.py                # CodingAgent 门面 (Dual API: run & run_stream)
│       ├── tools/                  # 7 大编码工具 (read/write/edit/bash/grep/find/ls)
│       ├── mutation_queue.py       # FileMutationQueue 细粒度单文件并发互斥锁
│       ├── permissions.py          # PermissionGate 业务权限审查门禁 (Accept-on-Diff)
│       ├── mcp.py                  # Turnkey MCP 客户端自动加载与回收
│       ├── file_reference.py       # @ 文件引用解析与快照直通注入
│       └── rpc_server.py           # stdio JSON-RPC 2.0 服务端门面
│
├── tests/                          # ⭐ 全局统一测试目录 (uv run pytest 跑完全部)
│   ├── llm/                        # LLM 层单元测试 (76 tests)
│   ├── core/                       # 框架内核单元测试 (337 tests)
│   └── coding/                     # 业务与工具测试 (252 tests)
│
├── tui/                            # ⭐ 独立的终端交互表现层 (基于 @earendil-works/pi-tui)
│   ├── package.json                # 依赖 @earendil-works/pi-tui, chalk, marked
│   ├── tsconfig.json
│   ├── bin/
│   │   └── my-agent.js             # CLI 启动命令入口
│   ├── src/
│   │   ├── app.ts                  # TuiMainScreen 状态机与组件树组装
│   │   ├── client.ts               # PythonKernelClient (管理 uv run python 子进程)
│   │   ├── components/             # Pi 原厂 UI 组件 (CustomEditor, status-indicator, footer...)
│   │   └── theme/                  # Pi 原厂 24-bit TrueColor dark.json 调色盘
│   └── test/                       # 前端 58 个自动化与端到端测试用例
│
├── docs/                           # 统一设计文档中心
├── package.json                    # 根目录 npm 工作区配置与一键启动脚本
├── REFERENCES.md                   # 架构设计参考溯源与工程复盘
└── README.md                       # 快速开始与全景总览
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

### 阶段 5：skill 机制（2026-08-13）

**目标**：框架层支持 skill——声明式 `.md` 文件（frontmatter + 正文），发现 / 清单格式化 / 显式调用。

- 提交：`66eab8d` `6d7a8e7` `0728b1a` `d0c6785` `ad5030d` `fc47f63` `e367523`（+ docs `ef00e91` `2c7edca`）
- **改了什么**：
  - `skills.py`（新增）：`Skill` 数据模型 + `parse_frontmatter`（PyYAML，坏 YAML 静默降级）+ 发现（pig-mono 式一层子目录 + `name=目录名` + 缺 description 跳过）+ 清单 XML 格式化 + `format_invocation` 显式调用包装
  - `Agent` 集成：`skill_dirs` 三态（None→探测 `.agents/skills` / []→禁用 / 非空→目录）+ system 清单块 + `invoke_skill(name)` 显式调用
  - 收尾 `e367523`：skill 机制改为 Repository 类管理（`SkillManager` 收编发现/查询/格式化，对标 pig-mono）
- **关键教训**：模型侧无 read 工具 → skill 正文只能由宿主 `invoke_skill` 显式注入（不预置 read_skill）；`SKILL.md` 兼容 UTF-8 BOM（utf-8-sig 读取，零副作用）。
- **验证**：全量测试全绿。

### subagent 机制（2026-08-15/16，另列）

**目标**：声明式子代理——`agents/*.md` + frontmatter 定义，宿主/模型经 `task` 工具委派。

- 提交：`ffb583d` `e4fc6d0` `f10c900` `2b7f08d` `3a04913` `0494be3`
- **改了什么**：
  - `subagents.py`（新增）：`Subagent` 数据模型 + `SubagentManager`（发现 agents/*.md，frontmatter camelCase→snake_case 映射）+ 清单格式化 + `DEFAULT_SUBAGENT`
  - `Agent` 集成：`subagent_dirs` 三态 + system 清单块 + `model`/`effort` 参数透传（子代理换模型前置）
  - 内置 `task` 工具（`make_task_tool`）：spawn 子 Agent、fresh context、只回最终文本、工具过滤 + 防递归
- **关键教训**：防递归靠「子代理 `subagent_dirs=[]` 不装配 task 工具」一刀切；effort 降级为 deferred（OpenAI SDK 用 reasoning_effort、Anthropic 用 thinking，无统一 `effort` kwarg）。
- **验证**：149 个测试全绿。

### Task 委派系统 + builtin 包化（2026-08-16）

**目标**：委派从「一个函数」升级为 Task/TaskStatus/TaskManager 生命周期（对标 OpenHands）；tools.py 升级为 tools/ 包。

- 提交：`289d52a` `28f5c4a` `6be1858`
- **改了什么**：
  - `tasks.py`（新增）：`Task`（result/error）+ `TaskStatus`（RUNNING/COMPLETED/FAILED 三态）+ `TaskManager`（start_task → 生命周期）
  - `make_task_tool` 工具桥化（调 TaskManager → 转字符串）
  - `tools.py` → `tools/` 包 + `tools/builtin.py` 收内置工具工厂
- **验证**：154 个测试全绿。

### 四个文件工具（2026-08-16）

**目标**：框架层 builtin 补 pi 的四个基本工具 read/edit/write/bash（反转「归属 coding agent 层」决策）。

- 提交：`0a45b9a` `a2de9c3` `5a9608e`（+ docs `2931834`）
- **改了什么**：
  - `builtin.py` → `builtin/` 包（`task.py` + `files.py`）
  - `files.py`：`_safe_path`（resolve + is_relative_to 路径逃逸）+ 四个工厂 `make_read/make_write/make_edit/make_bash_tool`（收 `root`）+ bash 危险命令黑名单 + 120s 超时
- **关键教训**：`_safe_path` 必须 `Path(root).resolve()`（symlink/相对 root 会 false-block）；bash 超时测试跨平台（`sleep 5` 非 cmd.exe 命令，改 `python -c "import time; time.sleep(5)"`）。
- **验证**：全量测试全绿。

### 组件装配重构（2026-08-16）

**目标**：Agent 结构优化——工具注册统一、hooks 统一、context 默认启用、方法重排。

- 提交：`e96a9ad` `05f9991` `7ffeaa3` `6980f17` `59bb219` `abed0c6` `f1b81bf` `4bc13cf` `bd9eed4`
- **改了什么**：
  - `_register_tools` 统一注册（用户工具 + 内置 task）
  - hooks 抽成 `HookRegistry` 类（对标 ToolRegistry）+ 改为构造参数 `hooks=[(事件类, 回调)]` 批量注册（去掉 register_hook/unregister_hook 公共 API）
  - `context` 默认启用（budget 默认值下沉 ContextManager=100k，Agent 不传用组件默认）
  - 装配外移试过后撤回（`_init_messages`/`_init_context` 写回 agent.py 内部方法）；方法按「构造/公共 API/内部实现」三组重排
- **验证**：全量测试全绿（纯重构无新增）。

### session 统一持久化 + system 归 Agent（2026-08-16）

**目标**：system 从「session 持久化内容」改为「Agent 运行时配置」，session 只存纯对话；子代理独立持久化。

- 提交：`a0fbbbf` `8809e48` `4fb888f` `2ef28c7` `6eb19dd`
- **改了什么**：
  - `Session` 去 `system_prompt`（只存纯对话，metadata 参数塞 header）；`reset()` 清空树
  - `Agent` 拼 system（`system_prompt` + skill 清单 + subagent 清单合成消息首条）；`session` 必填（去掉内存模式）
  - 子代理独立 session 落盘 `subagents/`（meta 塞 header：agent_type/spawn_depth/parent_session_id），对齐 Claude Code 子代理持久化目录
  - `run()` rewind-sync 保留 system 首条 + 同步纯对话（否则 rewind 后 system 丢失）
- **关键教训**：system=agent 定义、session=运行历史（对齐 anthropic-sdk-python 的 `agents.create(system=...)` 与 Claude Code 子代理目录）；防污染断言曾恒真，改成真检测父 session 不含子代理 user 消息。
- **验证**：165 个测试全绿。

### 阶段 9：extension 机制（2026-08-17）

**目标**：外部 `.py` 扩展加载——事件订阅 + 工具注册 + 命令（对齐 pig-mono extensions.py）。

- 提交：`09b7527` `082d75a` `4ba9183` `8976097`
- **改了什么**：
  - `extensions.py`（新增）：`ExtensionAPI`（on 事件订阅 / tool 工具注册 / command 命令三件套）+ `ExtensionManager`（discover / load_extension / load / handle_command）
  - 事件订阅复用 `HookRegistry`（类型化事件 + 双参 handler `(event, api)`，返回 `HookResult` 干预）；工具注册复用 `@tool`；命令查表调度（0/1 参自适应）
  - `Agent` 接入：`extension_dirs` 三态构造参数，加载在 `_register_tools` 之后（extension 工具可覆盖内置工具）；坏扩展隔离（print 不抛）
- **关键教训**：plan 测试 #8 笔误（命令注册在独立 ExtensionAPI 却用新 ExtensionManager 调，必抛 ValueError），implementer 修正确认；final review 抓「extension 覆盖内置工具零测试」，补覆盖测试锁住「后加载覆盖」语义。
- **验证**：182 个测试全绿（17 个 extension 测试 + 既有 165）。

### 阶段 9.2：基于 Extension 的 MCP 客户端扩展（2026-08-17）

**目标**：基于 `ExtensionAPI` 机制实现 MCP 客户端扩展——Stdio 子进程长连接、同步/异步线程事件循环桥接、`Tool` 解耦与 `raw_schema` 增强、`.mcp.json` 工作区配置加载。

- 提交：`950d528` `222754c` `d52764f` `300a742` `1fa10ed`
- **改了什么**：
  - `tools/__init__.py`：`ToolResult` 增加 `meta: dict[str, Any]`；`Tool` 增加 `raw_schema: dict | None` 与 `timeout: float | None` 参数，解耦 Python 函数注解推导，直接支持外部 JSON Schema 协议转换与字典参数执行。
  - `mcp.py`（新增）：`MCPServerConfig`（配置模型）+ `MCPConnection`（后台线程 asyncio 事件循环长连接守护，跨线程阻塞 RPC 转发 `session.call_tool` 与超时防护）+ `MCPClientManager`（`.mcp.json` 读取解析、多 Server 批处理连接、`atexit` 优雅关闭）。
  - `__init__.py`：导出 `MCPClientManager`、`MCPConnection`、`MCPServerConfig`。
  - 测试：新增 `tests/test_mcp.py`（配置解析 + Stdio 握手与工具调用）与 `tests/test_mcp_extension_e2e.py`（端到端 FakeLLM 驱动 Agent ReAct 循环调 MCP 工具）。
- **过程中的关键教训**：
  - 同步/异步桥接：官方 `mcp` SDK 是基于 `asyncio` 的长连接上下文管理器，通过为每个 Server 维护一个后台守护线程与 `asyncio.run_coroutine_threadsafe(...).result(timeout=...)` 实现了干净、高效的同步跨线程调用。
  - 100% 离线测试：使用内联 Python 脚本作为 Stdio MCP Server 子进程，完全不依赖外部网络与外部 CLI 安装。
- **验证**：全量 223 个测试全绿（187 个 core 测试 + 36 个 llm 测试）。

### 阶段 10：框架层原生异步架构升级（2026-08-18）

**目标**：将 `my-agent-core` 从同步伪装全面重构为原生 `asyncio` 异步引擎，实现流式 Token 增量事件打字机、无污染 `agent.abort()` 熔断取消机制、声明式 `is_parallel_safe` 读写分流并发与严格保序回填、MCP 客户端彻底去多线程化（`AsyncExitStack`）。

- 提交：`c0fa31c` `422e4a1` `10e3bd4` `c1d41f3` `43c801e` `a5a3e87` `eef8a36` `9bb5018` `0dba2fc` `0cadeb1` `e006c7f` `8d0159b`
- **改了什么**：
  - `events.py`：`HookRegistry.emit(event)` 异步化（支持 `async def` 协程与同步 `def` 回调混合注册与短路拦截）；`MessageUpdate` 继承 `Interceptable` 并增加 `chunk` 字段，支持流式 Token 生成过程中的 Hook 实时熔断。
  - `tools/core.py` & `registry.py`：`Tool` 增加 `is_parallel_safe: bool = False`；`Tool.execute` 支持原生协程并用 `asyncio.to_thread` 自动桥接同步函数；`ToolRegistry.execute_batch` 实现**只读并发（`asyncio.gather`）+ 写入按序串行 + 严格保序回填**。
  - `context.py`：`prepare`、`force_compact`、`_do_summarize`、`_call_summarizer` 四层压缩管线异步化，使用 `await self.llm.achat` 生成 L4 摘要。
  - `agent.py`：核心 ReAct 循环重构为原生异步 `async def run(prompt)`，接入 `llm.achat_stream` 流式迭代；实现 `agent.abort()` 叫停机制（叫停时丢弃未完成半截内容，不写入 Session，发射 `AgentEnd(stop_reason="cancelled")`）；移除冗余同步入口 `run_sync`（提交 `6d20c1a`），保持纯粹原生异步 API。
  - `tasks.py` & `task.py`：`TaskManager.start_task` 与工具桥 `task` 异步化，标记 `is_parallel_safe=True`，支持父 Agent 一次性派发多个子代理并发并行执行。
  - `files.py` & `mcp.py`：`read` 标记为并发安全，`write/edit/bash` 标记为写入串行；MCP 客户端基于 `AsyncExitStack` 重写，彻底移除所有 `threading.Thread`、`threading.Event`、`run_coroutine_threadsafe` 等多线程代码（~60% 代码量缩减）。
  - `main.py`：升级为 `asyncio.run(amain())`，展示流式 Token 打字机打印与工具并发调用效果。
- **过程中的关键教训**：
  - 优雅叫停与脏上下文隔离：Cancel 发生时必须直接丢弃未完成的累积文本，不向持久化 Session 与上下文注入残缺内容，避免模型在下一轮对话中产生“续写断句”幻觉。
  - 并发执行与上下文严格保序：只读工具并发启动（如并发读取多个文件），写入工具串行；但最终回填给 `messages` 和 `session` 时按大模型原始 `tool_calls` 索引预分配插槽回填，确保历史记录严格确定性。
  - MCP 原生异步：基于 `AsyncExitStack` 进入 `stdio_client` 与 `ClientSession` 上下文，彻底消除了后台守护线程与跨线程事件循环的复杂性。
  - 接口纯粹性：砍掉容易滋生隐蔽死锁与线程池复杂性的 `run_sync` 同步桥接，全面拥抱 100% 原生异步协程。
- **验证**：全量 231 个离线测试全部 100% 绿灯通过（195 个 core 测试 + 36 个 llm 测试）。

### 阶段 11：my-coding-agent 产品层（2026-08-26）

**目标**：分层纠偏——新建 `my-coding-agent` 产品层（对应 pig-mono `pig-coding-agent`），把此前误放框架层的文件工具（read/write/edit/bash）与 MCP 从 `my-agent-core` 迁出，落到产品层并完成薄装配（`build_coding_tools` + `CodingAgent`）；subagent 机制保留框架层。

- 提交：`1663c63` `48d834f` `d66cb4b` `b681b8b` `d9d1134` `faa64ae`
- **改了什么**：
  - 新建 `packages/my-coding-agent`（src 布局）：`tools.py`（文件工具四工厂 + `_safe_path` 路径逃逸 + bash 黑名单，原样迁自 files.py）、`mcp.py`（`MCPServerConfig`/`MCPConnection`/`MCPClientManager` + `extension(api)` 入口，原样迁自 extensions/builtin/mcp.py，保持 extension 形态）、`agent.py`（`build_coding_tools(workspace)` 返 4 工具 + `CodingAgent` 薄封装，构造自动装配文件工具并委托框架 `Agent.run`）、`__init__.py`、`pyproject.toml`（依赖 my-agent-core / my-agent-llm / mcp）。
  - 框架层瘦身：`my-agent-core` 删 `tools/builtin/files.py`（builtin 只留 `task` 委派工具）、删 `extensions/builtin/`（原 MCP 整个子包）、顶层 `__init__.py` 删 MCP 三件套导出、`pyproject.toml` 删 `mcp>=2.0.0` 依赖。
  - mcp 版本对齐：my-coding-agent 的 mcp 约束锁 `>=2.0.0,<2.1`，与框架层此前锁的 2.0.0 一致。
  - 测试：新增 `tests/test_tools.py`（文件工具 10，迁自 test_files）、`test_mcp.py` + `test_mcp_extension_e2e.py`（MCP 4，迁入）、`test_agent.py`（产品层装配 4）。
- **过程中的关键教训**：
  - 分层边界（判据「去掉业务后这能力还有没有独立意义」）：文件工具是编码专属 → 产品层；subagent 委派是通用协作机制 → 框架层。此前 2026-08-16 把文件工具反转放框架层是「夹生态」，本次归位。
  - 依赖版本漂移：`mcp>=2.0.0` 在全新 uv 项目里意外解析到 2.1.1（框架层锁 2.0.0），导致「原样迁入」的 MCP 测试红 1 例；锁 `<2.1` 守住「移动不改逻辑」原则，而非去适配新版本行为。
- **验证**：三包离线测试全绿，总计 **235 个测试**（my-agent-core 181 + my-agent-llm 36 + my-coding-agent 18）。

### 阶段 12：Extension 五大决策点与生命周期拦截体系（2026-08-26）

**目标**：对标 Pi 源码讲解第 7 章，补齐扩展系统的 5 大生命周期决策拦截点（`input / before_agent_start / context / tool_call / tool_result`），使 Extension 具备全生命周期的双向干预与安全防护能力，同时坚守「不引入 UI 概念」、「保持真实 Session 零污染」的设计原则。

- 提交：`6f31e33` `b596d50` `302eac9`
- **改了什么**：
  - `events.py`：新增 `UserInput(Event, Interceptable)`、`BeforeModelCall(Event, Interceptable)`，升级 `AgentStart(Event, Interceptable)`（携带 `system_prompt` 与 `user_input` 字段）；`HookResult` 扩充 `updated_input`、`updated_system_prompt`、`updated_messages` 字段。
  - `agent.py`：在 `run()` 执行流中织入三大新拦截点：
    1. **决策点 1 (`UserInput`)**：在输入写入 Session 前触发，支持 `block=True` 拦截（不写历史）或 `updated_input` 改写输入；
    2. **决策点 2 (`AgentStart`)**：在准备好系统消息后触发，支持 `updated_system_prompt` 动态更新首条 system 消息；
    3. **决策点 3 (`BeforeModelCall`)**：在 `_ctx.prepare()` 产出 `view` 后、调用大模型前触发，支持 `updated_messages` 临时改写送给大模型的视图（`self.messages` 与 Session 磁盘保持绝对纯净）；
    4. **决策点 4 (`ToolExecutionStart`)** 与 **决策点 5 (`ToolExecutionEnd`)** 继续保持对工具的入参拦截与出参改写。
  - `extensions/core.py`：`ExtensionAPI.on` 补充 `@overload` 类型注解，保证 IDE 与类型检查器对装饰器语法的精准识别。
  - `__init__.py`：导出 `UserInput` 与 `BeforeModelCall`。
- **过程中的关键教训**：
  - 临时视图隔离（No Session Pollution）：扩展在 `BeforeModelCall` 中注入的临时提醒（如 `[EPHEMERAL WARNING]`）只作用于当前的 `view` 变量，绝不能追加进 `self.messages` 或 Session JSONL 磁盘文件，保证会话历史的真实确定性。
  - 缺省 System Prompt 兼容：当 Agent 构造时未传入 `system_prompt`（且无 skills/subagents 清单）时，`self.messages` 首条无 system 消息；当扩展返回 `updated_system_prompt` 时，自动在 `self.messages[0]` 处插入新的 system 消息。
- **验证**：三包离线测试全绿，总计 **241 个测试**（my-agent-core 187 + my-agent-llm 36 + my-coding-agent 18）。

### 阶段 7：memory 记忆系统（2026-08-26）

**目标**：实现文件注入式 + 受控条目化长期记忆系统（对标 hermes-agent 精简版），让 Agent 拥有跨 Session 的持久化记忆能力。通过 `MEMORY.md`（Agent 笔记，2200 字符限制）与 `USER.md`（用户画像，1375 字符限制）双文件存储，启动时捕获 Frozen Snapshot 冻结注入 System Prompt 保证 Prefix Cache 稳定，并提供结构化的 `memory` 维护工具（`add/replace/remove`）防止模型裸写 Markdown 膨胀写乱。

- 提交：`80e0d60` `8fb8910` `6bb6239` `5bfca61` `b9a54f0` `9945fb0`
- **改了什么**：
  - `memory.py`（新增）：
    - `MemoryStore`：管理 `MEMORY.md` 与 `USER.md`，使用 `\n§\n` 条目切分与 `utf-8-sig`（容忍 Windows BOM）；启动时 `load_from_disk()` 捕获冻结快照 `_snapshot`；`add` 增量追加、`replace` / `remove` 唯原子串匹配定位；支持精确去重、超限拦截与提示、临时文件原子落盘（`tempfile.mkstemp` + `os.fsync` + `os.replace`）；`format_all_for_system_prompt()` 格式化为 `<MEMORY_CONTEXT>` 提示词块。
    - `make_memory_tool(store)`：使用 `@tool` 生成受控维护工具，接收 `target: Literal["memory", "user"]` 与 `action: Literal["add", "replace", "remove"]`，内部完成严格参数校验与分发，遵循 Never-Throw Guarantee。
  - `agent.py`：
    - `__init__` 新增 `memory_dir: str | Path | None | Literal[False] = None`（`None` 自动探测 `<cwd>/.my_agent_core/memory`，`False` 显式禁用，`str|Path` 指定目录）；
    - 在 `_register_tools` 前初始化 `MemoryStore` 并立即调用 `load_from_disk()` 冻结快照；
    - 在 `_register_tools` 中自动注册 `make_memory_tool(self.memory_store)`，用户传同名工具时抛 `ValueError` 防撞名；
    - 在 `_init_messages` 中将冻结快照拼入首条 system message；
    - 在 `reset()` 中调用 `self.memory_store.load_from_disk()` 重载磁盘并重拼 system 消息。
  - `__init__.py`：导出 `MemoryStore` 与 `make_memory_tool`。
  - 测试：新增 `tests/test_memory.py`（14 个测试用例，覆盖条目切分、BOM 读取、快照冻结不变性、唯原子串匹配与歧义检测、超限防护、工具 schema 与执行、Agent 自动探测与注入、禁用与冲突保护、端到端跨 Session 持久化与召回）。
- **过程中的关键教训**：
  - Frozen Snapshot 不变性：会话运行中大模型调用 `memory` 工具写入新条目时，只落盘更新磁盘与 live 数据，绝不修改当前会话的 System Prompt 内存快照，以此保持 LLM 提示词前缀哈希（Prefix Cache）的高度稳定，仅在下个 Session 启动或显式 `reset()` 时重载生效。
  - 唯原子串定位与歧义防护：在 `replace` 和 `remove` 操作中，要求 `old_text` 必须在当前 store 中唯一命中某一条目；若未命中或匹配到多条不同条目，返回清晰的匹配列表错误提示引导大模型提供更具体的文本。
- **验证**：三包全量 255 个离线测试全部 100% 绿灯通过（my-agent-core 201 + my-agent-llm 36 + my-coding-agent 18）。

### 阶段 13：Claude Code 风格 Plugin 插件系统（2026-08-26）

**目标**：实现 100% 对齐 Claude Code 官方规范与 OpenHands 实践的 Plugin 插件聚合分发系统（`PluginManifest` + `Plugin` + `PluginManager`）。支持自包含插件包（`.claude-plugin/plugin.json`、`skills/`、`agents/`、`.mcp.json`、`commands/` 兼容）以及根级单 `SKILL.md` 简写插件，由 `PluginManager` 统一扫描、Manifest 容错解析与子资源解构，并自动注入框架各底层 Manager（`SkillManager`、`SubagentManager`）。

- 提交：`9ad7b20` `2ceab5b` `6df9aa4` `be06008` `7995440` `ebf4a3a` `1d9a282`
- **改了什么**：
  - `plugins.py`（新增）：
    - `PluginAuthor` & `PluginManifest`：解析 Claude Code 官方 `plugin.json` 元数据，支持 `author` 字符串 `"Name <email>"` 与字典格式兼容；
    - `Plugin.from_directory()`：按顺序查找 `.claude-plugin/plugin.json` ➔ `.plugin/plugin.json` ➔ `plugin.json`；若无 manifest 或 JSON 损坏，自动以目录名推断默认 `PluginManifest(name=dir.name)`（智能兜底）；
    - 组件目录解构：`skills_dir`（优先 `skills/`，次选 `commands/`，根目录单 `SKILL.md` 时返回插件根）、`agents_dir`（`agents/`）、`mcp_config_path`（`.mcp.json`）；
    - `PluginManager`：支持三态目录扫描（`dirs=None` 探测 `.agents/plugins`，`dirs=[]` 禁用，`dirs=[Path]` 显式指定），识别单个插件目录或插件集合父目录，提供 `get_skill_dirs()`、`get_subagent_dirs()`、`get_mcp_config_paths()`。
  - `skills.py` & `subagents.py`：
    - `SkillManager` 与 `SubagentManager` 新增 `extra_dirs` 参数支持，无缝吸收 PluginManager 解构出的子目录路径；`SkillManager` 增强对根目录直接存在 `SKILL.md` 插件的识别加载。
  - `agent.py` & `tasks.py`：
    - `Agent.__init__` 新增 `plugin_dirs: Sequence[str | Path] | None = None` 参数并装配 `self.plugin_manager`，自动将插件技能与子代理注入 `SkillManager` 与 `SubagentManager`；
    - `TaskManager._run` 在派发子代理时显式配置 `plugin_dirs=[]`，确保子代理沙箱隔离，防止递归探测产生工具冲突。
  - `__init__.py`：导出 `Plugin`、`PluginAuthor`、`PluginManifest`、`PluginManager`。
  - 测试：新增 `tests/test_plugins.py`（10 个测试用例，覆盖 Author 解析、Manifest 加载与多路径查找、损坏 JSON 降级推断、根级单 SKILL.md 简写、组件目录映射、PluginManager 扫描提取、Agent 自动集成与端到端 run、禁用控制、子代理派发隔离保护）。
- **过程中的关键教训**：
  - 规范严格性与轻量化：对标 Claude Code 官方与 OpenHands 实践，插件定位是“聚合分发包”，不额外引入重型概念；`PluginManager` 仅专注做自包含资源解构与分发，底层执行 100% 复用已有的 Skills/Subagents/MCP 机制。
  - 递归探测防护：父 Agent 加载插件中的 `agents/*.md` 并派发子代理时，子 Agent 必须同时设置 `plugin_dirs=[]`、`subagent_dirs=[]`、`memory_dir=False`，严防子代理重新探测插件导致 `task` / `memory` 工具冲突。
- **验证**：三包全量 **266 个离线测试** 全部 100% 绿灯通过（my-agent-core 212 + my-agent-llm 36 + my-coding-agent 18）。

---

### 阶段 14：Pi 风格动态干预机制（Steer 与 Follow-up）（2026-08-27）

**目标**：对标 Pi 与 pig-mono，实现 `MessageQueue` 动态干预消息队列与单层 Agent 的「两层循环架构（Two-Level Loop）」，支持任务中途安全点即时转向（Steer）、最终答复期防止早退继续 ReAct、任务完成后无缝自动衔接排队追问（Follow-up），并在 `TaskManager` 中支持对运行中子代理实例的动态定向纠偏（`steer_task` / `follow_up_task`）。

- 提交：`314bec1` `931cf24` `59fa538`
- **改了什么**：
  - `message_queue.py`（新增）：定义 `MessageType` (`STEERING`, `FOLLOWUP`)、`QueuedMessage`、`MessageQueue`，支持 `one-at-a-time`（单步推进）与 `all`（批注入）消费模式。
  - `agent.py`：重构 `run()` 为两层循环；外层 `while True:` 驱动 Follow-up 队列与宏观任务流转，内层 `while has_more_tool_calls or len(pending_messages) > 0:` 驱动 ReAct 微观步骤与 Steer 转向；实现三大安全点（Turn 起点原子落盘、工具批执行后 Steer 检查、无工具输出期 Steer 拦截防止早退）；暴露 `steer()` / `follow_up()`（内部队列操作由 `self.message_queue` 统一管理），`abort()` 清空队列。
  - `tasks.py`：`TaskManager` 内部维护 `_active_agents: dict[str, Agent]`，提供 `steer_task(task_id, msg)` 与 `follow_up_task(task_id, msg)`。
  - `__init__.py`：导出 `MessageQueue`、`MessageType`、`QueuedMessage`。
  - 测试：新增 `tests/test_message_queue.py`（5 项单测）与 `tests/test_agent_steering.py`（5 项单测），`tests/test_tasks.py` 扩充 1 项。
- **过程中的关键教训**：
  - 循环无限递归防范：在单测模拟 LLM 时，若流式回调在每一轮无条件调用 `steer_task` 会导致内层循环死循环；必须精准在指定轮次注入以验证多轮自动解套。
  - 安全点落盘一致性：所有注入的 user 消息统一在内层循环起始处经由 `session.add_message("user", ...)` 原子落盘，保证了 Session 树状拓扑对干预消息的 100% 确定性可回溯。
- **验证**：三包全量 **277 个离线测试** 全部 100% 绿灯通过（my-agent-core 223 + my-agent-llm 36 + my-coding-agent 18）。

---

### 阶段 15：工具系统深度优化、因果并发安全与 Tau 项目对标（2026-08-29）

**目标**：对标 Pi 官方源码（第 3、5 章）与开源项目 Tau（`tau-ai`），修复 `ToolRegistry.execute_batch` 并发调度的因果时序倒置缺陷，在产品层引入 `FileMutationQueue` 细粒度单文件并发锁，全面精细化四大文件工具的错误提示与超时日志捕获，对齐每轮配对发射 `TurnEnd` 生命周期事件，并沉淀 Tau 架构深度对标报告。

- **改了什么**：
  - `registry.py`：修复 `execute_batch` 并发调度的因果时序倒置缺陷；对齐 Pi 官方的一票否决（Unanimous Parallel）机制——当且仅当整批工具均为 `is_parallel_safe=True` 时才放行 `asyncio.gather` 并发；一旦包含任何写操作，整批严格按大模型输出的原序保序串行执行，确保因果顺序绝对正确。
  - `mutation_queue.py`（新增于 `my-coding-agent`）：引入 `FileMutationQueue`，按文件绝对路径（`path.resolve()`）管理 `asyncio.Lock` 异步互斥锁。
  - `tools.py`（`my-coding-agent`）：
    - `write` 和 `edit` 接入 `FileMutationQueue` 单文件锁保护，将外部并发声明提升为 `is_parallel_safe=True`（多文件并发修改耗时直降，同名文件自动保序排队）；
    - 精细化错误文案（Prompt-Quality Errors）：`read` 增加行数统计与精准越界提示，`edit` 增加文件行数、未找到排查建议与多重匹配检测，`bash` 超时自动捕获并回显子进程已输出的最后 2000 字符日志。
  - `context.py`：升级 L4 结构化压缩为完整的 6 Section 约束模板（`Goal`, `Constraints & Preferences`, `Progress (Done/InProgress/Blocked)`, `Key Decisions`, `Next Steps`, `Critical Context`）；新增 `extract_file_operations` 与 `format_file_operations`，自动从被压缩历史中提取并累积读改文件足迹（`<read-files>` 与 `<modified-files>`）。
  - `agent.py`：对齐 Pi 规范，在每轮执行结束（包含纯文本答复轮）无条件成对发射 `TurnEnd(message, tool_results)` 事件，杜绝轮次悬空。
  - `docs/references/tau-analysis.md`（新增）：深度调研与解构 Python 版 Pi Harness 开源框架 Tau（`tau-ai`），横向对比三层架构，提炼 Textual TUI、OAuth 认证链、JSONL RPC 模式、models.dev 动态模型表、`repair_tool_history` 自愈等核心亮点与演进路线。
  - 测试：更新 `test_registry.py`（验证并发因果时序与全员并发）、`test_agent.py`（严格断言配对 `TurnEnd`）、`test_tools.py`（扩充 5 项单测覆盖文件锁并发、越界行数提示、多重匹配与超时日志捕获）、`test_context.py`（扩充 2 项单测覆盖 6 Section 约束模板与跨压缩文件足迹累积）。
- **验证**：三包全量 **283 个离线测试** 全部 100% 绿灯通过（my-agent-core 226 + my-agent-llm 36 + my-coding-agent 21）。

---

### 阶段 8：统一任务系统、看板自动投影与后台异步执行（2026-08-29）

**目标**：对标 Claude Code v2.1.142+（`trpc-agent-python`）、Pi（`@juicesharp/rpiv-todo`）与 `learn-claude-code`（s10/s11），构建三位一体的统一任务子系统。实现 `TaskItem` + `TaskStore` DAG 依赖状态机、标准 4 增量 CRUD 工具族（`task_create`, `task_update`, `task_get`, `task_list`）与 `todo_write` 便捷工具、`BeforeModelCall` 决策点 `<TASK_BOARD>` 上下文看板自动投影（0 工具往返消耗，Session 历史零污染），以及具备孤儿进程防御的 `BackgroundRunner` 后台异步执行引擎（`agent.abort()` 联动清理，结果自动送入 `MessageQueue` 收割）。

- 提交：`307bd2e` `54fed05` `cd8a8a7` `460f992` `af30075`
- **改了什么**：
  - `task_store.py`（新增于 `my-agent-core`）：
    - `TaskItem`：工单数据模型（`id`, `subject`, `description`, `status: pending/in_progress/completed/deleted`, `owner`, `active_form`, `blocked_by`, `metadata`）；
    - `TaskStore`：管理 `<workspace>/.my_agent_core/tasks.json` 原子持久化（`tempfile` + `fsync` + `os.replace`），提供自增 ID 分配、DAG 传递性深度成环检测（`_depends_on`）、单 `in_progress` 聚焦约束、上游完成时下游 `unblocked` 自动解锁回显、全量紧凑看板渲染（`render_board`）与内部 `asyncio.Lock` 互斥保护。
  - `tools/builtin/task_tools.py`（新增于 `my-agent-core`）：
    - 导出 5 个标准工具：`task_create`, `task_update`, `task_get`, `task_list`, `todo_write`，全部标记 `is_parallel_safe=True`，遵循 Never-Throw 异常隔离。
  - `background.py`（新增于 `my-agent-core`）：
    - `BackgroundJob` & `BackgroundRunner`：异步非阻塞启动操作系统后台子进程，立即返回 `job_id`；执行完成后自动将 `<task_notification>` 送入 `agent.message_queue.add_followup()`；
    - 孤儿进程防御：注册 `atexit` 钩子并在 `cancel_all()` / `agent.abort()` 中主动 `terminate()` 正在运行的子进程，杜绝僵尸进程。
  - `agent.py`（`my-agent-core`）：
    - 支持 `task_store` 参数（默认探测 `<cwd>/.my_agent_core/tasks.json`，显式指定或禁用），自动注册 `task_*` 工具；
    - 自动装配 `self.background_runner`，并在 `abort()` 中触发后台进程安全清理；
    - 在模型视图准备期（`BeforeModelCall` 前），若存在未完成任务，自动将 `<TASK_BOARD>` Markdown 看板注入当轮临时模型视图（Session 历史保持绝对纯净）。
  - `tasks.py`（`my-agent-core`）：
    - `_filter_tools` 自动过滤 `task_*` 与 `todo_write` 工具，派发子代理时显式传入 `task_store=False`，防止递归工具注册冲突。
  - `tools.py` & `agent.py`（`my-coding-agent`）：
    - `make_bash_tool` 支持 `run_in_background: bool = False` 参数并接入 `BackgroundRunner`；
    - `CodingAgent` 自动装配并暴露 `task_store` 与 `background_runner` 属性。
  - `docs/core/12-task-system-and-background.md`（新增）：沉淀统一任务系统与后台异步完整技术架构规范。
  - 测试：
    - `test_task_store.py`（8 项单测，覆盖 DAG 依赖、环检测、单 in_progress、解锁与原子持久化）；
    - `test_task_tools.py`（3 项单测，覆盖 CRUD 与 todo_write 契约）；
    - `test_task_context_projection.py`（2 项单测，验证 `<TASK_BOARD>` 自动注入与 Session 零污染）；
    - `test_background.py`（2 项单测，验证异步启动、消息队列通知投递与取消清理）；
    - `test_agent_task_nudge.py`（新增单测，验证模型试图输出纯文本早退时触发 Steering 提醒更新 in_progress 任务）；
    - `test_coding_agent_tasks_e2e.py`（新增于 `my-coding-agent`，端到端验证多轮任务规划与后台测试运行）。
- **过程中的关键教训**：
  - 领域模型分工：彻底区分“工程规划待办实体（`TaskItem` & `TaskStore`）”与“子代理委派运行实例（`SubagentTask`）”，彻底删除旧 `tasks.py`，杜绝概念污染与命名冲突。
  - 极简写串行化：写操作工具（`task_create`, `task_update`, `todo_write`）诚实声明 `is_parallel_safe=False`，由 `ToolRegistry` 保证严格原序串行执行，彻底免除 `TaskStore` 内部冗余互斥锁。
  - 前缀缓存捍卫：彻底移除每轮向 System Prompt 动态拼接看板的逻辑，看板通过工具返回值即时回显，前缀缓存（Prefix Cache）100% 稳定。
  - 任务收尾守卫：模型试图未结清退出时，框架通过 Steering 自动注入提醒，促使模型及时调用 `todo` 工具完成闭环打勾。
  - 孤儿进程与管道悬空防御：引入 `_kill_popen_tree`（`taskkill /F /T`），彻底解决 Windows 子进程管道悬空等待导致的测试超时假死。
- **验证**：三包全量 **304 个离线测试** 全部 100% 绿灯通过（my-agent-core 246 + my-agent-llm 36 + my-coding-agent 22）。

---

### 阶段 8 补充演进：TaskGuardHook 事件解耦、随路回显与 Tau 深度架构对标（2026-08-30）

**目标**：消除 Agent 核心循环硬编码任务检查的分层泄漏缺陷，对齐 Pi 官方 Extension 哲学；深度探索对标 Tau（`tau_agent`）与 Pi 官方后台扩展架构，沉淀深度模块化重构规范与代码清理审查报告。

- 提交：`afa9115` `ddbbe46` `6cd59d0` `e141641` `ac73711`
- **改了什么**：
  - `task_tools.py` & `agent.py`：将硬编码在 `Agent.run()` 中的早退催促逻辑彻底抽离，重构为独立的 `TaskGuardHook`，挂载在 `TurnEnd`（无工具调用时检查）与 `AgentStart`（清空已提醒集合）生命周期事件上，由底层消息队列安全点（`steer`）自动拉起下一轮；`Agent.run()` 核心循环回归 100% 纯净通用调度。
  - 随路看板回显（In-Band Echo）：工具写操作在 `ToolResult.data["board"]` 中即时返回最新紧凑看板，100% 捍卫大模型供应商 Prompt Prefix Cache，Session 磁盘历史保持零污染。
  - `docs/core/13-tau-alignment-architecture-redesign.md`（新增）：深度解构 `tau_agent`，规划 4 阶段演进路线图：
    1. 引入 `tool_history.py` 三阶段确定性自愈状态机与 `_provider_context` 空失败轮次清洗；
    2. 拆解 `session/` 子包（9 种多态实体、纯内存树算法防环路、`SessionState` 纯函数无锁折叠投影、纯追加 `SessionStorage`）；
    3. 提炼 `loop.py` 纯函数微内核并暴露 `prompt_stream` 事件流；
    4. `Agent` 消除 18 参数上帝类构造。
  - `docs/core/14-codebase-cleanup-and-defect-repair.md`（新增）：基于双路并行 Subagent（Deslop Pass 与 Verbosity Pass）对抗式审查结论，形式化定义 P0-1（POSIX 进程组防自杀）、P0-2（`ExtensionAPI.on` 异步 Hook 协程包装）、P1-1（`context.py` L3 重复写放大消除）、P1-2（`Tool.timeout` 接入 `asyncio.wait_for` 真实生效）等关键缺陷与修复规格。
  - 博客更新：修润 `my-pi-agent--todolist与background.md`，理顺工具演进脉络与随路回显架构。
- **验证**：三包全量 **304 个离线测试** 持续 100% 绿灯全通。

---

### 阶段 17：对话转录本自愈与断头保护引擎（对标 Tau tool_history.py）（2026-08-30）

**目标**：对标 Tau `tau_agent/tool_history.py`，实现前置对话自愈纯函数模块，彻底消灭用户打断、网络超时导致的悬空断头 ToolCall 引发的大模型 API 400 校验死锁。

- 提交：`580f98f`
- **改了什么**：
  - `tool_history.py`（新增）：定义 `ToolHistoryRepair` 结果模型与 `repair_tool_history(messages)` 纯函数，三阶段清洗算法：
    1. 收集所有带 `tool_calls` 的 Assistant 节点并建立 `call_id` 字典索引；
    2. 从后往前清理孤儿与重复 Tool 结果（丢弃无主结果或重复响应）；
    3. 严格按调用声明顺序重排 Tool 结果，对缺失结果的断头调用合成为 `role="tool"` 的 `Tool call interrupted by user` 错误消息。
  - `agent.py`：
    - 在进入 ReAct 双层循环前，对从 Session 恢复的完整历史执行 `repair_tool_history` 自愈；
    - 在流式接收被用户或 Hook 中止（`abort`）时，若 Assistant 消息已产生 `tool_calls`，立即为每个悬空调用生成合成中断结果并追加落盘，保证会话树拓扑时刻合法。
  - `__init__.py`：导出 `ToolHistoryRepair` 与 `repair_tool_history`。
  - 测试：新增 `test_tool_history.py`（8 项覆盖干净历史、悬空断头补齐、孤儿结果丢弃、乱序重排、重复清理、跨轮次同 ID 隔离、诊断报告以及 Agent 被 abort 取消后的端到端自愈恢复）。
- **验证**：三包全量 **312 个离线测试**（core 254 + llm 36 + coding 22）100% 绿灯全通。

---

### 阶段 18：Tau 对齐核心框架深度重塑（session/ 拆包、纯函数 loop.py 微内核与 prompt_stream 事件流）（2026-08-30）

**目标**：对标 Tau `tau_agent`，将框架核心层彻底解耦重构为工业级深度微内核架构：拆解单文件 `session.py` 为 5 专职模块并引入纯内存驱动，提炼 `run_agent_loop` 纯函数生成器微内核，将 `Agent` 瘦身为轻量 Harness 并对外暴露 `prompt_stream` 一等公民事件流与 `subscribe()` 接口。

- 提交：`f9c5f03` `ba109d0` `0b90f22` `0f5dac0` `c2eac4f` `74b8c27` `dae5474` `0ea849c` `73fba0d` `a8263c2` `a9a1d60` `9a93c42` `ac89076`
- **改了什么**：
  - `session/` 目录结构领域下沉（拆分为 5 大专职模块）：
    1. `entries.py`：定义 9 种多态 Pydantic v2 条目实体（`SessionInfoEntry`, `MessageEntry`, `ModelChangeEntry`, `ThinkingLevelChangeEntry`, `CompactionEntry`, `BranchSummaryEntry`, `LabelEntry`, `LeafEntry`, `CustomEntry`），通过 `Field(discriminator="type")` 组成 `SessionEntry` 联合体，彻底废除脆弱的第 0 行文件头字典；
    2. `tree.py`：实现纯内存 DAG 算法（`entries_by_id`, `path_to_entry`, `lowest_common_ancestor`），内置 `seen` 集合循环死锁检测与重复 ID 校验，零物理 I/O 依赖；
    3. `memory.py`：实现 `SessionState` 不可变状态快照与纯函数折叠投影（`SessionState.from_entries`），沿路径线性折叠模型、思考深度、分支指针，并自动将 `CompactionEntry` 映射为单条摘要消息；
    4. `storage.py`：定义只追加纯异步 `SessionStorage` 协议，实现 `InMemorySessionStorage` 纯内存存储驱动，赋能单测完全脱离物理文件极速运行；
    5. `jsonl.py`：实现 `JsonlSessionStorage` 追加存储驱动，引入 `.{name}.lock` 跨进程文件锁（Windows `msvcrt` / POSIX `fcntl`）、未完成 `.tmp` 碎片自愈清理与 `_migrate_session_entry` 旧版格式平滑兼容迁移；
    6. `session/__init__.py`：统一子包符号导出，动态桥接向后兼容门面，确保外部老代码与现有测试零断裂。
  - `loop.py`（新增）：
    - 提炼纯无状态异步生成器微内核 `run_agent_loop`，全面接管 ReAct 双层事件循环（内层工具执行 + steering 即时转向，外层 follow-up 自收割），消灭原 `agent.py` 内部 260+ 行重复内联循环逻辑；
    - 接入 `_provider_context`，在调用模型前剥离空失败轮次并串联 `repair_tool_history`，彻底免疫大模型 API 400 校验死锁；
    - 引入 `CancellationToken` 协作式取消信号，在流式及工具调用前即刻响应中断，并自动为悬空调用合成中断结果落盘。
  - `agent.py`：
    - 瘦身 Agent 为轻量 Harness，将核心调度流彻底委托给 `run_agent_loop`；
    - 暴露一等公民 `async def prompt_stream(self, user_input: str) -> AsyncIterator[Event]` 事件流接口；
    - 暴露 `subscribe(listener)` 观察者接口；
    - 将 `run()` 重构为纯粹消费 `prompt_stream` 的便利门面，保持原有 100% 行为兼容。
  - 测试：新增 `test_session_tree_modular.py`（14 项）、`test_session_memory_and_storage.py`（20 项）、`test_session_jsonl_modular.py`（19 项）、`test_agent_loop_pure.py`（11 项）、扩充 `test_agent.py`（2 项），全套重构新增 66 项高质量单测。
- **验证**：三包全量 **378 个离线测试**（core 320 + llm 36 + coding 22）100% 绿灯全通，零回归，代码检查 100% clean。

---

### 阶段 19：Pi 风格事件流与五大决策拦截点正交重构（2026-09-09）

**目标**：彻底终结微内核单体膨胀与双发混乱，正交解耦只读事实事件流与五大决策拦截点，子生成器分治提炼，坚决拒绝冗余兼容，重写老测试，全量测试达到 392 项 100% 绿灯。

- 提交：`9b585f7` `7855e7d` `e13f10f` `a0064b2` `888203a` `0cf6233` `077f45f` `d2ebf79` `b5da6b0` `bc0a5cc` `e35d2d8` `a93d108`
- **改了什么**：
  - `events.py` 与 `hooks.py` 架构正交解耦与物理拆分：
    1. 彻底删除 `Interceptable` 混入类，`events.py` 纯粹承载 12 个不可变事实事件（`AgentStart`, `AgentEnd`, `TurnStart`, `TurnEnd`, `MessageStart`, `MessageUpdate`, `MessageEnd`, `ToolExecutionStart`, `ToolExecutionUpdate`, `ToolExecutionEnd`, `ContextCompacted`, `ToolsChanged`，基类 `Event`）；
    2. 提炼独立的 `hooks.py` 物理模块，承载五大专职强类型 Hook 拦截点（`UserInputHook`, `AgentStartHook`, `BeforeModelCallHook`, `ToolCallHook`, `ToolResultHook`），专职策略拦截与参数/结果改写；
    3. `HookRegistry` 专职负责拦截钩子的注册、注销、async/sync 回调混合调用与短路机制，内置严格的 Never-Throw 异常隔离保证，彻底废除生造的 `DecisionRegistry` 与所有 `*Decision`、`UserInput`、`BeforeModelCall`、`AgentEvent` 等兼容别名；
    4. 扩展 `TurnEnd` 支持 `message: Message | None = None` 与 `tool_results: list[Message] = field(default_factory=list)`，并在 `AgentEnd.stop_reason` 中明确支持 `"error"` 枚举。
  - `loop.py` 子生成器分治与状态机极简化：
    1. 提炼 `_stream_llm`：统一归一化 `achat_stream`、`achat` 与同步 `chat`（经 `asyncio.to_thread`），消除 70 余行协议重复适配代码；
    2. 提炼 `_assistant_turn`：专职大模型流式推理车间，逐字 yield `MessageUpdate`，精准区分 cancellation 与 error，异常时 Never-Throw 封装并于末尾 yield `MessageStart`/`MessageEnd`；
    3. 提炼 `_synthesize_interrupted_tool_calls`：集中化断头合成自愈辅助函数；
    4. 提炼 `_execute_tools_turn`：严格对齐 Pi 官方时序契约（Preflight 阶段按 source order **率先广播 `ToolExecutionStart`** 供 UI 即时渲染 ➔ 调用 `before_tool_call` 审批改参 ➔ 并发批处理执行 ➔ 调用 `after_tool_call` 改写 ➔ 按完成顺序发射 `ToolExecutionEnd` ➔ 按 source order 发射配对 Tool 消息事件），并在中途取消时自动自愈补齐断头调用；
    5. 重构 `run_agent_loop`：彻底清除原本为过渡期保留的 `hook_registry` 参数与 35 行降级垫片代码，微内核纯粹瘦身为约 **110 行** 极简状态机微内核，彻底消灭 30 余处机械式双发冗余，保证在正常完成、取消中断、安全门禁阻断、最大轮次截断等任何退出路径下，已开启轮次 **100% 严格发射配对闭合的 `TurnEnd`**。
  - `extensions/core.py` 与 `agent.py` 强类型智能路由与装配：
    1. `ExtensionAPI.on(target)`：纯 Python 强类型自动分流：若 `issubclass(target, Event)` 则注册为只读监听器并静默忽略返回值；否则注册为拦截钩子中间件（透传 `HookResult` 干预）；
    2. `Agent` 装配 Hook 管线：在 `prompt_stream` 起始处依次介入 `UserInputHook` 与 `AgentStartHook`，将 `before_model_call`、`before_tool_call`、`after_tool_call` 委托给 `run_agent_loop`，直接向 `self._subscribers` 单向广播事实事件；
    3. 在 `Agent.run()` 中遇到 `event.stop_reason == "error"` 时准确向上抛出 `RuntimeError`，完整维持子代理任务失败报错契约。
  - 单测重写与模块化分拆：
    1. `test_events.py`（4 项覆盖 Event 不可变性、字段、TurnEnd 闭包及负向防御断言）；
    2. `test_hooks.py`（7 项独立测试 5 大 Hook 拦截点、HookResult 字段及 HookRegistry 短路与 Never-Throw 异常捕获）；
    3. `test_loop_subgenerators.py`（13 项覆盖协议归一化、流式推理、Pi 时序前置广播、参数结果改写与中断自愈）；
    4. `test_agent_loop_pure.py`（14 项覆盖纯状态机微内核、门禁阻断 TurnEnd 闭环、max_iterations 截断与转向注入）；
    5. `test_agent.py` 与 `test_extensions.py`（46 项覆盖强类型 Hook 分流与 Harness 门面）。
- **验证**：三包全量 **389 个离线测试**（core 331 + llm 36 + coding 22）100% 绿灯全通，零回归，Primary LSP 类型检查 100% clean。

---

### 阶段 20：工业级七阶段工具执行流水线与订阅管道收敛（2026-09-12）

**目标**：对标 Pi 工业级七阶段工具执行流水线，在 `loop.py` 微内核中引入阶段 1 截断防御（`stop_reason="length"`）、阶段 5 跨线程队列 `ToolExecutionUpdate` 实时进度流、阶段 7 `any()` 批次提前退出与 `final_text` 传递；清理 `agent.py` 遗留兼容垫片与死代码，统一收敛 `_notify` 只读事件订阅管道（完成阶段 16），并修复模型层空 `tool_calls: []` 触发 HTTP 400 隐患。

- **改了什么**：
  - `loop.py`（七阶段工具流水线落地）：
    1. **阶段 1 截断防御（Truncation Defense）**：在 `stop_reason == "length"` 时切入 `_fail_tool_calls_from_truncated_message`，成对发射 `ToolExecutionStart`/`End(is_error=True)` 并注入错误指引，阻止残缺截断工具调用越界执行；
    2. **阶段 2 畸形调用防崩（Error Containment）**：`_coerce_tool_call` 统一捕获工具参数序列化异常并包装为合成错误，杜绝未处理异常中断异步生成器；
    3. **阶段 5 实时进度流（Real-time Streaming Updates）**：在 `Tool.execute` 中引入 `on_update` 回调，过滤保留参数（`_FRAMEWORK_RESERVED_PARAMS`），建立 `asyncio.Queue` 跨线程安全桥（`loop.call_soon_threadsafe` 处理 `to_thread` 同步工具），并通过 `accepting_updates` 锁存器杜绝工具结束后的迟到更新；队列生产者无条件在 `finally:` 发射 `_SENTINEL` 杜绝死锁；
    4. **阶段 7 批次提前退出（Batch Early-Exit）**：`ToolResult` 增加 `terminate: bool = False`，`HookResult` 增加三态 `terminate: bool | None = None`；整批工具执行完毕后以 `any()` 语义评估是否熔断退出，并保证保留最后的有效终态文本 `final_text`。
  - `agent.py`（Harness 瘦身与管道 A 闭环）：
    1. 彻底删除零引用的死代码 `_emit`，移除死方法 `clear_queue` 与 `get_queue_status`（收敛于公开属性 `self.message_queue`）；
    2. 清理 `compact(self)` 的死参数 `_custom_instructions`；
    3. 将静态兼容赋值 `self.skills = self.skill_manager.list()` 重构成只读动态属性 `@property def skills`，彻底消除动态注册 skill 时的脱节隐患；
    4. 修正构造函数 `hooks` 参数类型注解为 `list[tuple[type, Callable[..., Any]]] | None`；
    5. 收敛 4 处重复手写的广播循环为统一的 `_notify(event)` 助手，支持同步/异步监听器，并由 `contextlib.suppress(Exception)` 彻底保障 Never-Throw 契约；
    6. 将 `prompt_stream` 中的历史恢复统一为 `self.session.get_full_history_messages()`，避免压缩缓存节点混入空白系统消息。
  - `my-agent-llm/providers/openai.py`：
    - 在消息转 wire 协议时，仅在 `wire_calls` 非空时才附加 `"tool_calls"` 键，杜绝上游接口空列表 HTTP 400 校验死锁。
  - 测试：
    - `test_agent_loop_pure.py` 扩充截断防御、批次 `any()` 提前退出、三态 Hook 熔断与反向压制测试；
    - `test_loop_subgenerators.py` 扩充跨线程进度流及 `Tool.execute` 锁存器 Spy 校验；
    - `test_agent.py` 扩充 `_notify` 异步订阅者与异常隔离单测；
    - `test_openai_provider.py` 补充空 `tool_calls` 消息转换单测。
- **验证**：三包全量 **410 个离线测试**（core 337 + llm 51 + coding 22）100% 绿灯全通，零回归，Primary LSP 类型检查 100% clean。

---

## 核心演化历程总览（已全部完成落地）

- 阶段 2：单层 `Agent` 类 + 事件（已完成）
- 阶段 3：session 管理（已完成）
- 阶段 4：context 管理（已完成）
- 阶段 5：skill 机制（已完成）
- subagent 机制（已完成，另列）
- Task 委派系统 + 四个文件工具（已完成，文件工具已归位产品层）
- 阶段 9：extension 机制与 MCP 客户端扩展（9.1/9.2/9.3 已全部完成）
- 阶段 10：框架层原生异步架构升级（已完成）
- 阶段 11：my-coding-agent 产品层（已完成，18 + 181 + 36 测试全绿）
- 阶段 12：Extension 五大决策点与生命周期拦截体系（已完成，187 + 36 + 18 测试全绿）
- 阶段 7：memory 记忆系统（已完成，201 + 36 + 18 测试全绿）
- 阶段 13：Claude Code 风格 Plugin 插件系统（已完成，212 + 36 + 18 测试全绿）
- 阶段 14：Pi 风格动态干预机制 Steer 与 Follow-up（已完成，223 + 36 + 18 测试全绿）
- 阶段 8：统一 Task / Todo 系统与后台异步执行（已完成，246 + 36 + 22 = 304 测试全绿）
- 阶段 17：对话转录本自愈与断头保护引擎（已完成，对标 Tau tool_history.py，312 测试全绿）
- 阶段 18：Tau 对齐核心框架深度重塑（已完成，session/ 拆包、纯函数 loop.py 微内核与 prompt_stream 事件流，320 + 36 + 22 = 378 测试全绿）
- 阶段 19：事件与拦截解耦正交重塑（已完成，纯函数微内核、强类型路由与 TurnEnd 闭合，389 测试全绿）
- 阶段 16：事件管道 A——只读轻量事件订阅管道（`agent.subscribe` + `_notify` 异常隔离广播与 `unsubscribe()` 注销句柄，已完成）
- 阶段 20：工业级七阶段工具流水线（截断防御、流式进度、批次熔断提前退出，410 测试全绿，已完成）

---

### 阶段 21：CodingAgent 产品层落地与 6 大核心文件工具（2026-09-12）

**目标**：构建生产级无头编码助手 `my_coding_agent`，落地 6 大安全文件工具（`read`, `write`, `edit`, `bash`, `grep`, `find`）、`FileMutationQueue` 细粒度并发写锁、`<project_context>` 自动发现与 Dual API（`run` / `run_stream`）。

- **改了什么**：
  - `tools/base.py`：实现 `resolve_path` 兼容性路径解析与 `_safe_path` 沙箱防御，定义 `DEFAULT_IGNORE_DIRS`；
  - `tools/read.py`：实现带行号、行/字节双重截断保护的读取工具；
  - `tools/write.py`：由 `FileMutationQueue` 细粒度文件锁保护的原子文件写入；
  - `tools/edit.py`：实现 Multi-Edit 与 Unified Diff 变更回显；
  - `tools/bash.py`：跨平台进程树安全执行与超时截断；
  - `tools/grep.py` 与 `tools/find.py`：原生跨平台正则内容与路径匹配；
  - `mutation_queue.py`：基于 `@asynccontextmanager` 的文件级并发互斥锁；
  - `prompt.py`：专业编码提示词装配与 `AGENTS.md` / `CLAUDE.md` 项目上下文发现；
  - `agent.py`：`CodingAgent` 统一组装门面，提供 `run()` 与 `run_stream()` 双 API。
- **验证**：单包 20 项新增单元与 E2E 场景测试全绿，全库 430 项测试 100% 绿灯全通。

---

### 阶段 22：Phase 3A Antigravity OAuth 鉴权与配额自省（2026-09-12）

**目标**：对标 `pi-antigravity`，实现零硬编码密钥的 Google Cloud Code Assist OAuth 凭据自动解析与刷新，接入配额监控与多模型支持。

- **改了什么**：
  - `my_agent_llm/auth/antigravity.py`：实现 `AntigravityAuthResolver`，严格动态自省 `~/.pi/agent/auth.json` 提取 `access_token`、`refresh_token`、`project_id`，过期时通过 Google OAuth 端点自动静默刷新；
  - `my_agent_llm/providers/antigravity.py`：实现 `AntigravityProvider`，自动注入 `Authorization`、`x-goog-user-project` 与 `User-Agent`；
  - `my_agent_llm/auth/quota.py`：实现用户调用配额查询器 `AntigravityQuotaViewer`。
- **验证**：全套 OAuth 解析、Token 刷新与 Provider 请求头注入测试通过，全量 505 项测试全绿。

---

### 阶段 23：Phase 3B Accept-on-Diff 权限审查门禁与词级 Diff 增强（2026-09-12）

**目标**：对标 Pig-Mono 与 Pi，实现高危操作（写文件、命令执行）前的安全审查门禁与行内反色精细高亮。

- **改了什么**：
  - `my_coding_agent/permissions.py`：实现 `PermissionGate`，基于 `ToolCallHook` 介入写操作审查，支持 `review`、`autonomous`、`strict`、`yolo` 4 种安全模式；
  - 词级反色差异加亮算法：字符/单词级精细 Diff 算法，直观一眼看出修改细节。
- **验证**：多轮审查与自动放行 E2E 测试全绿，全量 535 项测试全绿。

---

### 阶段 24：Phase 3C 提示词 `@` 文件引用快速补全与工作区 Turnkey MCP（2026-09-12）

**目标**：对标 Pig-Mono 与 Claude Code，实现提问中键入 `@file` 自动展开代码快照，大模型首轮免调 `read` 直接分析；工作区 `.mcp.json` 自动感知挂载与安全回收。

- **改了什么**：
  - `my_coding_agent/file_reference.py`：实现 `FileReferenceParser`，正则 `@([\w\-./]+\.\w+)` 匹配文件、校验边界与 2000 行/50KB 双重截断，将代码块以 `<referenced_file>` 注入提问末尾；
  - `my_coding_agent/agent.py`：`CodingAgent` 启动时自动通过 `MCPClientManager.from_config_file()` 扫描当前工作区 `.mcp.json`，将外部工具标记 `is_mcp=True` 动态注入注册表；在 `close_mcp()` 中同时销毁子进程并从 `registry` 反注册，彻底杜绝陈旧 Schema 残留。
- **验证**：多轮端到端直通与 MCP 挂载测试全绿，全量 565 项测试全绿。

---

### 阶段 25：Phase 3D 终端状态底栏 (Footer) 与流式动态转向 (LiveInputListener)（2026-09-13）

**目标**：对标 Pi `footer.ts` 与 Steering 机制，提供紧凑仪表盘底栏与非阻塞键盘监听。

- **改了什么**：
  - 终端状态底栏：自动探测 Git 分支、折叠路径为 `~/...`、从会话树祖先链深度聚合实际 `total_tokens`、统计上一轮执行耗时；
  - 键盘监听器 `LiveInputListener`：Windows `msvcrt` 与 POSIX `termios` 跨平台支持，ANSI 序列防抖，`Esc` 键瞬时掐断当前生成轮次，直接打字回车即时向 `MessageQueue` 注入 `Steering` 转向纠偏指令；
  - `CodingAgent` 暴露 `steer()`, `follow_up()`, `abort()` 门面，通过 `main_loop.call_soon_threadsafe` 保障跨线程安全。
- **验证**：多线程打断与 Steering 状态机测试全绿，全量 580 项测试全绿。

---

### 阶段 26：基于 Pi 原厂 `@earendil-works/pi-tui` 的双核表现层落地（2026-09-13）

**目标**：彻底告别传统 Python 终端界面的粗糙与割裂，直接借力 Mario Zechner 调教的 Pi 原厂 TUI 引擎与成熟组件。

- **改了什么**：
  - `src/my_coding_agent/rpc_server.py`：实现 stdio JSON-RPC 2.0 服务端，将内部 `AgentEvent` 序列化为同构 JSON Lines，重构 Windows 异步 I/O 防崩溃；
  - `tui/src/client.ts`：实现 `PythonKernelClient` 跨进程管理 Python 内核，双向管道流式传输；
  - 移植 Pi 官方组件体系：`AssistantMessageComponent`（流式 Markdown 与思考块折叠）、`ToolExecutionComponent`（圆角细线卡片与点阵动效）、`UserMessageComponent`、`FooterComponent`、`dark.json` 24-bit TrueColor 调色盘；
  - 消除屏幕闪烁：基于 `TuiMainScreen` 差量重绘与 CSI 2026 同步垂直刷新屏障。
- **验证**：自动化测试覆盖组件渲染、RPC 协议收发与真实 Python 子进程端到端会话。

---

### 阶段 27：Tau 式单工程多包拓扑大一统重构（2026-09-13）

**目标**：对标 HuggingFace 官方 Tau 架构，彻底消除“伪多包”虚拟环境分裂与跨包导包黑魔法，实现单行 `uv run pytest` 跑完全库测试。

- **改了什么**：
  - 根目录建立全局唯一的 `pyproject.toml`、`.venv` 与 `uv.lock`；
  - 统合 Python 源码至根目录 `src/`（`my_agent_llm`, `my_agent_core`, `my_coding_agent`）；
  - 统合测试集至根目录 `tests/`（`tests/llm`, `tests/core`, `tests/coding`）；
  - 将前端交互层独立归位至顶级 `tui/`，根目录 `package.json` 配置 npm workspaces 支持一键 `npm start`；
  - 在 `tui` 中接入 `CombinedAutocompleteProvider`，原生支持 `@` 工作区文件路径联想与 `/` 斜杠命令浮窗；
  - 智能零配置凭据探测：未传 `-m` 参数时自动从 `auth.json` 挂载 `gemini-3.8-flash`。
- **验证**：**全库 584 个测试全部 100% 绿灯全通**（Python 575 + TypeScript 9），零破坏性回归，代码已完整推送至 GitHub。

---

### 阶段 28：Pi 原厂运行时与交互组件 1:1 深度对齐（2026-09）

**目标**：严格比对官方 Pi 系列包（`@earendil-works/pi-coding-agent`、`@earendil-works/pi-tui`、`@earendil-works/pi-ai` 与 `pi-antigravity`），在调度、工具流水线、会话 DAG 分支、Token/成本计费以及前端交互体验上达成 1:1 像素级与行为级对齐。

- **改了什么**：
  - **补齐第 7 个内置工具 `ls`**：在 `src/my_coding_agent/tools/ls.py` 实现 `make_ls_tool`，默认 500 条目 / 50KB 双重截断保护，目录自动追加 `/` 后缀，大小写不敏感排序，支持 dotfiles 隐藏文件；
  - **工具参数规范与模型容错对齐**：
    - `grep`：重构入参对齐 Pi 规范，接入 `glob`、`ignore_case`、`literal`、`context` 上下文行回显与 50KB 字节截断；
    - `edit`：对标 Pi 原厂 `prepareEditArguments`，自动反序列化 JSON 字符串与包装单 dict，杜绝格式不规范模型报错；
    - `bash`：重构为异步行流读取，每 100ms 增量触发 `on_update` 广播，彻底告别长命令执行时的界面卡顿黑盒；
    - `find`：限制默认 1000 项结果与 50KB 截断保护；
  - **Antigravity 原生 SSE 直连与模型自省**：
    - 废弃伪装的 404 OpenAI 接口，直连 Google Cloud Code Assist `v1internal:streamGenerateContent` 原生 SSE；
    - 递归内联展开 JSON Schema 中的 `$defs` 与 `$ref`，彻底解决 Google Protobuf 400 校验死锁；
    - 对标 `pi-antigravity/grouping.ts`，基于 Google internal API 动态发现可用模型，收敛思考后缀与别名，支持 4 小时磁盘缓存；
  - **DeepSeek 动态模型目录**：
    - 接入 `GET https://api.deepseek.com/models` 动态拉取模型列表并持久化 4 小时磁盘缓存，消除硬编码；
  - **会话持久化与 DAG 分支探索**：
    - 扩充 `SessionEntry` 支持 `SessionHeaderEntry` (`type: "session"`)、`CustomMessageEntry` 与 `modelId` / `firstKeptEntryId` 别名兼容；
    - 修复 `/tree` DAG 图分支连接线（`│`, `├─`, `└─`）；
    - 完整实现 `/fork`（从历史节点分叉）、`/clone`（复制当前会话全量状态）、`/resume` 下 `Ctrl+D` 二次确认删除与活跃会话安全防御（前后端双拦截）；
  - **全量 Token 与成本核算**：
    - 提取各 Native Provider Cache 元数据，精确计算 Prompt Cache 命中率（`CH%`）；
    - 建立模型家族阶梯价格映射，计算美元开销与节省成本；
    - 真实 Context Window 动态传导至双行底栏，紧凑渲染 `↑[in] ↓[out] R[read] W[write] CH[hit]% $[cost] [ctx]%/[win]`；
  - **交互式组件与转圈动效对齐**：
    - 实现 `CustomEditor` 继承 `Editor`，100% 对齐 Pi 原厂 `renderTopBorder` 算法，在输入框顶部边框实时嵌入高频旋转指示器（`── ⠸ Working ──`）；
    - 实现 `WorkingStatusIndicator` 与 `CompactionStatusIndicator`，支持 80ms 高频 Braille 帧动画与 `unref` 定时器安全管理；
    - 实现 `CompactionSummaryMessageComponent` 可折叠卡片，支持 `Ctrl+O` 展开全文 Markdown；
    - 支持 `Shift+Tab` 与 `Ctrl+T` 快捷键轮转思考等级，自动根据模型能力动态夹逼与边框变色；
  - **清理工程冗余**：
    - 删除无引用的历史草稿 `docs/coding/05-pigmono-tau-feature-parity-design.md`；
    - 删除无引用的外部重导出文件 `tui/src/interactive/components.ts` 与 `theme.ts`；
    - 剥离 `tui/package.json` 对 `@earendil-works/pi-coding-agent` 的冗余依赖，使前端代码完全自主可控。
- **验证**：全库测试规模提升至 **665 个 Python 核心测试全部通过**，**57 个 TUI 自动化测试全部通过**，TypeScript 编译 0 报错。
