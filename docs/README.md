# my-pi-agent 技术设计文档与架构规范

本项目（`my-pi-agent`）是一个从零手写、纯原生异步、零外部重依赖的 Python Agent 运行时 SDK 与产品套件。
项目采用 **“对标 Tau 的单一 Python 核心内核 + 基于 Pi 原厂 @earendil-works/pi-tui 的独立表现层”** 双核拓扑架构。

本文档库（`docs/`）详细记录了整个工程中所有核心模块的技术架构规范、类关系图、数据流转机制与关键设计不变式。

---

## 架构总览与双核拓扑设计

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                          my-pi-agent 双核架构全景                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  【终端交互表现层】: tui/ (Node.js / TypeScript, 基于 @earendil-works/pi-tui)│
│    • TuiMainScreen 极速差量重绘器（保留终端原生历史与鼠标滚轮翻看）           │
│    • CSI 2026 垂直同步刷新屏障（彻底消灭字符撕裂与屏幕闪烁）                  │
│    • 24-bit TrueColor 调色盘 (dark.json) 与柔和卡片视觉系统                 │
│    • 流式 Markdown 增量渲染 + 动态可折叠思考过程区块 (AssistantMessage)      │
│    • 圆角边框工具调用卡片 + 点阵 Spinner 动效 + 实时耗时统计 (ToolExecution)  │
│    • 定制编辑器 (CustomEditor) 顶部边框实时嵌入高频转圈 (── ⠸ Working ──)   │
│    • 快捷键 Shift+Tab / Ctrl+T 轮转思考深度，按模型能力动态夹逼与边框变色     │
│    • 上下文压缩卡片 [compaction] 可折叠卡片与 Ctrl+O 展开全文                │
│    • 树状会话 DAG 视图 (/tree) 与分叉 (/fork)、克隆 (/clone)、删除保护 (Ctrl+D)│
│    • 模糊匹配路径联想 (@) 与斜杠命令浮窗 (/) 补全 (CombinedAutocomplete)    │
│  ─────────────────────────────────────────────────────────────────────────  │
│                                      │                                      │
│                                      │ 跨进程双向 stdio 协议 (JSON-RPC 2.0) │
│                                      ▼                                      │
│  【后端业务与产品层】: src/my_coding_agent (Python 3.12 / 纯无头业务层)      │
│    • CodingAgent 组装门面（Dual API: run 与 run_stream）                    │
│    • 7 大工作区安全编码文件工具 (read / write / edit / bash / grep / find / ls)│
│    • FileMutationQueue 单文件细粒度并发写锁                                 │
│    • PermissionGate 业务权限审查门禁 (Accept-on-Diff 词级反色高亮)          │
│    • 全量 Token 与成本核算（Prompt Cache 命中率 CH%、模型费率映射、Context 视口）│
│    • FileReferenceParser 提示词 @ 文件引用正则解析与首轮源码快照直通注入     │
│    • Turnkey MCP 客户端自动加载与进程生命周期安全回收                        │
│    • rpc_server.py stdio JSON-RPC 2.0 服务端门面与跨线程安全调度            │
│  ─────────────────────────────────────────────────────────────────────────  │
│                                                                             │
│  【框架微内核层 SDK】: src/my_agent_core (Python 3.12)                      │
│    • 单层 Agent 类 (AgentHarness + prompt_stream 事件流一等公民)            │
│    • loop.py 纯函数微内核 (约 110 行无状态状态机 + 两个专职子生成器)         │
│    • 工业级七阶段工具流水线（截断防御/畸形防崩/Preflight/门禁/进度/改写/熔断）│
│    • tool_history.py 对话转录本三阶段自愈 (免疫 LLM API 400 校验死锁)        │
│    • 工具系统 (Tool / @tool / ToolRegistry 原生字典分发 / 免 4x JSON 编解码) │
│    • 12 个只读生命周期事件 (events.py) + 五大专职拦截门禁 (hooks.py) 正交解耦│
│    • 模块化会话存储子系统 (session/ 7 模块 + 9 种多态条目 + 只追加持久化)   │
│    • 四层廉价优先上下文压缩管线 (L3➔L1➔L2➔L4 + retainedTail 缓存)           │
│    • Skills 声明式管理 (SKILL.md 发现 / 启动轻量清单注入 / 显式调用)        │
│    • Subagents 任务委派 (独立子会话树 / 防递归工具过滤 / 沙箱隔离)          │
│    • Extension 扩展机制 (ExtensionAPI 契约 / 0 Token 本地命令路由)          │
│    • Memory 长期记忆系统 (MemoryStore 双 Store / Frozen Snapshot 保护缓存)  │
│    • Plugin 插件聚合分发系统 (Claude Code 标准目录 / 智能推断 / 资源解构)   │
│    • 统一任务系统 (TaskItem + TaskStore DAG 依赖) + BackgroundRunner 后台引擎│
│    • MessageQueue 动态干预队列（Steer 即时转向 & Follow-up 宏观任务排队）   │
│  ─────────────────────────────────────────────────────────────────────────  │
│                                                                             │
│  【模型边界层 SDK】: src/my_agent_llm (Python 3.12)                         │
│    • 统一 LLM 门面 (chat / stream / achat / achat_stream)                   │
│    • 结构化 ToolCall (args: dict) 一等公民生产与 TurnOutcome 中立化状态机   │
│    • 四大 Provider (Antigravity Google internal SSE 直连 / DeepSeek / OpenAI / Anthropic)│
│    • AntigravityAuthResolver 动态凭据自省与自动静默刷新 (零硬编码密钥)       │
│    • 动态模型目录获取与 4 小时磁盘缓存（Antigravity 别名收敛 / DeepSeek 列表同步）│
│    • 流式 Tool Calls 增量聚合与末块 Response 实体直接交付                   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 文档目录索引

### 1. 模型边界层 (`docs/llm/`)

- [01-llm-boundary.md](llm/01-llm-boundary.md)：统一模型门面、结构化 `ToolCall`（`args: dict`）一等公民生产、`TurnOutcome` 中立化单轮终止状态机、多 Provider 协议转换与末块 `Response` 实体直接交付。

### 2. 框架核心层 (`docs/core/`)

- [01-tool-system.md](core/01-tool-system.md)：基于 Pydantic 的 `@tool` 动态建模、`Tool` 实体、结构化 `ToolCall` 原生消费、`ToolRegistry` 字典直接分发（免 4x JSON Ping-Pong）、读写分流并发批执行与 Never-Throw 保证。
- [02-event-hooks.md](core/02-event-hooks.md)：12 个纯只读事实事件（`events.py`）与五大专职 Hook 决策拦截点（`hooks.py`）彻底正交解耦、`HookResult` 统一干预模型与 Pi 官方时序契约。
- [03-agent-loop.md](core/03-agent-loop.md)：Tau 风格单层 `AgentHarness`、`loop.py` 纯函数微内核（约 110 行优雅状态机）、子生成器分治（`_assistant_turn` 与 `_execute_tools_turn`）、七阶段工具执行流水线、`tool_history.py` 转录本三阶段自愈与一等公民 `prompt_stream` 事件流。
- [04-session-tree.md](core/04-session-tree.md)：树状会话存储子系统（`session/` 7 模块分工）、9 种强类型判别多态 `SessionEntry`、纯内存防环树算法、`SessionState` 事件溯源折叠投影与只追加纯异步存储驱动（跨进程文件锁）。
- [05-context-compaction.md](core/05-context-compaction.md)：四层廉价优先上下文压缩管线（L3➔L1➔L2➔L4）、Usage 动态校准、`retainedTail` 持久化缓存与 `compaction_floor` 护栏。
- [06-skills.md](core/06-skills.md)：Skills 声明式管理机制、`SKILL.md` 元数据解析、渐进式披露 Token 优化与 `invoke_skill` 宿主显式触发。
- [07-subagents-tasks.md](core/07-subagents-tasks.md)：Subagents 声明式多智能体与 `TaskManager` 生命周期管理、独立子会话树隔离与防递归沙箱防护。
- [08-extensions.md](core/08-extensions.md)：Extension 扩展机制、`ExtensionAPI` 开发者契约、模块隔离加载与本地 0 Token 命令调度。
- [09-memory.md](core/09-memory.md)：Memory 长期记忆系统、`MemoryStore` 双 Store 分区、Frozen Snapshot 保护 Prefix Cache、唯一子串匹配与受控维护工具。
- [10-plugins.md](core/10-plugins.md)：Claude Code 官方标准 Plugin 插件系统、Manifest 优先级查找与智能兜底推断、自包含资源解构分发。
- [11-dynamic-steering.md](core/11-dynamic-steering.md)：Pi 风格即时转向（Steer）与排队追问（Follow-up）双层调度引擎、三大切入安全点与取消隔离。
- [12-task-system-and-background.md](core/12-task-system-and-background.md)：统一任务系统（`TaskItem` + `TaskStore` DAG 依赖）、`<TASK_BOARD>` 上下文看板自动投影与具备孤儿进程防御的 `BackgroundRunner` 后台异步执行引擎。

### 3. 产品与编码层 (`docs/coding/`)

- [01-workspace-tools.md](coding/01-workspace-tools.md)：工作区编码工具集与并发控制规范（7 大核心工具 `read` / `write` / `edit` / `bash` / `grep` / `find` / `ls` 规范、`resolve_path` 宽松 CWD 解析、`FileMutationQueue` 细粒度并发锁、`FileReferenceParser` 提示词 `@` 文件快照直通注入）。
- [02-mcp-integration.md](coding/02-mcp-integration.md)：原生 MCP 客户端与扩展集成规范（`MCPClientManager`、stdio/SSE 子进程管理、工具自动发现与 Schema 平坦化、工作区 `.mcp.json` 按需加载）。
- [03-coding-agent-facade.md](coding/03-coding-agent-facade.md)：CodingAgent 产品门面与提示词装配规范（Dual API: `run` / `run_stream`、`build_default_coding_prompt`、`<project_context>` 自动发现 `AGENTS.md` / `CLAUDE.md`、五大专职 Hook 拦截机制）。
- [04-user-home-and-settings.md](coding/04-user-home-and-settings.md)：用户主目录、配置与凭据隔离体系规范（`~/.my-pi-agent/` 目录拓扑、`auth.json` 多模型凭据管理、`settings.json` 双层级联配置、`sessions/<slug>-<hash>/` 集中式零污染会话持久化、`trust.json` 项目信任安全策略）。
- [05-rpc-bridge-protocol.md](coding/05-rpc-bridge-protocol.md)：前后端通信协议与内核桥接规范（stdio JSON-RPC 2.0 规范、`KernelBridge` 客户端驱动、会话 DAG 操作 `/tree` / `/fork` / `/clone` / `/resume` 删除防御、全量 Token 与成本动态核算公式、Prompt Cache 命中率 `CH%`）。
- [06-pi-tui-interactive-terminal.md](coding/06-pi-tui-interactive-terminal.md)：Pi-TUI 交互式终端与表现层规范（基于 `@earendil-works/pi-tui` 的 `AgentApp` / `InteractiveMode` 架构、`CustomEditor` 顶部边框嵌入式 `── ⠸ Working ──` 动效与快捷键思考预算自适应轮转、三大交互式选择器 Model/Session/Thinking、可折叠压缩卡片、全套斜杠命令与输入宏）。
- [07-distribution-and-packaging.md](coding/07-distribution-and-packaging.md)：工程发布、全平台分发与全局 CLI 规范（npm workspaces 与 `npm link` 全局命令 `my-pi-agent` / `my-agent`、uv 单一虚拟环境、跨平台独立分发路线）。

### 4. 原厂对齐审计与分发部署 (`docs/`)

- [PI_ALIGNMENT_AUDIT.md](PI_ALIGNMENT_AUDIT.md)：Pi 官方实现 1:1 对标审计报告（涵盖核心微内核、工具契约、会话 DAG 分支、上下文压缩与 TUI 组件）。
- [DISTRIBUTION.md](DISTRIBUTION.md)：全平台 CLI 分发指南（npm link / uv / 全局单命令接入）。

### 5. 外部调研与对标分析 (`docs/references/`)

- [tau-analysis.md](references/tau-analysis.md)：深度调研与剖析 `tau-ai`（Python 版 Pi Harness 框架）三层架构，横向对比 TUI 终端界面、OAuth 认证链、JSONL RPC 模式、models.dev 动态模型库、会话历史自愈机制与演进路线图。

---

## 核心设计原则与架构不变式

1. **Never-Throw Guarantee（工具、Hook 与自愈永不崩溃）**：
   任何工具执行、参数校验或 Hook 拦截异常必须包装为 `ToolResult(ok=False, error=...)` 或安全捕获跳过，绝不允许未捕获异常导致 Agent 崩溃，引导大模型自我修正。
2. **Crash-Safe Atomic Persistence（原子写盘与只追加驱动）**：
   所有涉及磁盘文件持久化的操作均必须具备崩溃安全保证（会话只追加配合跨进程锁、记忆 Markdown 采用 `tempfile.mkstemp` 写入 ➔ `os.fsync` 刷盘 ➔ `os.replace` 原子覆盖），断电永不损坏文件。
3. **Prefix Cache Invariant（前缀缓存保护）**：
   会话进行中，System Prompt 全程保持绝对静止（Frozen Snapshot），运行时记忆写入只更新磁盘不动当前快照；`BeforeModelCallHook` 临时视图修改绝不污染底层会话历史。
4. **Subagent Sandbox Isolation（子代理沙箱隔离）**：
   派发子代理时，子 Agent 必须显式配置 `plugin_dirs=[]`、`subagent_dirs=[]`、`memory_dir=False` 并过滤 `task` 工具，彻底防止递归探测与状态冲突。
5. **Dual-Core Process Decoupling（双核进程彻底解耦）**：
   前端 Node.js TUI 与后端 Python 业务内核严格通过无状态 stdio JSON-RPC 2.0 管道隔离，Python 侧维持 100% 纯无头，无任何终端 UI 依赖。
