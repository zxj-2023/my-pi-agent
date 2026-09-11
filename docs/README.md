# my-pi-agent 技术设计文档与架构规范

本项目（`my-pi-agent`）是一个从零手写、纯原生异步、零外部重依赖的 Python Agent 运行时 SDK 与产品套件。

本文档库（`docs/`）详细记录了整个 Monorepo 三层架构中所有核心模块的技术架构规范、类关系图、数据流转机制与关键设计不变式。

---

## 架构总览与分层设计

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                          my-pi-agent 三层架构全景                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  【第 3 层：产品与应用层】: packages/my-coding-agent                        │
│    • CodingAgent 组装门面                                                   │
│    • 工作区安全编码文件工具 (read / write / edit / bash + _safe_path 防护)   │
│    • 原生异步 MCP 客户端扩展 (AsyncExitStack + JSON-RPC 2.0 桥接)            │
│  ─────────────────────────────────────────────────────────────────────────  │
│                                                                             │
│  【第 2 层：框架核心层 SDK】: packages/my-agent-core                        │
│    • 单层 Agent 类 (AgentHarness + prompt_stream 事件流一等公民)            │
│    • loop.py 纯函数微内核 (约 110 行无状态状态机 + 两个专职子生成器)         │
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
│  ─────────────────────────────────────────────────────────────────────────  │
│                                                                             │
│  【第 1 层：模型边界层 SDK】: packages/my-agent-llm                         │
│    • 统一 LLM 门面 (chat / stream / achat / achat_stream)                   │
│    • 结构化 ToolCall (args: dict) 一等公民生产与 TurnOutcome 中立化状态机   │
│    • 三大 Provider (OpenAI 基准 / DeepSeek 推理链 / Anthropic 原生 dict)    │
│    • 流式 Tool Calls 增量聚合与末块 Response 实体直接交付                   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 文档目录索引

### 1. 模型边界层 (`docs/llm/`)

- [01-llm-boundary.md](llm/01-llm-boundary.md)：统一模型门面、结构化 `ToolCall`（`args: dict`）一等公民生产、`TurnOutcome` 中立化单轮终止状态机、三大 Provider 协议转换与末块 `Response` 实体直接交付。

### 2. 框架核心层 (`docs/core/`)

- [01-tool-system.md](core/01-tool-system.md)：基于 Pydantic 的 `@tool` 动态建模、`Tool` 实体、结构化 `ToolCall` 原生消费、`ToolRegistry` 字典直接分发（免 4x JSON Ping-Pong）、读写分流并发批执行与 Never-Throw 保证。
- [02-event-hooks.md](core/02-event-hooks.md)：12 个纯只读事实事件（`events.py`）与五大专职 Hook 决策拦截点（`hooks.py`）彻底正交解耦、`HookResult` 统一干预模型与 Pi 官方时序契约。
- [03-agent-loop.md](core/03-agent-loop.md)：Tau 风格单层 `AgentHarness`、`loop.py` 纯函数微内核（约 110 行优雅状态机）、子生成器分治（`_assistant_turn` 与 `_execute_tools_turn`）、`tool_history.py` 转录本三阶段自愈与一等公民 `prompt_stream` 事件流。
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

- [01-file-tools.md](coding/01-file-tools.md)：工作区编码文件工具集（`read` / `write` / `edit` / `bash`）与 `_safe_path` 路径穿越逃逸防御。
- [02-mcp-client.md](coding/02-mcp-client.md)：原生异步 MCP 客户端扩展、`AsyncExitStack` 双扇门生命周期管理、JSON-RPC 2.0 转发与闭包工厂延迟绑定防护。

### 4. 外部调研与对标分析 (`docs/references/`)

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
