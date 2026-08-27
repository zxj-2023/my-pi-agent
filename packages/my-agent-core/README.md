# my-agent-core

从零实现的最简 ReAct agent。只依赖通用库（`openai` SDK、`pydantic`、`pyyaml` 等）与标准库，不引入任何 agent 框架（langchain / langgraph 等）。

项目方向：pig-mono 式两层结构——本包 = **框架层**（对应 `pig-agent-core`，独立 uv 项目，src 布局下 Python 包名为 `my_agent_core`）；
未来用它搭独立的 **coding agent 层**（对应 `pig-coding-agent`）。
详见文末「TODO：v1 实现路线」。

> **项目进度记录**：每个实现阶段做了什么（目标 / 规格 / 计划 / 提交 / 改了什么 /
> 过程中的关键教训 / 验证方式）记录在仓库根 `PROGRESS.md`——复盘看它就够。

## 简介

一个完整的 ReAct（Reason + Act）循环：模型决定是否调用工具，
本项目负责执行工具、把观察结果写回消息历史，循环持续——直到模型认为可以直接
回答为止。工具 schema 生成与参数校验委托 `pydantic`，其余协议细节
（`tool_calls` 解析、调度、错误容错）全部手写，透明可审查。

特性：

- `@tool` 装饰器：从函数名、docstring、类型标注自动生成发给模型的 JSON schema（pydantic 驱动，支持全集类型与默认值）；支持 `name`/`description`/`params_model` 覆盖
- ReAct 循环：Reason → Act → Observe → 重复，经典退出条件（`tool_calls` 为空即结束）
- 工具容错：工具异常、非法参数、不存在的工具名全部转成描述性消息回给模型，
  让模型有机会自我纠正
- 模型边界独立包：消息用 `my_agent_llm.Message`（role/content/metadata），
  统一 LLM 门面屏蔽 provider 差异（openai / deepseek / anthropic）
- 客户端依赖注入：生产传 `my_agent_llm.LLM(...)`，测试传假 LLM，全循环可离线测试
- 会话持久化 + 上下文管理：树结构 session（原子落盘 + rewind + fork）、
  四层压缩管线（免费层 + LLM 摘要 + retainedTail 缓存）

## 怎么跑

```powershell
uv sync                        # 安装依赖
Copy-Item .env.example .env    # 然后把真实配置填进 .env（不是 .env.example）
uv run python -m my_agent_core.main # 在本包目录（packages/my-agent-core）执行
```

环境变量：

| 变量                | 必需 | 说明                         |
| ------------------- | ---- | ---------------------------- |
| `OPENAI_API_KEY`  | 是   | OpenAI API key               |
| `OPENAI_MODEL`    | 否   | 模型名，默认`gpt-4.1-mini` |
| `OPENAI_BASE_URL` | 否   | 自定义 OpenAI 兼容端点       |

测试（不需要 API key）：

```powershell
uv run pytest -q
```

## 项目结构

```
my-agent-core/           # 独立 uv 项目（本包根）
├── pyproject.toml       # 包名 my-agent-core，src 布局 + hatchling 构建
├── .env.example         # 环境变量模板（复制为 .env 填真实值）
├── src/
│   └── my_agent_core/   # Python 包（import 名仍是下划线 my_agent_core）
│       ├── tools.py     # Tool 类 + tool() 装饰器 + ToolResult（schema 生成 + 校验执行）
│       ├── registry.py  # ToolRegistry：工具注册表（查表 + 批量 schema + 执行）
│       ├── events.py    # 10 个事件 dataclass + HookResult（hook 生命周期通知/干预）
│       ├── agent.py     # Agent 类（单层：状态 + 循环 + 工具执行 + hook 注册表）
│       ├── session.py   # SessionEntry + SessionTree + Session（树 + JSONL 原子落盘）
│       ├── session_store.py  # SessionStore（会话仓库，workspace 隔离）
│       ├── context.py   # ContextManager（四层压缩管线）+ ContextSessionBridge
│       ├── memory.py    # MemoryStore + make_memory_tool（长期记忆与快照管理）
│       ├── plugins.py   # Plugin + PluginManager（Claude Code 插件聚合分发）
│       └── main.py      # demo 入口：三个示例工具 + 三个示例问题
└── tests/
    ├── test_tools.py    # Tool/ToolResult/tool() 离线测试
    ├── test_registry.py # ToolRegistry 离线测试
    ├── test_events.py   # events.py 事件 dataclass 测试
    ├── test_agent.py    # Agent 循环离线测试（FakeLLM 驱动）
    ├── test_session.py  # 树 + 持久化 + 缓存 entry + rewind 护栏测试
    ├── test_session_store.py  # SessionStore 仓库测试（workspace 隔离）
    └── test_context.py  # ContextManager 四层管线测试（FakeLLM 驱动）
```

## 工作原理

```
用户问题 → [model] ──有 tool_calls──→ 执行工具 → 观察结果 ─┐
              ↑                                             │
              └─────────────── 回模型 ◄──────────────────────┘
              │
              └──无 tool_calls──→ 返回最终答案
```

每一轮把完整消息历史 + 工具 schema 发给模型；**是否调用工具由模型自己决定**
（模型厂商 function calling 训练的能力），本项目只负责翻译和调度：

1. **上行翻译**：`@tool` 把 Python 函数翻译成模型看得懂的 JSON schema，
   放进请求的 `tools` 字段
2. **下行调度**（`Agent.run` 内联循环）：读响应的 `tool_calls`——非空就逐个经
   `_prepare_tool`（解析 + `ToolExecutionStart` hook 拦截/改参数）→ `ToolRegistry.execute`
   （内部查表 + pydantic 校验，永不抛）→ `_execute_tool`（执行 + `ToolExecutionEnd` hook 改结果），
   把观察文本作为 `role: "tool"` 消息写回 messages（与助手消息的 `tool_call_id` 配对），
   再问一轮；为空则循环结束，返回模型的文本。循环各阶段触发 hook（构造时 `hooks=` 批量挂载），
   工具路径任何错误（坏 JSON / 未知工具 / 校验失败 / 工具异常 / hook 拦截）都转成
   描述性消息喂回模型，让模型有机会自我纠正

## 添加新工具

```python
from my_agent_core.tools import tool

@tool
def get_weather(city: str) -> str:
    """Get the weather for a city."""      # docstring 会成为工具描述
    return f"{city}: sunny, 22°C"

@tool
def search_docs(query: str, tags: list[str], limit: int = 5) -> str:
    """Search docs by query and tags."""   # 复杂类型、默认值都可以
    return f"results for {query} (tags={tags}, limit={limit})"

# 然后把它组装进 Agent：
from my_agent_llm import LLM
from my_agent_core.session_store import SessionStore

session = SessionStore().create()
agent = Agent(llm=LLM(...), session=session, tools=[get_weather, search_docs], system_prompt="...")
answer = agent.run(question)
```

参数类型支持 pydantic 全集（`list` / `dict` / `Optional` / 嵌套 `BaseModel` 等），
允许默认值；无标注参数与 `*args` / `**kwargs` 在装饰时拒绝。

## 设计取舍

- **库层没有默认系统提示词**：`Agent` 的 `system_prompt` 默认为 `None`，
  不发送 system 消息；给模型什么人设由应用层决定（`main.py` 的 demo 自行
  传入 `DEMO_SYSTEM_PROMPT`）
- **没有无限循环护栏**：退出完全由模型判断；模型若陷入工具循环会持续消耗
  token，需手动 Ctrl+C 终止。如需护栏请设置 `max_iterations` 最大轮数限制
- **同步顺序执行**：模型一轮发起多个 `tool_calls` 时逐个执行
- **单层 `Agent` 类**：状态（`messages`）+ 循环 + 工具执行全在一个类（pig-mono 式）；
  循环无法脱离 Agent 单独测试，离线测试靠注入鸭子类型 `FakeLLM`（`Agent(llm=FakeLLM(...))`）

## TODO：v1 实现路线

框架层（对应 pig-mono 的 `pig-agent-core`）的整体实现，按依赖排序；
**coding agent 层**（对应 `pig-coding-agent`，用本框架搭成的
独立包）在这些阶段之后另行设计与实现。pig-mono（`D:/code/python/pig-mono`）
是 pi 的 Python 移植版，为直接参考。

**原则**：阶段 2（单层 Agent）是主要演进——`agent.py` 重写为 `Agent` 类，新增
`events.py`；阶段 3 起逐层叠加。每步带验证方式（测试编号为本地记录）。

### 阶段 2：单层 `Agent` 类 + 事件（框架 v1 完成）

> **2026-08-06 修订**：原设计的两层（`run_loop` 纯函数 + `Agent` 外壳）已改为
> **pig-mono 式单层 `Agent` 类**（状态 + 循环 + 工具执行全在一个类），并适配
> my-agent-llm（消息 `list[Message]`、Agent 直接持有 `LLM`）。`llm.py` / `loop.py`
> 不再存在；循环测试全部转为「构造 `Agent(llm=FakeLLM(...))` → run」驱动。

- [x] 2.1 `events.py`：`Event` 基类 + 10 个事件 dataclass（对齐 pi 生命周期模型：
      Agent/Turn/Message/Tool 四组成对，`MessageUpdate`/`ToolExecutionUpdate` 为异步流式预留）
      → 验证：可导入可实例化（行为由循环测试覆盖）
- [x] 2.2 `agent.py` 重写为 `Agent` 类：`run()` 内联循环、`reset()` 保留 system prompt、
      复用 `ToolRegistry.execute` → 验证：框架 §7 #2–#5、#11、#13、#14（FakeLLM 驱动）
- [x] 2.3 hook 注册表：`_prepare_tool`（解析 + `ToolExecutionStart` hook 拦截/改参数）+ `_execute_tool`
      （执行 + `ToolExecutionEnd` hook 改结果）、hook 异常转错误字符串 → 验证：框架 §7 #7–#10
- [x] 2.4 `max_iterations`（默认 `None` 不限）→ 验证：框架 §7 #12
- [x] 2.5 `main.py` 改用 `Agent` + `register_hook` 打印循环过程；`__init__.py` 导出公共 API
      （`Agent` / `tool` / `Tool` / `ToolResult` / `ToolRegistry` / `HookResult` / `Interceptable` / 事件类型）
- [x] 2.6 更新本 README 的「添加新工具」示例与「设计取舍」措辞（`run_agent` → `Agent`）
- **阶段验证**：`uv run pytest -q` 全绿（#1–#15，框架 §7.2：框架 v1 完成）；
  真实运行 `uv run python -m my_agent_core.main`，三个问题答案符合预期
  （703 / 当前时间 / 两城市天气）

### 阶段 3：session 管理

> **2026-08-06 修订**：原「纯消息序列 + turn 边界批量写」已改为 **pig-mono 式树结构
> （entry 带 id/parent_id + current 指针）+ 逐条原子落盘 + rewind（移动指针）**。
> 用户有 rewind 计划，v1 就用树。

- [x] 3.1 `session.py`：`SessionTree`（entry 带 id/parent_id/current_id，add_entry /
      get_current_path / rewind）+ `Session`（add_message / save 原子全量重写 / load /
      get_current_path_messages）→ 验证：会话 §8 #1–#6
- [x] 3.2 `session_store.py`：`SessionStore` —— create / list（倒序）/ open（唯一
      前缀匹配，歧义报错）/ delete / fork（从 entry 复制路径为新会话）；id = 时间戳
      + 8 位随机 hex，碰撞重试；workspace 隔离（pig-mono 式：会话目录 =
      `<workspace>/.my_agent_core/sessions`，默认 cwd；跨项目天然隔离）
      → 验证：会话 §8 #11、#13、#14
- [x] 3.3 `Agent` 集成：`session=` 参数（必填，逐条落盘；system 由 Agent 拼、不存 session）、
      `reset()` 重写文件 → 验证：会话 §8 #7、#8、#10、#12
- [x] 3.4 `rewind`：`Session.rewind(entry_id)` 移动指针（旧分支保留），续跑从回退点长新枝
      → 验证：会话 §8 #3、#9
- **阶段验证**：`uv run python -m pytest -q` 全绿（会话 §8 #1–#12）；真实跨进程演示（需 .env）：
  进程 1 `store.create()` + `agent.run(一个问题)` 退出；进程 2 `store.open(前缀)` +
  `agent.run(引用上一轮答案的问题)` → 模型答得上

### 阶段 4：context 管理

- [x] 4.1 `context.py`：`estimate_tokens`（chars/4 + usage 锚定）+ 三层免费压缩
      （L3 大结果落盘 / L1 裁中间 / L2 旧结果占位，cheap-first，0 API）
      → 验证：上下文 #1、#4–#6
- [x] 4.2 `ContextManager`：四层管线（免费层每轮例行 + 超 0.8·budget 触发 L4 摘要）、
      切点对齐 user 边界（不拆 tool 配对）、摘要复用 `self.llm`（tools=[]，
      防注入 + 先分析再总结 `<analysis>`/`<summary>` 剥离）、缓存复用（retainedTail
      快照）、迭代再摘要、摘要失败降级不压缩 → 验证：上下文 #3、#7–#10、#13、#15
- [x] 4.3 `Agent` 集成：`context_budget=` / `keep_recent_tokens=`（`None` 不启用）、
      run() 循环内 prepare + usage 锚定、`compact()` 手动压缩、缓存写回 session
      （`type="compaction"` entry + `compaction_floor` rewind 护栏 +
      `get_full_history_messages` 过滤）、`ContextCompacted` 事件
      → 验证：上下文 #2、#11、#12、#14、#16
- **阶段验证**：`uv run python -m pytest -q` 全绿（113 个）；真实验证（需 .env）：
  小 budget（如 4000）跑多轮工具对话 → 事件可见 ContextCompacted；继续对话仍能引用早期信息（摘要生效）

### 阶段 5：skill 机制

- [ ] 5.1 `skills.py`：`Skill` / `SkillDiagnostic` 模型、手写 `parse_frontmatter`
      （不引 PyYAML）、`load_skills` 发现（SKILL.md = skill 根不下钻 / 根级
      `.md` / 递归子目录 / 容错诊断）、规范校验（name / description）
      → 验证：skill §7 #1–#4
- [ ] 5.2 `skills.py`：`format_skills_for_prompt`（agentskills.io XML 清单，
      只含 name + description）+ `read_skill_tool`（按名取正文，未知名字 →
      错误字符串列可用清单）→ 验证：skill §7 #5–#7
- [ ] 5.3 `Agent` 集成：`skill_dirs=` 参数（清单拼 system 尾部、`read_skill`
      置于 tools 首位、诊断公开）、`invoke_skill()` 显式调用（`<skill>` 包装
      跑一轮）→ 验证：skill §7 #8–#11
- **阶段验证**：`uv run pytest -q` 全绿；真实 demo：写两个 SKILL.md
      （其一 `disable-model-invocation`），提一个匹配 description 的问题 →
      模型自主 `read_skill` 后按正文指令作答；`invoke_skill` 显式调用
      隐藏 skill 成功

### 阶段 6：动态工具

- [ ] 6.1 `Agent.tools` 改为可变注册表（对外只读，写入口仅 register/unregister）；
      `run()` 每 turn 从注册表重建 schemas 与分发表
      → 验证：可扩展性 §7 #2、#5
- [ ] 6.2 `Agent.register_tool` / `unregister_tool`（撞名 / 未知名报错）
      + `ToolsChanged` 事件（事件集 7→8）
      → 验证：可扩展性 §7 #1、#3、#4、#6
- [ ] 6.3 agent-as-tool 配方验证（子代理包装成工具，内外双层 FakeLLM）
      → 验证：可扩展性 §7 #7
- **阶段验证**：`uv run pytest -q` 全绿

### 阶段 7：memory 记忆系统

- [x] 7.1 `memory.py`：`MemoryStore`（管理 `MEMORY.md` 2200 字符与 `USER.md` 1375 字符，`\n§\n` 条目分隔、`utf-8-sig` 编码、唯原子串定位增删改、精确去重、超限防护与原子落盘，启动捕获 Frozen Snapshot 冻结快照）
      → 验证：离线测试（`tests/test_memory.py`）
- [x] 7.2 `memory.py`：`make_memory_tool(store)`（受控 `memory` 维护工具，`Literal["memory", "user"]` + `Literal["add", "replace", "remove"]`，Never-throw 异常防护）
      → 验证：离线测试（`tests/test_memory.py`）
- [x] 7.3 `Agent` 集成：`memory_dir=` 三态参数（`None` 自动探测 / `False` 显式禁用 / 显式路径），`_init_messages` 注入 `<MEMORY_CONTEXT>` 冻结快照，`_register_tools` 自动注册 `memory` 工具（防撞名），`reset()` 重载快照
      → 验证：离线测试（`tests/test_memory.py`）
- **阶段验证**：三包离线测试全绿（总计 255 个测试）；端到端测试验证通过（Session A 写入用户画像 → 新 Session B 自动召回记忆并据此作答）

### 阶段 8：task 系统（todo + plan 核心）

- [ ] 8.1 `tasks.py`：`Task` 模型 + `TaskStore`（任务列表 / 状态机 todo→doing→done，
      随 session 持久化；plan 产出 = 任务列表）→ 验证：离线测试
      （对标 pi `packages/pi/src/task/`）
- [ ] 8.2 内置工具：`todo_write`（增删改查 + 勾选 completed，对标 Claude Code TodoWrite）
      → 验证：离线测试（FakeLLM 驱动）
- [ ] 8.3 `Agent` 集成：任务上下文注入 + 每轮自动更新进度
      → 验证：离线测试
- **阶段验证**：`uv run pytest -q` 全绿；真实 demo：模型自主拆解任务并勾选进度
  （**plan 模式**——进入 plan / 只读调研 / 用户批准 / 执行——是交互范式，
  做在 coding agent 层，见未来路线图）

### 阶段 9：extension 机制（MCP 由此实现；subagent 与 plugin 另列）

> **2026-08-14 修订**：MCP 不再独立实现——以 **extension** 形态落地（对标 pi
> `extensions` 文档与 pig-mono `extensions.py`）：MCP client 连接器本身就是一个
> extension，`ExtensionAPI.register_tool` 即翻译器的注册口。plugin（Claude Code 式
> 分发）还缺 **subagent 机制**（它带出的 agents 依赖 subagent）前置，拆出本阶段，
> 待 subagent 完成后另排（见未来路线图）。

> **2026-08-26 修订**：MCP 已迁产品层 `my-coding-agent`（`mcp.py`：
> `MCPServerConfig` / `MCPConnection` / `MCPClientManager`）；框架层
> `extensions/builtin/`（原 MCP）已删除、extension 机制本身保留；
> `mcp>=2.0.0` 依赖已随之从 `my-agent-core` 迁出。

- [x] 9.1 `extensions.py`：extension 机制（pi extensions 的 Python 版）——
      `ExtensionAPI`（on 事件 / tool / command 三件套）+ `ExtensionManager`
      （约定 `def extension(api): ...` + importlib 按文件加载 + 目录发现，失败跳过）
      → 验证：离线测试（对标 pig-mono `extensions.py`）
- [ ] 9.2 `mcp.py`：MCP client 以 **extension 形态**实现——stdio 连接器扩展：
      `extension(api)` 里 initialize → tools/list → 翻译成本地 `Tool` →
      `api.register_tool`（tools/call 在工具函数体内转发）
      → 验证：假 MCP server 离线测试
- [x] 9.3 `Agent` 集成：`extension_dirs=` 参数（加载扩展目录；扩展注册的 tools 进注册表）
      → 验证：离线测试（extension 目录加载 + tools 进注册表）
- **阶段验证**：`uv run pytest -q` 全绿；真实 filesystem MCP server demo：
  模型经 MCP 工具读写本地文件

## 未来路线图

按序演进，每项对标 pi 的对应物：

- [ ] **coding agent 层**（新主线，独立包 `my_coding_agent`，基于 my_agent_core
      框架，对应 `pig-coding-agent`；待专门设计）：CLI 入口、coding 系统
      提示、权限门控（落点 `ToolExecutionStart` hook）、**内置工具组装（read /
      write / edit / bash 四个文件工具——2026-08-26 已迁产品层 `my-coding-agent` 并实现；不含
      read_skill，框架层不预置文件工具）**、**plan 模式**（进入 plan → 只读调研 →
      产出计划 → 用户批准 → 执行；基于阶段 8 的 TaskStore，交互层在本包）
- [ ] **Prompt 管理**（**做在 `my_coding_agent` 层**，对应 pig-mono `prompts.py` +
      `context.py`）：`my_coding_agent/prompts.py`（PromptManager：从
      `~/.agents/prompts/`、`.pi/prompts/`、项目目录发现 `.md` 模板，
      `{{variable}}` 渲染）+ `my_coding_agent/context.py`（上下文文件注入：
      AGENTS.md / SYSTEM.md / APPEND_SYSTEM.md 从目录层级发现并拼入
      system prompt）。**拼好后传给框架 `Agent(system_prompt=...)`**——
      框架层零改动（`system_prompt=` 参数就是为此准备的）。理由：
      AGENTS.md 是 coding agent 的约定（宿主配置行为），不是通用框架概念
- [ ] async 化：只改 `llm.chat` 调用侧（对应 pi 的全异步形态）
- [ ] 流式输出：`message_update` 类增量事件（对应 pi 的 `message_start/update/end`）
- [ ] 推理内容回传：去程保留 `reasoning_content`（多轮连续性，DeepSeek 式）
- [ ] 工具结果结构化：`str` → `content`（喂模型）+ `details`（给 UI）
      （对应 pi 的 `AgentToolResult`）
- [ ] context 进阶：优雅停止钩子、split-turn 二次摘要、reactive 应急
      （对应 pi `compaction/` 完整版；usage 锚定、压缩状态持久化已实现）
- [ ] session 进阶：逐条事件落盘、typed entries + reduce、搜索索引
      （对应 pi `harness/session/` 完整版；树与分支已实现）
- [ ] skill 进阶：附带文件（正文路径引用）、user/project 分层作用域 +
      ignore 文件、动态刷新、REPL `/skill` 命令（对应 pi 完整 skill 机制）
- [ ] 可靠性：LLM 调用重试/指数退避（只对 429/5xx/连接错误，包在 `LLM` 门面
      或 Agent 层；对应 pi 的 `RetryPolicy`）
- [ ] usage 保留与成本统计：assistant 消息记录 `usage`、`Agent.total_usage` 累加；
      是会话级统计的前置（usage 锚定估算已实现）
- [ ] `my_agent_core.testing`：FakeLLM 公开化，框架使用者可离线测自己的 agent
      （对应 pi 的 faux provider 测试套件）
- [ ] 动态工具进阶：全量/激活子集、注册表持久化（session typed entries）、
      `addedToolNames` 式延迟加载（对应 pi harness 完整机制；
      MCP 连接器已并入阶段 9 extension）
- [ ] **extension：pi extensions 完整版**（**重要**，对应 pi `/docs/extensions`；
      pig-mono `extensions.py` 为其精简移植）：事件全集（tool_call 拦截/篡改、input、
      before_agent_start、compaction/tree 自定义、provider 内省）+ 命令自动补全 +
      `registerProvider` + `appendEntry` + `.pi/extensions` 自动发现 + `/reload`
      热载 + 分发（npm/git 式包）
- [x] **subagent 机制**（2026-08-16 实现，8 commits `ffb583d`→`6be1858`，154 测试；
      详见 spec `2026-08-15-my-agent-subagent-design.md` + `2026-08-16-subagent-task-manager-design.md`）：
      声明式 `agents/*.md` 定义文件（frontmatter：name/description/model/maxTurns/
      tools/disallowedTools/skills）+ `SubagentManager` 发现 + 内置 `task` 委派工具
      （spawn 子 Agent、fresh context、只回最终文本、工具过滤 + 防递归）。委派已升级为
      `Task`/`TaskStatus`/`TaskManager` 结构（`tasks.py`），`make_task_tool` 工具桥化。
      `effort`/`memory`/`background`/`isolation` 四项 deferred（字段位预留，端到端留后续）。
      （对标 Claude Code sub-agents 生态；**plugin 的 agents 前置已就绪**）
- [x] **plugin 分发**（2026-08-26 实现，Claude Code 官方标准；前置：subagent 机制 + skills + extension）：
      目录 + manifest（.claude-plugin/plugin.json 或 .plugin/plugin.json，支持目录名智能推断兜底），
      声明带出 skills / agents / .mcp.json，由 `PluginManager` 统一聚合解构并无缝注入各底层 Manager。
- [x] 内置工具模块（`my_agent_core.tools.builtin`）——已建，含 `task` 委派工具工厂
      + 四个文件工具 `read`/`edit`/`write`/`bash`（路径逃逸防护 `_safe_path` + bash
      危险命令黑名单 + 120s 超时）。**2026-08-16 反转 2026-08-13 决策**：通用文件工具
      归属框架层 builtin（不再等 coding agent 层）。
- [ ] 结构化输出：`run()` 的 JSON schema 强制变体
- [ ] 交互式多轮 REPL（应用层 demo，`Agent` 已为其铺路）
