# my-pi-agent

**当前最好的 Python 语言 agent 框架学习项目**——从零手写一个最小但完整的 agent 框架。
只依赖通用库（`openai` SDK、`pydantic`、`pyyaml`、`mcp` 等）与标准库，**不引入任何 agent 框架**（langchain / langgraph 等），每一行代码都可审查。

- 📖 **博客专栏**：[my-pi-agent 学习笔记与架构剖析](https://zxj-2023.github.io/categories/agent%E5%AE%9E%E6%88%98/my-pi-agent/)

---

## 为什么从零实现

市面上的 Python agent 框架很难找到称心的：要么完全依赖 AI 搭建，结构与实现冗杂、难以阅读；
要么来自 TypeScript 生态，Python 实现偏少；而选择 Python 的大多直接套 langchain / langgraph——
框架成了黑盒，底层原理与设计取舍都来不及亲自验证。

自己实现一个 agent 框架：

- **从底层学习**：ReAct 循环、原生异步流式、五大决策拦截点、树状会话回溯、分层上下文压缩、MCP 协议桥接……每个环节亲手实现一遍，才能真正理解 agent 的底层原理
- **灵活可控**：不是所有场景都需要复杂的图编排；自研框架按需定制，配合业务需求更轻量高效
- **工程规范**：严格遵循 TDD（测试先行）、100% 离线单元测试覆盖、Never-Throw 异常边界隔离、原子文件落盘与架构不变式约束

## 风格

**简洁、规范、零过度设计**——只做当前需求的最小实现，接口边界干净、职责单一、测试先行。
代码即使由 AI 辅助生成，也**逐行人工审查**（这是投入最多的部分），实现思路与
结构管理在此基础上反复打磨完善。

## 参考

功能实现整合参考 **pi**（[earendil-works/pi](https://github.com/earendil-works/pi)）、
**pig-mono**（[kangkona/pig-mono](https://github.com/kangkona/pig-mono)）、
**learn-claude-code**（[shareAI-lab/learn-claude-code](https://github.com/shareAI-lab/learn-claude-code)）、
**Hermes Agent**（[hermes-agent](https://github.com/NousResearch/Hermes-Agent)）与
**OpenHands**（[software-agent-sdk](https://github.com/All-Hands-AI/OpenHands)）等标杆项目的架构思路。
详细的技术设计参考、源码映射与裁剪对比见根目录的 **[REFERENCES.md](REFERENCES.md)**。

---

## 已实现功能

### 1. 模型边界层 `my-agent-llm`（[学习笔记](https://zxj-2023.github.io/2026/08/05/%E5%AD%A6%E4%B9%A0/agent%E5%AE%9E%E6%88%98/my-pi-agent/my-pi-agent--%E6%A8%A1%E5%9E%8B%E5%B1%82/)）

- **统一 `LLM` 门面**：`chat` / `stream` / `achat` / `achat_stream` 四组接口，屏蔽多供应商差异
- **三大 Provider**：`openai`（基准翻译）/ `deepseek`（继承 + reasoning 提取）/ `anthropic`（block 翻译 + web_search 过滤）
- **流式增量聚合**：`StreamChunk` 流式 tool_calls 增量拼装 + usage 捕获（末块携带完整统计）
- **核心模型**：不可变 `Config`（Pydantic frozen）、`Message`、`Response`

### 2. 框架核心层 `my-agent-core`

- **[工具系统（tools & registry）](https://zxj-2023.github.io/2026/07/31/%E5%AD%A6%E4%B9%A0/agent%E5%AE%9E%E6%88%98/my-pi-agent/my-pi-agent--%E5%B7%A5%E5%85%B7%E7%B3%BB%E7%BB%9F/)**：
  - `@tool` 装饰器：基于 Pydantic 动态提取函数签名生成 OpenAI/Anthropic 兼容的 JSON Schema
  - `Tool` 实体：支持 `raw_schema`（外部/远程 Schema 透传）与 `is_parallel_safe`（声明式并发标记）
  - `ToolRegistry`：支持单查、批量获取 Schema、`execute_batch` 异步并发/串行智能分流执行与保序回填
  - `ToolResult` 与 **Never-Throw 架构保证**：工具异常绝不向上抛崩 Agent，统一包装为结构化错误供大模型自愈
- **[生命周期事件与五大决策拦截点（events & hooks）](https://zxj-2023.github.io/2026/07/31/%E5%AD%A6%E4%B9%A0/agent%E5%AE%9E%E6%88%98/my-pi-agent/my-pi-agent--agent%E7%B1%BB%E4%B8%8Ehook%E7%B3%BB%E7%BB%9F/)**：
  - 12 个生命周期事件 dataclass（涵盖 Agent、Turn、Message、Tool、Context 阶段）
  - **五大生命周期决策拦截点**：
    1. `UserInput`（`input`）：截获用户原始输入，支持 `block` 阻断或 `updated_input` 前置改写；
    2. `AgentStart`（`before_agent_start`）：启动前拦截，支持 `updated_system_prompt` 动态更新首条 system 消息；
    3. `BeforeModelCall`（`context`）：调 LLM 前拦截，支持 `updated_messages` 临时改写视图（**临时 View 改写 vs 真实 Session 零污染**）；
    4. `ToolExecutionStart`（`tool_call`）：工具执行前拦截，支持 `block` 拦截危险命令或 `updated_args` 修补参数；
    5. `ToolExecutionEnd`（`tool_result`）：工具执行后拦截，支持 `updated_result` 篡改出参。
  - `MessageUpdate`：流式生成中的 Token 级实时熔断（掐断时**丢弃未完成半截文本**，防止模型断句幻觉）
  - 统一干预模型：`HookResult` dataclass
- **[Agent 内联循环与原生异步驱动（agent & async）](https://zxj-2023.github.io/2026/08/15/%E5%AD%A6%E4%B9%A0/agent%E5%AE%9E%E6%88%98/my-pi-agent/my-pi-agent--%E5%BC%82%E6%AD%A5%E6%94%AF%E6%8C%81/)**：
  - 单层 `Agent` 类设计（状态 + 内联 ReAct 循环 + 工具派发 + Hook 织入）
  - 100% 纯原生异步 API：`await agent.run(prompt)`，支持多轮自动决策与工具调用
  - 状态管理：`reset()` 重置会话并重拼提示词、`abort()` 异步中断任务、`max_iterations` 迭代上限保护
- **[会话持久化（session）](https://zxj-2023.github.io/2026/08/10/%E5%AD%A6%E4%B9%A0/agent%E5%AE%9E%E6%88%98/my-pi-agent/my-pi-agent--session%E7%AE%A1%E7%90%86/)**：
  - 树状会话结构：`SessionEntry`（带 id、parent_id）+ `SessionTree` + 当前指针 `current_id`
  - 逐条原子落盘（临时文件 + `fsync` + `os.replace`），崩溃永不损坏历史
  - `rewind`（指针回退，分支保留）+ `fork`（分叉派生新会话）
  - Workspace 目录隔离（`<workspace>/.my_agent_core/sessions`）
- **[上下文管理与压缩（context）](https://zxj-2023.github.io/2026/08/11/%E5%AD%A6%E4%B9%A0/agent%E5%AE%9E%E6%88%98/my-pi-agent/my-pi-agent--context%E7%AE%A1%E7%90%86/)**：
  - `ContextManager` 四层压缩管线（cheap-first）：L3 大结果落盘 ➔ L1 裁切中间轮次 ➔ L2 旧结果占位（0 API 耗损）➔ L4 LLM 智能摘要（超阈才花 1 次 API）
  - Usage 锚定估算（`chars / 4` 兜底 + `Response.usage` 实测校准）
  - `retainedTail` 缓存（摘要 + 尾部快照持久化为 `compaction` entry，重启免重算）
  - `compaction_floor` 护栏：压缩后指针只能回退到压缩点之后，缓存永不失效
  - 摘要提示词防注入隔离（`<analysis>` / `<summary>` 标签剥离）
- **[Skills 声明式管理（skills）](https://zxj-2023.github.io/2026/08/14/%E5%AD%A6%E4%B9%A0/agent%E5%AE%9E%E6%88%98/my-pi-agent/my-pi-agent--skill%E4%B8%8Eplugin/)**：
  - 三态目录发现（默认探测 `<cwd>/.agents/skills/` / 显式禁用 / 自定义目录）
  - `SKILL.md` YAML 元数据与 Markdown 正文解析
  - 启动阶段仅将轻量 Skills 清单注入 System Prompt，省 Token 且无工具调用开销
  - `invoke_skill` 宿主显式触发机制
- **[Subagents 与 Task 任务委派（subagents & tasks）](https://zxj-2023.github.io/2026/08/15/%E5%AD%A6%E4%B9%A0/agent%E5%AE%9E%E6%88%98/my-pi-agent/my-pi-agent--subagent%E4%B8%8Etask%E5%A7%94%E6%B4%BE/)**：
  - `.agents/agents/*.md` 声明式子代理配置发现
  - `TaskManager` 任务生命周期状态机管理（`RUNNING` ➔ `COMPLETED` / `ERROR`）
  - **隔离子会话**：独立落盘于 `<session_dir>/subagents/agent-task_*.jsonl`，父会话不被子代理中间过程污染
  - **防递归与隔离机制**：子代理继承工具时强制过滤 `task` 与 `memory` 工具，并显式配置 `subagent_dirs=[]` 与 `memory_dir=False`
  - `make_task_tool` 桥接：将子代理委派转化为单一标准工具 `task(prompt, agent_type)` 供主模型调用
- **[Extension 扩展机制（extensions）](https://zxj-2023.github.io/2026/08/15/%E5%AD%A6%E4%B9%A0/agent%E5%AE%9E%E6%88%98/my-pi-agent/my-pi-agent--extension%E6%9C%BA%E5%88%B6%E4%B8%8Emcp/)**：
  - 静态注册面 `ExtensionAPI` + 调度总管 `ExtensionManager`
  - 模块动态发现与加载（支持 `async def extension(api)` 与同步 `def` 入口，单点故障隔离保护）
  - 核心能力三件套：
    1. `@api.on(Event)`：订阅 12 个生命周期事件，支持 `@overload` 类型推导与五大决策点拦截干预；
    2. `@api.tool(...)` / `api.register_tool(tool)`：注册业务工具（后加载静默覆盖机制，赋能安全沙箱替换）；
    3. `@api.command("name")`：注册斜杠命令，CLI 前置反射分发（0 Token 消耗，不污染历史）。
- **[记忆系统（memory）](https://zxj-2023.github.io/2026/08/27/%E5%AD%A6%E4%B9%A0/agent%E5%AE%9E%E6%88%98/my-pi-agent/my-pi-agent--memory%E7%B3%BB%E7%BB%9F/)**：
  - `MemoryStore` 条目化存储：管理 `MEMORY.md`（上限 2200 字符）与 `USER.md`（上限 1375 字符），使用 `\n§\n` 条目切分与原子落盘
  - **Frozen Snapshot（冻结快照）机制**：构造时冻结为 `<MEMORY_CONTEXT>` 注入 System Prompt；运行时写入只落盘不动快照，保护大模型 Prefix Cache 稳定；`reset()` 时重载
  - `make_memory_tool` 受控维护工具：提供 `memory(target, action, content, old_text, new_content)` 工具（支持 `add/replace/remove`、唯原子串定位匹配、歧义防误删、超限引导整理），支持跨 Session 长期记忆持久化与召回
- **[Plugin 插件分发系统（plugins）](https://zxj-2023.github.io/2026/08/14/%E5%AD%A6%E4%B9%A0/agent%E5%AE%9E%E6%88%98/my-pi-agent/my-pi-agent--skill%E4%B8%8Eplugin/)**：
  - **100% 对齐 Claude Code 官方插件规范**：自包含 `.claude-plugin/plugin.json`（或 `.plugin/plugin.json`）、`skills/`、`agents/`、`.mcp.json`，以及根级单 `SKILL.md` 简写支持
  - `PluginManager` 统一管理：负责插件发现、Manifest 容错解析与目录名智能推断兜底（无清单时自动以目录名生成默认元数据）
  - **无缝解构与分发**：在 `Agent.__init__` 装配时自动提取插件内的 `skills/` 注入 `SkillManager`、`agents/` 注入 `SubagentManager`，子代理派发时自动进行递归探测隔离保护
- **[动态干预机制与两层循环（message_queue & steering）](docs/core/11-dynamic-steering.md)**：
  - `MessageQueue` 动态干预队列：支持 `STEERING`（内层安全点转向）与 `FOLLOWUP`（外层排队追问）双类型消息
  - **经典两层循环架构（Two-Level Loop）**：外层处理 Follow-up 宏观任务流转，内层处理 ReAct 微观步骤与 Steer 转向
  - **三大安全点拦截**：Turn 起点原子落盘、工具批执行后即时插队、无工具输出期拦截早退
  - `TaskManager.steer_task(task_id, msg)`：支持对后台运行中的子代理进行定向动态纠偏与追问

### 3. 产品层 `my-coding-agent`

- **内置 Coding 工具集**：`read`、`write`、`edit`、`bash`，包含 `_safe_path` 路径穿越安全防护
- **MCP 客户端扩展（`mcp.py`）**：
  - 采用 Extension 插件形式实现，通过 `.mcp.json` 读取配置
  - `AsyncExitStack` 管理物理传输层（`stdio_client` 子进程）与协议层（`ClientSession`）的异步生命周期
  - JSON-RPC 2.0 协议交互与 Schema 动态透传（`raw_schema`）
  - 闭包工厂消除循环中的延迟绑定陷阱
  - 声明式 `is_parallel_safe=True` 赋予只读工具并发加速能力
  - `/mcp` 本地状态查看命令
- **`CodingAgent`**：开箱即用的代码助手 Agent 门面（预装编码工具集 + 自动加载 MCP 扩展）

---

## 快速开始

### 1. 安装与环境准备

本项目使用 [uv](https://docs.astral.sh/uv/) 进行工作区与依赖管理：

```powershell
# 1. 运行框架核心层 demo
cd packages/my-agent-core
uv sync
Copy-Item .env.example .env    # 填入真实 API 密钥
uv run python -m my_agent_core.main

# 2. 运行编码助手 demo
cd ../my-coding-agent
uv sync
uv run python -m my_coding_agent.agent
```

### 2. 运行离线测试套件

本项目所有单元测试均严格使用 FakeLLM 与模拟客户端，**100% 离线运行，无需网络或真实 API Key**：

```powershell
# 运行全部三个包的单元测试（277 tests）
cd packages/my-agent-core && uv run python -m pytest -q
cd ../my-agent-llm && uv run python -m pytest -q
cd ../my-coding-agent && uv run python -m pytest -q
```

---

## 仓库目录结构

```text
my-pi-agent/
├── docs/                           # 全套技术设计规范文档库 (14 篇模块规范 + 全景导航)
│   ├── README.md                   # 架构全景与文档索引
│   ├── llm/                        # 模型边界层规范 (01-llm-boundary.md)
│   ├── core/                       # 框架核心层规范 (01-tool-system.md ~ 11-dynamic-steering.md)
│   └── coding/                     # 产品与编码层规范 (01-file-tools.md, 02-mcp-client.md)
│
├── packages/
│   ├── my-agent-llm/               # 模型边界层独立 uv 项目 (36 tests)
│   │   ├── pyproject.toml          # src 布局 + hatchling 构建
│   │   ├── src/my_agent_llm/       # Python 包
│   │   │   ├── client.py           # LLM 门面（chat/stream/achat/achat_stream）
│   │   │   ├── config.py           # Config（pydantic frozen）
│   │   │   ├── models.py           # Message / Response / StreamChunk
│   │   │   └── providers/          # openai / deepseek / anthropic + 注册表
│   │   └── tests/                  # 离线测试（假 SDK 注入）
│   │
│   ├── my-agent-core/              # 框架核心层独立 uv 项目 (223 tests)
│   │   ├── pyproject.toml          # src 布局 + hatchling 构建
│   │   ├── src/my_agent_core/      # Python 包
│   │   │   ├── agent.py            # Agent 类（单层：异步两层循环 + 五大决策拦截点）
│   │   │   ├── message_queue.py    # MessageQueue 动态干预队列（Steer & Follow-up）
│   │   │   ├── tools/              # 工具系统（Tool / @tool / ToolRegistry / ToolResult）
│   │   │   ├── events.py           # 12 个生命周期事件 + HookResult 统一干预模型
│   │   │   ├── session.py          # SessionEntry + SessionTree + Session（树 + JSONL 原子落盘）
│   │   │   ├── session_store.py    # SessionStore（会话仓库，workspace 隔离）
│   │   │   ├── context.py          # ContextManager（四层压缩管线）+ ContextSessionBridge
│   │   │   ├── memory.py           # MemoryStore + make_memory_tool（长期记忆与快照管理）
│   │   │   ├── skills.py           # Skill / SkillManager（.agents/skills 发现与提示词注入）
│   │   │   ├── subagents.py        # Subagent / SubagentManager（.agents/agents 发现）
│   │   │   ├── tasks.py            # Task / TaskManager（子代理生命周期与独立会话隔离）
│   │   │   ├── extensions/         # ExtensionAPI + ExtensionManager（扩展加载与命令路由）
│   │   │   ├── plugins.py          # Plugin + PluginManager（Claude Code 插件聚合分发）
│   │   │   └── main.py             # 核心层 demo 入口
│   │   └── tests/                  # 离线测试
│   │
│   └── my-coding-agent/            # 产品层独立 uv 项目 (18 tests)
│       ├── pyproject.toml          # src 布局 + 依赖 core, llm, mcp
│       ├── src/my_coding_agent/    # Python 包
│       │   ├── tools.py            # 内置编码工具（read/write/edit/bash + _safe_path 沙箱）
│       │   ├── mcp.py              # MCP 客户端扩展（AsyncExitStack + JSON-RPC 2.0 桥接）
│       │   └── agent.py            # CodingAgent 组装门面
│       └── tests/                  # 离线测试
│
├── REFERENCES.md                   # 全模块架构设计参考溯源与工程复盘
├── PROGRESS.md                     # 项目进度复盘与详细演进记录
└── README.md                       # 仓库级总览（本文件）
```

---

## 架构文档与笔记索引

| 模块 | 对应源码 | 学习笔记链接 |
| --- | --- | --- |
| **全景架构** | 整体设计 | [my-pi-agent--架构设计](https://zxj-2023.github.io/2026/07/31/%E5%AD%A6%E4%B9%A0/agent%E5%AE%9E%E6%88%98/my-pi-agent/my-pi-agent--%E6%9E%B6%E6%9E%84%E8%AE%BE%E8%AE%A1/) |
| **模型边界层** | `my_agent_llm/` | [my-pi-agent--模型层](https://zxj-2023.github.io/2026/08/05/%E5%AD%A6%E4%B9%A0/agent%E5%AE%9E%E6%88%98/my-pi-agent/my-pi-agent--%E6%A8%A1%E5%9E%8B%E5%B1%82/) |
| **工具系统** | `my_agent_core/tools/` | [my-pi-agent--工具系统](https://zxj-2023.github.io/2026/07/31/%E5%AD%A6%E4%B9%A0/agent%E5%AE%9E%E6%88%98/my-pi-agent/my-pi-agent--%E5%B7%A5%E5%85%B7%E7%B3%BB%E7%BB%9F/) |
| **生命周期与 Hook** | `my_agent_core/events.py` | [my-pi-agent--agent类与hook系统](https://zxj-2023.github.io/2026/07/31/%E5%AD%A6%E4%B9%A0/agent%E5%AE%9E%E6%88%98/my-pi-agent/my-pi-agent--agent%E7%B1%BB%E4%B8%8Ehook%E7%B3%BB%E7%BB%9F/) |
| **原生异步驱动** | `my_agent_core/agent.py` | [my-pi-agent--异步支持](https://zxj-2023.github.io/2026/08/15/%E5%AD%A6%E4%B9%A0/agent%E5%AE%9E%E6%88%98/my-pi-agent/my-pi-agent--%E5%BC%82%E6%AD%A5%E6%94%AF%E6%8C%81/) |
| **会话持久化** | `my_agent_core/session.py` | [my-pi-agent--session管理](https://zxj-2023.github.io/2026/08/10/%E5%AD%A6%E4%B9%A0/agent%E5%AE%9E%E6%88%98/my-pi-agent/my-pi-agent--session%E7%AE%A1%E7%90%86/) |
| **上下文四层压缩** | `my_agent_core/context.py` | [my-pi-agent--context管理](https://zxj-2023.github.io/2026/08/11/%E5%AD%A6%E4%B9%A0/agent%E5%AE%9E%E6%88%98/my-pi-agent/my-pi-agent--context%E7%AE%A1%E7%90%86/) |
| **Skills 机制** | `my_agent_core/skills.py` | [my-pi-agent--skill与plugin](https://zxj-2023.github.io/2026/08/14/%E5%AD%A6%E4%B9%A0/agent%E5%AE%9E%E6%88%98/my-pi-agent/my-pi-agent--skill%E4%B8%8Eplugin/) |
| **Subagents 委派** | `my_agent_core/tasks.py` | [my-pi-agent--subagent与task委派](https://zxj-2023.github.io/2026/08/15/%E5%AD%A6%E4%B9%A0/agent%E5%AE%9E%E6%88%98/my-pi-agent/my-pi-agent--subagent%E4%B8%8Etask%E5%A7%94%E6%B4%BE/) |
| **Extension 与 MCP** | `my_agent_core/extensions/`, `mcp.py` | [my-pi-agent--extension机制与mcp](https://zxj-2023.github.io/2026/08/15/%E5%AD%A6%E4%B9%A0/agent%E5%AE%9E%E6%88%98/my-pi-agent/my-pi-agent--extension%E6%9C%BA%E5%88%B6%E4%B8%8Emcp/) |
| **Memory 记忆系统** | `my_agent_core/memory.py` | [my-pi-agent--memory系统](https://zxj-2023.github.io/2026/08/27/%E5%AD%A6%E4%B9%A0/agent%E5%AE%9E%E6%88%98/my-pi-agent/my-pi-agent--memory%E7%B3%BB%E7%BB%9F/) |
| **Plugin 插件系统** | `my_agent_core/plugins.py` | [my-pi-agent--skill与plugin](https://zxj-2023.github.io/2026/08/14/%E5%AD%A6%E4%B9%A0/agent%E5%AE%9E%E6%88%98/my-pi-agent/my-pi-agent--skill%E4%B8%8Eplugin/) |
| **动态干预与两层循环** | `my_agent_core/message_queue.py` | [docs/core/11-dynamic-steering.md](docs/core/11-dynamic-steering.md) |

---

## 未来演进路线 (Roadmap)

项目按阶段对标业界标杆机制持续迭代演进：

- [x] **Pi 风格的 Steer 与 Follow-up 动态干预机制**：
  - **`steer`（动态转向与即时纠偏）**：在 ReAct 循环执行过程中（工具执行间隙、无工具文本输出期等安全点），支持上层宿主或子代理调度器注入转向指令，使 Agent 实时调整执行方向，而无需中断会话或丢失已产生的上下文；
  - **`follow_up`（轮次边界任务追加）**：在当前 Turn 执行结束的自然边界自动拉取并衔接后续追问/队列任务，保持单会话连贯性；
  - **经典两层循环与交付模式**：支持 `one-at-a-time`（单步纠偏）与 `all`（批注入）消费模式，并在 `TaskManager` 中提供子代理定向干预（`steer_task` / `follow_up_task`）。
- [ ] **Task / Todo 系统（Phase 8）**：
  - 实现 `todo_write` 工具与 `TaskStore`，支持任务多层级拆解、实时状态机推进（`todo` ➔ `in_progress` ➔ `completed`）与悬浮看板投影。
- [ ] **Coding Agent CLI 交互层（`packages/my-coding-agent`）**：
  - 基于 `prompt_toolkit` 与 `rich` 的现代化终端交互 REPL；
  - 权限确认门控（落地于 `ToolExecutionStart` 拦截点）；
  - Plan 模式（只读调研 ➔ 方案批准 ➔ 执行落地）与 `AGENTS.md` 提示词自动注入。
- [ ] **底层可靠性与网络弹性**：
  - 流式中断与 429 / 5xx 指数退避重试；
  - 大模型 `stop_reason` 细粒度归一化处理。
