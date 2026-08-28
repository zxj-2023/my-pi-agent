# my-pi-agent 架构参考溯源与设计复盘

本项目（`my-pi-agent`）从零手写了一个最小但完整的 Python Agent 框架与编码智能体。
为了保持极简、清晰、高内聚，我们在设计每一个核心模块时，深入研读并对比了开源领域中的多个顶级标杆项目（包括 **Pi**、**Hermes Agent**、**OpenHands (software-agent-sdk)**、**Learn-Claude-Code**、**pig-mono** 等）。

本文档对全套 12 个核心模块进行系统的溯源复盘，详细记录：

1. **参考的标杆项目与源码定位**；
2. **核心借鉴的设计机制与工程思想**；
3. **我们在 Python 下的裁剪、取舍与本土化架构创新**。

---

## 目录索引

- [一、模型边界层 (`my-agent-llm`)](#一模型边界层-my-agent-llm)
- [二、工具系统 (`my_agent_core.tools`)](#二工具系统-my_agent_coretools)
- [三、事件驱动与生命周期拦截体系 (`my_agent_core.events`)](#三事件驱动与生命周期拦截体系-my_agent_coreevents)
- [四、单层 Agent 与原生异步 ReAct 循环 (`my_agent_core.agent`)](#四单层-agent-与原生异步-react-循环-my_agent_coreagent)
- [五、树状会话与原子持久化 (`my_agent_core.session`)](#五树状会话与原子持久化-my_agent_coresession)
- [六、上下文四层廉价优先压缩管线 (`my_agent_core.context`)](#六上下文四层廉价优先压缩管线-my_agent_corecontext)
- [七、Skills 技能机制 (`my_agent_core.skills`)](#七skills-技能机制-my_agent_coreskills)
- [八、Subagents 与 Task 任务委派 (`my_agent_core.subagents` & `tasks`)](#八subagents-与-task-任务委派-my_agent_coresubagents--tasks)
- [九、Extension 扩展与命令路由机制 (`my_agent_core.extensions`)](#九extension-扩展与命令路由机制-my_agent_coreextensions)
- [十、Memory 长期记忆系统 (`my_agent_core.memory`)](#十memory-长期记忆系统-my_agent_corememory)
- [十一、Claude Code 风格 Plugin 插件系统 (`my_agent_core.plugins`)](#十一claude-code-风格-plugin-插件系统-my_agent_coreplugins)
- [十二、产品层 Coding 工具与原生异步 MCP 客户端 (`my_coding_agent`)](#十二产品层-coding-工具与原生异步-mcp-客户端-my_coding_agent)

---

## 一、模型边界层 (`my-agent-llm`)

### 1. 参考项目与源码定位

- **主要参考**：
  - **Pi (`@earendil-works/pi-ai`)**：多模型协议标准化与流式增量拼接（`packages/ai/src/`）；
  - **Anthropic Python SDK**：Claude 3/3.5 的 Content Block 双向翻译模型；
  - **DeepSeek API**：`reasoning_content` 思维链字段规范与解析。

### 2. 核心借鉴的设计机制

- **统一门面隔离（Facade Pattern）**：提供 `chat`、`stream`、`achat`、`achat_stream` 四组统一签名接口，将 OpenAI 的 `function_call`、Anthropic 的 `tool_use block` 与 DeepSeek 的推理过程抹平为统一的 `Message` / `Response` / `StreamChunk`；
- **流式 Tool Calls 增量聚合**：流式生成中，部分模型分片返回工具参数（如 index, partial arguments string）。在模型层内部完成自动拼接与 JSON 校验，确保到达 Agent 层时获得的是完整可调用的 `tool_calls`。

### 3. 我们的裁剪与创新

- **去三方重依赖（No LiteLLM/LangChain）**：不引入庞大黑盒的 LiteLLM，仅基于标准库和官方 SDK 抽象出 300 行极简 Provider 驱动；
- **Usage 锚定捕获**：流式末块（Last Chunk）必须强制挂载统一的 Token Usage 统计，为上层 Context 压缩提供精确计量基准。

---

## 二、工具系统 (`my_agent_core.tools`)

### 1. 参考项目与源码定位

- **主要参考**：
  - **pig-mono (`src/pig_agent_core/tools/`)**：`@tool` 装饰器、`Tool` 类与 `ToolRegistry` 注册表；
  - **OpenHands (`openhands.sdk.tool.tool`)**：Pydantic 动态建模自动生成 Function Calling Schema；
  - **Pi (`packages/agent/src/harness/tools/`)**：工具只读并发安全性声明与执行分流。

### 2. 核心借鉴的设计机制

- **Pydantic 动态契约提取**：利用 `pydantic.create_model` 直接从 Python 业务函数的类型注解和 Docstring 动态提取 OpenAI/Anthropic 兼容的 JSON Schema，无需手写重复的 Schema 字典；
- **Never-Throw 架构保证**：`Tool.execute()` 内部捕获所有校验和业务异常，统一包装为 `ToolResult(ok=False, error=...)`，绝不让未捕获异常导致 Agent 崩溃，引导 LLM 在下一轮自愈；
- **声明式并发加速（`is_parallel_safe`）**：支持在工具上标记只读并发安全，`ToolRegistry.execute_batch` 可通过 `asyncio.gather` 同时并发执行多个只读工具，大幅降低总耗时。

### 3. 我们的裁剪与创新

- **双通道 Schema 支持（`raw_schema`）**：既支持从 Python 函数类型注解推导，也支持直接透传 MCP 远程服务返回的原始 JSON Schema 字典，解耦远程工具对本地 Python 签名的依赖；
- **严格保序回填**：并发批执行完后，严格按照大模型最初发起 Tool Calls 的顺序重组回填进 Session 树。

---

## 三、事件驱动与生命周期拦截体系 (`my_agent_core.events`)

### 1. 参考项目与源码定位

- **主要参考**：
  - **Pi (`core/extensions/types.ts` & `docs/hooks.md`)**：五大生命周期决策拦截点（`input / before_agent_start / context / tool_call / tool_result`）；
  - **pig-mono (`events.py`)**：事件 Dataclass 继承层级与 Hook 注册表。

### 2. 核心借鉴的设计机制

- **五大生命周期拦截决策点**：
  1. `UserInput`（`input`）：截获用户原始输入，支持前置改写或 `block=True` 拦截（不写历史）；
  2. `AgentStart`（`before_agent_start`）：启动前拦截，支持动态改写首条 System Prompt；
  3. `BeforeModelCall`（`context`）：调 LLM 前拦截，支持 `updated_messages` 临时改写视图；
  4. `ToolExecutionStart`（`tool_call`）：工具执行前拦截，支持参数修补或危险阻断；
  5. `ToolExecutionEnd`（`tool_result`）：工具执行后拦截，支持篡改返回给大模型的出参。
- **纯观察 vs 强干预（Interceptable）解耦**：继承 `Interceptable` 的事件允许返回 `HookResult` 进行系统级干预；普通事件作为只读广播。

### 3. 我们的裁剪与创新

- **临时视图改写 vs 真实 Session 零污染不变式**：扩展在 `BeforeModelCall` 中注入的临时提醒（如 `[EPHEMERAL WARNING]`）只修改发给当前大模型的临时 `view`，**绝不追加进 `self.messages` 或 Session 磁盘文件**，保障会话历史 100% 纯净与确定性；
- **流式 Token 级实时熔断（`MessageUpdate`）**：在大模型逐字吐出 Token 时，若 Hook 检测到敏感内容可实时掐断生成，并**彻底丢弃未完成的半截文本**（不存入 Session），防止模型在下一轮产生断句续写幻觉。

---

## 四、单层 Agent 与原生异步 ReAct 循环 (`my_agent_core.agent`)

### 1. 参考项目与源码定位

- **主要参考**：
  - **Pi (`packages/agent/src/agent-loop.ts`)**：轻量内联 ReAct 循环、事件发射时序、退出条件判定；
  - **pig-mono (`agent.py`)**：单层类设计，将状态、工具派发与装配全部内聚在一个类中。

### 2. 核心借鉴的设计机制

- **扁平单层设计（Single-Layer Architecture）**：摒弃复杂的状态图框架（如 LangGraph），将 ReAct 循环（Reason ➔ Act ➔ Observe）直接以原生 `while` 循环内联在 `Agent.run()` 中，所有状态流转一目了然；
- **100% 纯原生异步 API**：全流程基于 `async/await`，调用方通过 `await agent.run(prompt)` 无阻塞交互。

### 3. 我们的裁剪与创新

- **彻底移除同步桥接（No `run_sync`）**：坚守纯协程架构，移除所有 `ThreadPoolExecutor` 伪同步封装，彻底杜绝多线程事件循环死锁；
- **组件自动注入装配**：构造时按序完成 `MemoryStore` 快照捕获 ➔ `SkillManager` / `SubagentManager` 探测 ➔ 工具统一挂载 ➔ `<MEMORY_CONTEXT>` 拼装。

---

## 五、树状会话与原子持久化 (`my_agent_core.session`)

### 1. 参考项目与源码定位

- **主要参考**：
  - **Pi (`packages/agent/src/harness/session/jsonl-storage.ts` & `session.ts`)**：树状会话结构、`rewind` 指针回退、`fork` 分支派生与 JSONL 格式；
  - **pig-mono (`session.py` & `session_store.py`)**：`SessionEntry` / `SessionTree` / `Session` / `SessionStore` 分层职责。

### 2. 核心借鉴的设计机制

- **树状分支数据结构（Tree-structured Session）**：每个 `SessionEntry` 包含全局唯一 `id` 和 `parent_id`，配合 `current_id` 指针维护当前对话主线；
- **无损回溯（`rewind`）与分支分叉（`fork`）**：`rewind` 仅移动当前指针，历史旧分支完整保留在树中；`fork` 从指定 Entry 复制主线生成独立新会话；
- **Workspace 隔离**：会话文件统一持久化在 `<workspace>/.my_agent_core/sessions/`，跨项目天然物理隔离。

### 3. 我们的裁剪与创新

- **逐条原子落盘（Crash-Safe Atomic Write）**：每次追加消息均通过 `tempfile.mkstemp` 写入 ➔ `os.fsync` 强制刷盘 ➔ `os.replace` 原子覆盖，即使进程强杀或断电，磁盘文件也永不损坏。

---

## 六、上下文四层廉价优先压缩管线 (`my_agent_core.context`)

### 1. 参考项目与源码定位

- **主要参考**：
  - **Pi (`packages/agent/src/harness/compaction/compaction.ts`)**：廉价优先多层压缩思想（Cheap-first Pipeline）与 `retainedTail` 缓存机制；
  - **OpenHands (`openhands.sdk.context.condenser`)**：LLM 摘要提示词防注入与先分析再总结（`<analysis>` / `<summary>` 标签剥离）。

### 2. 核心借鉴的设计机制

- **四层廉价优先流水线（L3 ➔ L1 ➔ L2 ➔ L4）**：
  1. **L3 大结果落盘**：超大工具输出写入磁盘文件，上下文内替换为文件路径引用（0 API 开销）；
  2. **L1 裁切中间轮次**：保留系统提示词与最近 $N$ 轮，裁切中间历史（0 API 开销）；
  3. **L2 旧结果占位**：历史过旧的工具输出替换为简短占位符（0 API 开销）；
  4. **L4 LLM 智能摘要**：仅当上述 3 层仍超预算时，才花费 1 次 API 调用生成结构化摘要。
- **Usage 锚定估算**：使用 `chars / 4` 兜底，并通过每轮实测的 `Response.usage` 动态校准 Token 计数；
- **`compaction_floor` 护栏**：压缩后指针被锁定在压缩点之后，防止指针回退导致历史压缩缓存失效。

### 3. 我们的裁剪与创新

- **Non-destructive View Transformation（非破坏性视图变换）**：`_ctx.prepare(messages)` 只生成用于传给 LLM 的压缩视图（`view`），真实会话历史保持完整无损。

---

## 七、Skills 技能机制 (`my_agent_core.skills`)

### 1. 参考项目与源码定位

- **主要参考**：
  - **Pi (`packages/agent/src/harness/skills.ts`)**：`SKILL.md` 标准、启动仅注入轻量清单（渐进式披露）、宿主显式加载；
  - **OpenHands (`openhands.sdk.skills`)**：YAML Frontmatter 解析与技能发现。

### 2. 核心借鉴的设计机制

- **渐进式披露的 Token 经济学**：
  - 启动阶段：只解析 `SKILL.md` 的 `name` 和 `description`，拼成极小的 `<available_skills>` 清单注入 System Prompt（单技能仅消耗几十 Token，不加载正文）；
  - 运行阶段：通过 `invoke_skill(name, instructions)` 显式加载完整操作正文进入上下文。

### 3. 我们的裁剪与创新

- **三态参数装配（`skill_dirs`）**：`None` 自动探测 `<cwd>/.agents/skills/`；`[]` 显式禁用；`list[Path]` 自定义加载；
- **`extra_dirs` 动态扩展**：支持接收 `PluginManager` 解构出的插件技能目录，实现插件技能自动发现。

---

## 八、Subagents 与 Task 任务委派 (`my_agent_core.subagents` & `tasks`)

### 1. 参考项目与源码定位

- **主要参考**：
  - **Claude Code 官方 Subagent 规范**：`.agents/agents/*.md` Markdown 声明式子代理定义；
  - **OpenHands (`openhands-tools/openhands/tools/task/manager.py`)**：`TaskManager` 任务生命周期状态机；
  - **Pi (`pi-subagents`)**：单工具桥接委派（`make_task_tool`）。

### 2. 核心借鉴的设计机制

- **独立子会话树（Child Session Isolation）**：子代理的全部思考与工具调用过程独立记录在 `<session_dir>/subagents/agent-task_*.jsonl`，父会话只接收最终的总结文本，主会话历史 0 污染；
- **单工具桥接（Tool as Bridge）**：大模型不需要感知复杂的进程通信，仅通过调用单一标准工具 `task(prompt, agent_type)` 即可完成任务委派。

### 3. 我们的裁剪与创新

- **严格的防递归与沙箱隔离不变式**：子代理创建时，强制执行：
  1. 工具过滤：排除 `task`（防无限递归派发）和 `memory`（防污染父记忆）；
  2. 参数隔离：强制传入 `subagent_dirs=[]`、`plugin_dirs=[]`、`memory_dir=False`，保证子代理在极简纯净的沙箱中运行。

---

## 九、Extension 扩展与命令路由机制 (`my_agent_core.extensions`)

### 1. 参考项目与源码定位

- **主要参考**：
  - **Pi (`packages/coding-agent/src/extensions/` & `ExtensionAPI`)**：静态注册面（`ExtensionAPI`）+ 动态调度总管（`ExtensionManager`）双面设计；本地斜杠命令 0 Token 前置调度。

### 2. 核心借鉴的设计机制

- **扩展三大能力收敛**：
  1. `@api.on(Event)`：订阅生命周期并执行拦截；
  2. `@api.tool(...)` / `api.register_tool(tool)`：注册业务工具（后加载覆盖机制，支持安全沙箱替换）；
  3. `@api.command("name")`：注册斜杠命令，CLI 前置反射分发。
- **本地 0 Token 命令调度（Bypass-LLM Dispatching）**：用户在终端输入 `/mcp`、`/stats` 等斜杠命令时，由 `ExtensionManager.handle_command` 直接反射调用本地 Python 函数返回结果，不调用大模型、不花 Token、不污染会话。

### 3. 我们的裁剪与创新

- **原生异步扩展加载**：支持 `async def extension(api)` 协程入口，使 MCP 等需要在启动期建立异步网络长连接的扩展能够无阻塞初始化；
- **坏扩展单点故障隔离**：加载扩展模块时通过 `try...except` 隔离，单个损坏扩展只打印 Warning，绝不崩溃主程序。

---

## 十、Memory 长期记忆系统 (`my_agent_core.memory`)

### 1. 参考项目与源码定位

- **主要参考**：
  - **Hermes Agent (`tools/memory_tool.py`)**：双 Store 架构、Frozen Snapshot 保护 Prefix Cache、字符预算硬约束、唯一子串匹配（Unique Substring Match）、超限引导整理（Consolidation）。

### 2. 核心借鉴的设计机制

- **双 Markdown Store 分区**：
  - `MEMORY.md`（上限 2200 字符）：存储 Agent 的客观技术笔记、环境事实、工具暗坑；
  - `USER.md`（上限 1375 字符）：存储用户的主观画像、沟通习惯、编码风格。
- **Frozen Snapshot（冻结快照）核心不变式**：
  - 启动时 `load_from_disk()` 一次性捕获 `_snapshot` 冻结注入 System Prompt；
  - 运行中大模型调用 `add`/`replace`/`remove` 仅原子更新磁盘，**当前会话的 `_snapshot` 绝对静止**，100% 守卫大模型 Prompt Prefix Cache 不失效；
  - 下次启动新会话或调用 `agent.reset()` 时重载生效。
- **唯一子串匹配与歧义安全网**：
  - `replace` / `remove` 时通过关键词定位旧条目；
  - 若匹配到多条不同条目（歧义），系统**立即拒绝修改并打印冲突项**，强制要求模型提供更具区分度的词，彻底防止误改误删。

### 3. 我们的裁剪与创新

- **去重型生产依赖**：剔除 Hermes 原版的系统级排他文件锁（`fcntl/msvcrt`）、外部非标准编辑 `.bak` 备份流与复杂正则威胁扫描，用 ~240 行纯 Python 标准库代码实现完整闭环；
- **Never-Throw 异常自愈**：缺少入参时工具抛出的 `ValueError` 由底层自动转为结构化错误，引导大模型自我纠错。

---

## 十一、Claude Code 风格 Plugin 插件系统 (`my_agent_core.plugins`)

### 1. 参考项目与源码定位

- **主要参考**：
  - **Claude Code 官方插件规范 (`code.claude.com/docs/zh-CN/plugins`)**：标准插件目录拓扑（`.claude-plugin/plugin.json`、`skills/`、`agents/`、`.mcp.json`）与根级单 `SKILL.md` 简写；
  - **OpenHands (`openhands-sdk/openhands/sdk/plugin/format/claude_code.py`)**：Manifest 优先级查找与目录名智能推断兜底（Fallback Inference）。

### 2. 核心借鉴的设计机制

- **Manifest 极简优先级查找**：
  - 顺序查找：`.claude-plugin/plugin.json` ➔ `.plugin/plugin.json` ➔ `./plugin.json`；
  - **智能兜底（Fallback Infer）**：无清单时自动以目录名推断生成默认 `PluginManifest(name=dir.name)`，纯本地手写插件 0 门槛即插即用；
- **单 Skill 插件简写支持**：根目录直接放置 `SKILL.md` 的极简单技能插件自动被识别为独立插件加载；
- **自包含资源解构**：`PluginManager` 仅专注解构出各组件的物理路径，无缝注入 `SkillManager` 与 `SubagentManager`，0 重复造轮子。

### 3. 我们的裁剪与创新

- **Windows BOM 容错**：强制采用 `utf-8-sig` 解析 `plugin.json`，解决 Windows 下的解析崩溃；
- **不可变数据实体**：使用 `@dataclass(frozen=True)` 定义 `PluginAuthor` 与 `PluginManifest`，建立不可变契约防腐层。

---

## 十二、产品层 Coding 工具与原生异步 MCP 客户端 (`my_coding_agent`)

### 1. 参考项目与源码定位

- **主要参考**：
  - **OpenHands (`openhands-tools/openhands/tools/file_editor`)**：工作区路径穿越安全防护（`_safe_path`）；
  - **Model Context Protocol (MCP) 官方 Python SDK (`mcp`)**：`stdio_client`、`ClientSession`、JSON-RPC 2.0 通信协议；
  - **Pi (`pi-mcp-adapter`)**：MCP 工具动态包装与 Schema 转换。

### 2. 核心借鉴的设计机制

- **`AsyncExitStack` 双扇门生命周期管理**：
  - 第一扇门：物理传输层（`stdio_client` 操作系统子进程管道）；
  - 第二扇门：协议层（`ClientSession` JSON-RPC 2.0 会话）；
  - 通过 `AsyncExitStack` 优雅管理多层异步上下文，关闭时自动倒序安全释放资源；
- **闭包工厂消除延迟绑定陷阱**：在循环包装 MCP 远程工具时，使用 `_make_handler(conn, tool_name)` 独立工厂函数，确保每个工具在内存中精确绑定属于自己的连接与工具名；
- **工作区安全逃逸防护（`_safe_path`）**：`read`、`write`、`edit` 工具严格校验目标路径必须在 `workspace` 根目录之内，拦截 `../../etc/passwd` 等路径穿越攻击。

### 3. 我们的裁剪与创新

- **分层彻底归位**：编码文件工具与 MCP 客户端作为具体应用场景，彻底从框架层剥离到产品层（`my-coding-agent`），使框架核心 `my-agent-core` 保持绝对通用与纯净；
- **声明式并发加速**：MCP 远程只读工具默认标记 `is_parallel_safe=True`，多工具调用时直接享受 `asyncio.gather` 并发加速。

---

## 全景参考映射总结表

| 核心模块 | 对应源码路径 | 主要参考项目 | 核心借鉴机制 |
| --- | --- | --- | --- |
| **模型边界层** | `packages/my-agent-llm/` | Pi, Anthropic, DeepSeek | 统一多模型门面、流式增量拼接、Usage 锚定 |
| **工具系统** | `my_agent_core/tools/` | pig-mono, OpenHands, Pi | Pydantic 动态建模、Never-Throw 保证、`is_parallel_safe` 并发 |
| **事件拦截** | `my_agent_core/events.py` | Pi (`hooks.md`) | 五大生命周期决策拦截点、HookResult 统一干预、流式熔断丢弃半截 |
| **异步循环** | `my_agent_core/agent.py` | Pi (`agent-loop.ts`), pig-mono | 单层类内联 ReAct 循环、纯协程驱动、临时视图零污染 |
| **会话持久化** | `my_agent_core/session.py` | Pi (`jsonl-storage.ts`), pig-mono | 树状分支存储、`rewind/fork`、逐条临时文件原子刷盘 |
| **上下文压缩** | `my_agent_core/context.py` | Pi (`compaction.ts`), OpenHands | 四层廉价优先管线 (L3➔L1➔L2➔L4)、retainedTail 缓存、防注入标签剥离 |
| **Skills 机制** | `my_agent_core/skills.py` | Pi (`skills.ts`), OpenHands | 渐进式披露、启动仅注入清单、`invoke_skill` 显式调用 |
| **Subagents** | `my_agent_core/tasks.py` | Claude Code, OpenHands, Pi | 独立子会话树、防递归工具过滤、子代理沙箱隔离 |
| **Extension** | `my_agent_core/extensions/` | Pi (`ExtensionAPI`) | 静态注册面 + 动态调度、本地 0 Token 命令行前置路由 |
| **Memory 系统** | `my_agent_core/memory.py` | Hermes Agent (`memory_tool.py`) | 双 Store 分区、Frozen Snapshot 保护 Prefix Cache、唯一子串匹配 |
| **Plugin 系统** | `my_agent_core/plugins.py` | Claude Code 官方, OpenHands | `.claude-plugin/plugin.json`、目录名兜底推断、单 Skill 根级简写 |
| **Coding & MCP** | `packages/my-coding-agent/` | OpenHands, MCP SDK, Pi | `_safe_path` 路径安全、`AsyncExitStack` 异步双扇门管理、闭包工厂 |
