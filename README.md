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
**Tau**（Python 版 Pi Harness 标杆，纯函数微内核、历史自愈与模块化存储）、
**pig-mono**（[kangkona/pig-mono](https://github.com/kangkona/pig-mono)）、
**learn-claude-code**（[shareAI-lab/learn-claude-code](https://github.com/shareAI-lab/learn-claude-code)）、
**Hermes Agent**（[hermes-agent](https://github.com/NousResearch/Hermes-Agent)）与
**OpenHands**（[software-agent-sdk](https://github.com/All-Hands-AI/OpenHands)）等标杆项目的架构思路。
详细的技术设计参考、源码映射与裁剪对比见根目录的 **[REFERENCES.md](REFERENCES.md)** 以及专属对标报告 **[docs/references/tau-analysis.md](docs/references/tau-analysis.md)**。

---

## 📚 博客专栏文章目录与学习路线

全套框架实现笔记与技术思考已系统沉淀至个人博客专栏：[**my-pi-agent 学习笔记与架构剖析**](https://zxj-2023.github.io/categories/agent%E5%AE%9E%E6%88%98/my-pi-agent/)。涵盖从零手搓现代 Agent 运行时的全链路设计取舍与工程落地：

| 序号 | 模块主题 | 博客文章精读链接 | 核心技术要点 |
| :---: | :--- | :--- | :--- |
| 01 | **全局架构** | [架构设计](https://zxj-2023.github.io/2026/07/31/%E5%AD%A6%E4%B9%A0/agent%E5%AE%9E%E6%88%98/my-pi-agent/my-pi-agent--%E6%9E%B6%E6%9E%84%E8%AE%BE%E8%AE%A1/) | 三层分层架构、为什么不用 LangChain、自研设计哲学与演进路线 |
| 02 | **模型边界** | [模型层](https://zxj-2023.github.io/2026/08/05/%E5%AD%A6%E4%B9%A0/agent%E5%AE%9E%E6%88%98/my-pi-agent/my-pi-agent--%E6%A8%A1%E5%9E%8B%E5%B1%82/) | Provider 抽象、StreamAccumulator 流式聚合、ToolCall 结构化防穿帮 |
| 03 | **工具原语** | [工具系统](https://zxj-2023.github.io/2026/07/31/%E5%AD%A6%E4%B9%A0/agent%E5%AE%9E%E6%88%98/my-pi-agent/my-pi-agent--%E5%B7%A5%E5%85%B7%E7%B3%BB%E7%BB%9F/) | `@tool` Pydantic 提取、Never-Throw、因果并发安全、七阶段流水线 |
| 04 | **状态机外壳** | [Agent 类与 Hook 系统](https://zxj-2023.github.io/2026/07/31/%E5%AD%A6%E4%B9%A0/agent%E5%AE%9E%E6%88%98/my-pi-agent/my-pi-agent--agent%E7%B1%BB%E4%B8%8Ehook%E7%B3%BB%E7%BB%9F/) | `prompt_stream` 事件流、`_notify` 订阅广播、五大决策拦截门禁 |
| 05 | **调度微内核** | [Loop 微内核](https://zxj-2023.github.io/2026/08/30/%E5%AD%A6%E4%B9%A0/agent%E5%AE%9E%E6%88%98/my-pi-agent/my-pi-agent--loop%E5%BE%AE%E5%86%85%E6%A0%B8/) | 纯函数无状态 ReAct 循环、9 步时序、单向传送带队列管道 |
| 06 | **会话持久化** | [Session 管理](https://zxj-2023.github.io/2026/08/10/%E5%AD%A6%E4%B9%A0/agent%E5%AE%9E%E6%88%98/my-pi-agent/my-pi-agent--session%E7%AE%A1%E7%90%86/) | 树状分支 DAG、原子 JSONL 追加存储、跨进程文件锁与分支回溯 |
| 07 | **上下文优化** | [Context 管理](https://zxj-2023.github.io/2026/08/11/%E5%AD%A6%E4%B9%A0/agent%E5%AE%9E%E6%88%98/my-pi-agent/my-pi-agent--context%E7%AE%A1%E7%90%86/) | Cheap-first 四层压缩 (L3➔L1➔L2➔L4)、retainedTail 缓存 |
| 08 | **技能扩展** | [Skill 与 Plugin](https://zxj-2023.github.io/2026/08/14/%E5%AD%A6%E4%B9%A0/agent%E5%AE%9E%E6%88%98/my-pi-agent/my-pi-agent--skill%E4%B8%8Eplugin/) | 声明式元数据发现、Prompt 注入、Claude Code 插件规约解构 |
| 09 | **任务委派** | [Subagent 与 Task 委派](https://zxj-2023.github.io/2026/08/15/%E5%AD%A6%E4%B9%A0/agent%E5%AE%9E%E6%88%98/my-pi-agent/my-pi-agent--subagent%E4%B8%8Etask%E5%A7%94%E6%B4%BE/) | 子会话物理隔离、防递归保护、单任务生命周期管理与 `task` 桥接 |
| 10 | **生态接入** | [Extension 机制与 MCP](https://zxj-2023.github.io/2026/08/15/%E5%AD%A6%E4%B9%A0/agent%E5%AE%9E%E6%88%98/my-pi-agent/my-pi-agent--extension%E6%9C%BA%E5%88%B6%E4%B8%8Emcp/) | 动态扩展加载、斜杠命令路由、AsyncExitStack MCP 客户端 |
| 11 | **跨会话记忆** | [Memory 系统](https://zxj-2023.github.io/2026/08/27/%E5%AD%A6%E4%B9%A0/agent%E5%AE%9E%E6%88%98/my-pi-agent/my-pi-agent--memory%E7%B3%BB%E7%BB%9F/) | 冻结快照保护 Prefix Cache、原子字串修改、分段记忆维护 |
| 12 | **任务规划** | [Todolist 与 Background](https://zxj-2023.github.io/2026/08/31/%E5%AD%A6%E4%B9%A0/agent%E5%AE%9E%E6%88%98/my-pi-agent/my-pi-agent--todolist%E4%B8%8Ebackground/) | DAG 依赖任务图、随路看板回显、BackgroundRunner 进程树强杀 |
| 13 | **人机协作** | [动态干预机制](https://zxj-2023.github.io/2026/08/14/%E5%AD%A6%E4%B9%A0/agent%E5%AE%9E%E6%88%98/my-pi-agent/my-pi-agent--%E5%8A%A8%E6%80%81%E5%B9%B2%E9%A2%84%E6%9C%BA%E5%88%B6/) | Steer 即时转向、Follow-up 宏观任务排队、双层循环拓扑 |
| 14 | **核心并发** | [异步支持](https://zxj-2023.github.io/2026/08/15/%E5%AD%A6%E4%B9%A0/agent%E5%AE%9E%E6%88%98/my-pi-agent/my-pi-agent--%E5%BC%82%E6%AD%A5%E6%94%AF%E6%8C%81/) | 原生协程调度、解除 Python GIL 约束、跨线程任务与取消机制 |

---

## 已实现功能

### 1. 模型边界层 `my-agent-llm`（[学习笔记](https://zxj-2023.github.io/2026/08/05/%E5%AD%A6%E4%B9%A0/agent%E5%AE%9E%E6%88%98/my-pi-agent/my-pi-agent--%E6%A8%A1%E5%9E%8B%E5%B1%82/)）

- **统一 `LLM` 门面**：`chat` / `stream` / `achat` / `achat_stream` 四组接口，屏蔽多供应商差异
- **四大 Provider**：`openai`（基准翻译）/ `deepseek`（继承 + reasoning 提取 + 动态模型发现）/ `anthropic`（block 翻译 + web_search 过滤）/ `antigravity`（Google internal SSE 原生直连 + OAuth 自省）
- **流式增量聚合**：`StreamChunk` 流式 tool_calls 增量拼装 + usage 捕获（末块携带完整统计）
- **核心模型**：不可变 `Config`（Pydantic frozen）、`Message`、`Response`

### 2. 框架核心层 `my-agent-core`

- **[纯函数 ReAct 微内核与七阶段工具流水线（loop & 7-stage pipeline）](docs/core/03-agent-loop.md)**（[学习笔记](https://zxj-2023.github.io/2026/08/30/%E5%AD%A6%E4%B9%A0/agent%E5%AE%9E%E6%88%98/my-pi-agent/my-pi-agent--loop%E5%BE%AE%E5%86%85%E6%A0%B8/)）：
  - `run_agent_loop` 纯函数无状态异步微内核（约 110 行状态机，与类状态彻底解耦）
  - **工业级七阶段工具执行流水线**：
    1. 阶段 1 截断防御（`stop_reason="length"` 安全挂起未完成工具，注入自纠正指引）；
    2. 阶段 2 畸形调用防崩（`_coerce_tool_call` 统一参数防穿帮，产生合成错误结果）；
    3. 阶段 3 预检（`ToolExecutionStart` 严谨成对发射）；
    4. 阶段 4 门禁拦截（`before_tool_call` 提前裁决阻断或改写）；
    5. 阶段 5 实时进度流（`ToolExecutionUpdate` 跨线程安全队列 + 锁存器防迟到更新）；
    6. 阶段 6 结果后处理（`after_tool_call` 改写与 `ToolExecutionEnd` 广播）；
    7. 阶段 7 批次提前退出（`ToolResult.terminate` + Hook 三态熔断 + `any()` 退出保护 `final_text`）。
  - **对话转录本拓扑自愈引擎（`tool_history.py`）**：三阶段状态机消除断头调用，彻底消灭 API 400 校验死锁
  - **只读轻量事件订阅管道（`agent.subscribe`）**：支持同步/异步监听器，`_notify` 异常隔离广播（Never-Throw 保证），返回 `unsubscribe()` 闭包注销句柄
- **[工具系统（tools & registry）](https://zxj-2023.github.io/2026/07/31/%E5%AD%A6%E4%B9%A0/agent%E5%AE%9E%E6%88%98/my-pi-agent/my-pi-agent--%E5%B7%A5%E5%85%B7%E7%B3%BB%E7%BB%9F/)**：
  - `@tool` 装饰器：基于 Pydantic 动态提取函数签名生成 OpenAI/Anthropic 兼容的 JSON Schema
  - `Tool` 实体：支持 `raw_schema`（外部/远程 Schema 透传）与 `is_parallel_safe`（声明式并发标记）
  - `ToolRegistry`：支持单查、批量获取 Schema、`execute_batch` 一票否决因果时序保护（全员只读并发放行，含写严格串行保序）
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
  - 6 Section 结构化约束模板（Goal / Constraints / Progress / Decisions / NextSteps / CriticalContext）与 `<read-files>` / `<modified-files>` 文件足迹自动累积
  - Usage 锚定估算（`chars / 4` 兜底 + `Response.usage` 实测校准）
  - `retainedTail` 缓存（摘要 + 尾部快照持久化为 `compaction` entry，重启免重算）
  - `compaction_floor` 护栏：压缩后指针只能回退到压缩点之后，缓存永不失效
  - 摘要提示词防注入隔离（`<analysis>` / `<summary>` 标签剥离）
- **[Skills 声明式管理（skills）](https://zxj-2023.github.io/2026/08/14/%E5%AD%A6%E4%B9%A0/agent%E5%AE%9E%E6%88%98/my-pi-agent/my-pi-agent--skill%E4%B8%8Eplugin/)**：
  - 三态目录发现（默认探测 `<cwd>/.agents/skills/` / 显式禁用 / 自定义目录）
  - `SKILL.md` YAML 元数据与 Markdown 正文解析
  - 启动阶段仅将轻量 Skills 清单注入 System Prompt，省 Token 且无工具调用开销
  - `invoke_skill` 宿主显式触发机制
- **[Subagents 与 SubagentTask 任务委派（subagents & subagent_tasks）](https://zxj-2023.github.io/2026/08/15/%E5%AD%A6%E4%B9%A0/agent%E5%AE%9E%E6%88%98/my-pi-agent/my-pi-agent--subagent%E4%B8%8Etask%E5%A7%94%E6%B4%BE/)**：
  - `.agents/agents/*.md` 声明式子代理配置发现
  - `SubagentTaskManager` 任务生命周期状态机管理（`RUNNING` ➔ `COMPLETED` / `ERROR`）
  - **隔离子会话**：独立落盘于 `<session_dir>/subagents/agent-task_*.jsonl`，父会话不被子代理中间过程污染
  - **防递归与隔离机制**：子代理继承工具时强制过滤 `task`、`memory` 与 `task_*` 工具，并显式配置 `subagent_dirs=[]`、`plugin_dirs=[]`、`memory_dir=False` 与 `task_store=False`
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
- **[动态干预机制与两层循环（message_queue & steering）](docs/core/11-dynamic-steering.md)**（[学习笔记](https://zxj-2023.github.io/2026/08/14/%E5%AD%A6%E4%B9%A0/agent%E5%AE%9E%E6%88%98/my-pi-agent/my-pi-agent--%E5%8A%A8%E6%80%81%E5%B9%B2%E9%A2%84%E6%9C%BA%E5%88%B6/)）：
  - `MessageQueue` 动态干预队列：支持 `STEERING`（内层安全点转向）与 `FOLLOWUP`（外层排队追问）双类型消息
  - **经典两层循环架构（Two-Level Loop）**：外层处理 Follow-up 宏观任务流转，内层处理 ReAct 微观步骤与 Steer 转向
  - **三大安全点拦截**：Turn 起点原子落盘、工具批执行后即时插队、无工具输出期拦截早退
  - `TaskManager.steer_task(task_id, msg)`：支持对后台运行中的子代理进行定向动态纠偏与追问
- **[统一任务系统与后台异步（task_store & background）](docs/core/12-task-system-and-background.md)**（[学习笔记](https://zxj-2023.github.io/2026/08/31/%E5%AD%A6%E4%B9%A0/agent%E5%AE%9E%E6%88%98/my-pi-agent/my-pi-agent--todolist%E4%B8%8Ebackground/)）：
  - **DAG 依赖状态机（`TaskItem` + `TaskStore`）**：支持单一标准入口 `todo` 工具（对标 Pi 与 Hermes-Agent，涵盖 create/update/list/get/clear/write 6 大动作）、深度传递性成环检测、单 `in_progress` 聚焦约束、自动解锁下游任务与崩溃安全原子持久化
  - **随路看板回显投影（In-Band Echo via `ToolResult`）**：写操作工具执行后直接在返回值中回显最新紧凑 `<TASK_BOARD>`，100% 保护大模型 Prompt Prefix Cache，零额外查询往返，Session 磁盘历史绝对零污染
  - **任务早退守卫（`TaskGuardHook`）**：对标 Pi 扩展事件哲学，解耦监听 `TurnEnd` 与 `AgentStart` 生命周期，在模型未结清在跑工单时自动调用 `steer()` 拦截并纠偏
  - **`BackgroundRunner` 后台异步执行引擎**：支持慢命令（`bash run_in_background=True`）非阻塞运行，结果自动送入 `MessageQueue` Follow-up 队列安全点收割；跨平台整树强杀防御（Windows `taskkill /F /T` + Unix `os.killpg`，联动 `agent.abort()` 与 `atexit`，彻底杜绝孤儿进程）

### 3. 产品层 `my-coding-agent`

- **7 大工作区编码工具与细粒度并发锁**：`read`、`write`、`edit`、`bash`、`grep`、`find`、`ls`，采用 Pi 宽松 CWD 路径解析（`resolve_path`）、`FileMutationQueue` 单文件细粒度并发写锁与 Prompt-Quality 精细化纠错提示（带行数、未找到建议与超时日志捕获）
- **MCP 客户端扩展（`mcp.py`）**：
  - 采用 Extension 插件形式实现，通过 `.mcp.json` 读取配置
  - `AsyncExitStack` 管理物理传输层（`stdio_client` 子进程）与协议层（`ClientSession`）的异步生命周期
  - JSON-RPC 2.0 协议交互与 Schema 动态透传（`raw_schema`）
  - 闭包工厂消除循环中的延迟绑定陷阱
  - 声明式 `is_parallel_safe=True` 赋予只读工具并发加速能力
  - `/mcp` 本地状态查看命令
- **`CodingAgent`**：开箱即用的代码助手 Agent 门面（预装编码工具集 + 自动加载 MCP 扩展）

### 4. 架构设计与外部对标分析

- **[docs/ 技术设计文档库](docs/README.md)**：包含 30 余篇模块级技术架构规范（模型层、核心层、产品层、Tau 深度对标分析、重构路线与缺陷修复规范）。
- **[docs/references/tau-analysis.md](docs/references/tau-analysis.md)**：深度解构 Python 版 Pi Harness 框架 Tau（`tau-ai`），横向对比三层架构，提炼 Textual TUI、OAuth 认证链、JSONL RPC 模式、models.dev 动态模型表、会话历史自愈机制与演进路线。

---

## 快速开始

### 1. 安装与环境准备

本项目使用 [uv](https://docs.astral.sh/uv/) 进行 Python 依赖管理，使用 `npm` 管理前端 TUI 依赖：

```bash
# 1. 根目录安装 Python 依赖与同步全局唯一的虚拟环境
uv sync

# 2. 根目录一键运行全量 Python 单元测试 (665 passed)
uv run python -m pytest

# 3. 运行前端 Pi-TUI 测试套件 (57 passed)
npm test

# 4. 根目录一键启动全新高质感 Pi-TUI 终端交互助手
npm start
```

### 2. 运行离线测试套件

本项目所有测试均使用模拟客户端，**100% 离线运行，无需网络或真实 API Key**：

```bash
# 1. 运行全部 Python 核心测试 (665 tests, 100% 绿灯全通)
uv run python -m pytest

# 2. 运行全部前端 TUI 测试 (57 tests, 100% 绿灯全通)
npm test
```

---

## 仓库目录结构

```text
my-pi-agent/
├── pyproject.toml                  # ⭐ 全局统一的 Python 构建与依赖配置 (uv)
├── uv.lock                         # 全局唯一的 Python 依赖锁定文件
├── .venv/                          # 全局唯一的 Python 虚拟环境
│
├── src/                            # ⭐ 统一收拢的 Python 业务源码 (对标 Tau)
│   ├── my_agent_llm/               # 1. 模型直连层 (Antigravity/DeepSeek/OpenAI/Stream)
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
├── tests/                          # ⭐ 全局统一测试目录 (uv run pytest 3秒并发全通)
│   ├── llm/                        # LLM 层单元测试 (76 tests)
│   ├── core/                       # 框架内核单元测试 (337 tests)
│   └── coding/                     # 业务与工具测试 (252 tests)
│
├── tui/                            # ⭐ 独立的终端交互表现层 (基于 @earendil-works/pi-tui)
│   ├── package.json                # 依赖 @earendil-works/pi-tui, chalk, marked
│   ├── tsconfig.json
│   ├── bin/
│   │   └── my-agent.js             # CLI 执行文件 (支持全局命令 my-pi-agent / my-agent)
│   ├── src/
│   │   ├── app.ts                  # TuiMainScreen 状态机与组件树组装
│   │   ├── client.ts               # PythonKernelClient (管理 uv run python 子进程)
│   │   ├── components/             # Pi 原厂 UI 组件 (CustomEditor, status-indicator, footer...)
│   │   └── theme/                  # Pi 原厂 24-bit TrueColor dark.json 调色盘
│   └── test/                       # 前端 58 个自动化测试与端到端测试套件
│
├── docs/                           # 架构与技术设计文档中心
├── package.json                    # 根目录 npm 工作区配置与一键启动脚本
├── REFERENCES.md                   # 全模块架构设计参考溯源与工程复盘
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
| **会话持久化** | `my_agent_core/session/` | [my-pi-agent--session管理](https://zxj-2023.github.io/2026/08/10/%E5%AD%A6%E4%B9%A0/agent%E5%AE%9E%E6%88%98/my-pi-agent/my-pi-agent--session%E7%AE%A1%E7%90%86/) |
| **上下文四层压缩** | `my_agent_core/context.py` | [my-pi-agent--context管理](https://zxj-2023.github.io/2026/08/11/%E5%AD%A6%E4%B9%A0/agent%E5%AE%9E%E6%88%98/my-pi-agent/my-pi-agent--context%E7%AE%A1%E7%90%86/) |
| **Skills 机制** | `my_agent_core/skills.py` | [my-pi-agent--skill与plugin](https://zxj-2023.github.io/2026/08/14/%E5%AD%A6%E4%B9%A0/agent%E5%AE%9E%E6%88%98/my-pi-agent/my-pi-agent--skill%E4%B8%8Eplugin/) |
| **Subagents 委派** | `my_agent_core/subagent_tasks.py` | [my-pi-agent--subagent与task委派](https://zxj-2023.github.io/2026/08/15/%E5%AD%A6%E4%B9%A0/agent%E5%AE%9E%E6%88%98/my-pi-agent/my-pi-agent--subagent%E4%B8%8Etask%E5%A7%94%E6%B4%BE/) |
| **Extension 与 MCP** | `my_agent_core/extensions/`, `mcp.py` | [my-pi-agent--extension机制与mcp](https://zxj-2023.github.io/2026/08/15/%E5%AD%A6%E4%B9%A0/agent%E5%AE%9E%E6%88%98/my-pi-agent/my-pi-agent--extension%E6%9C%BA%E5%88%B6%E4%B8%8Emcp/) |
| **Memory 记忆系统** | `my_agent_core/memory.py` | [my-pi-agent--memory系统](https://zxj-2023.github.io/2026/08/27/%E5%AD%A6%E4%B9%A0/agent%E5%AE%9E%E6%88%98/my-pi-agent/my-pi-agent--memory%E7%B3%BB%E7%BB%9F/) |
| **Plugin 插件系统** | `my_agent_core/plugins.py` | [my-pi-agent--skill与plugin](https://zxj-2023.github.io/2026/08/14/%E5%AD%A6%E4%B9%A0/agent%E5%AE%9E%E6%88%98/my-pi-agent/my-pi-agent--skill%E4%B8%8Eplugin/) |
| **动态干预与两层循环** | `my_agent_core/message_queue.py` | [docs/core/11-dynamic-steering.md](docs/core/11-dynamic-steering.md) |
| **统一任务与后台异步** | `my_agent_core/task_store.py`, `background.py` | [docs/core/12-task-system-and-background.md](docs/core/12-task-system-and-background.md) |

---

## 未来演进路线 (Roadmap)

项目按阶段对标业界标杆机制持续迭代演进：

- [x] **Pi 风格的 Steer 与 Follow-up 动态干预机制**：
  - **`steer`（动态转向与即时纠偏）**：在 ReAct 循环执行过程中（工具执行间隙、无工具文本输出期等安全点），支持上层宿主或子代理调度器注入转向指令，使 Agent 实时调整执行方向，而无需中断会话或丢失已产生的上下文；
  - **`follow_up`（轮次边界任务追加）**：在当前 Turn 执行结束的自然边界自动拉取并衔接后续追问/队列任务，保持单会话连贯性；
  - **经典两层循环与交付模式**：支持 `one-at-a-time`（单步纠偏）与 `all`（批注入）消费模式，并在 `TaskManager` 中提供子代理定向干预（`steer_task` / `follow_up_task`）。
- [x] **统一 Task / Todo 系统与后台异步执行（Phase 8）**：
  - 实现 `TaskItem` + `TaskStore` DAG 依赖状态机、环检测与崩溃安全原子落盘；
  - 提供 4 增量 CRUD 工具族（`task_create`, `task_update`, `task_get`, `task_list`）与 `todo_write` 便捷工具；
  - `BeforeModelCall` 自动 `<TASK_BOARD>` 上下文看板投影（Session 零污染）；
  - `BackgroundRunner` 异步调度与进程树递归强杀孤儿进程防御。
- [x] **基于 Pi 原厂 `@earendil-works/pi-tui` 的双核表现层（`tui/` 与 `src/my_coding_agent`）**：
  - 基于 `TuiMainScreen` 差量重绘器与 CSI 2026 同步屏障的高质感终端交互层；
  - 流式 Markdown 增量渲染、动态思考折叠块、圆角边框工具卡片、`@` 路径联想与 `/` 斜杠命令气泡；
  - 无状态 stdio JSON-RPC 2.0 双向流通信与跨进程生命周期安全绑定；
  - `Accept-on-Diff` 权限审查门禁与词级差异高亮；
  - `<project_context>` 自动发现与 `AGENTS.md` 规范注入。
- [x] **Pi 官方运行时与交互组件 1:1 深度对齐**：
  - **完整 7 大编码工具**：补齐第 7 个工具 `ls`（500 条目 / 50KB 截断，字母忽略大小写排序，隐藏文件支持），对齐 `grep`（`glob`, `context`, `ignore_case`, `literal`）、`find`（1000 限制）、`edit`（JSON 字符串 / 单 dict 容错）与 `bash`（100ms 流式更新）；
  - **Antigravity 原生直连与动态模型发现**：直连 Google internal Code Assist 原生 SSE，递归展开 JSON Schema `$defs` 解决 Protobuf 400 校验错误；通过 Google internal API 动态发现模型并实现别名与思考等级收敛（4小时磁盘缓存）；
  - **DeepSeek 动态模型列表获取**：通过官方 API 获取最新模型列表并提供 4 小时磁盘缓存；
  - **会话持久化与 DAG 分支探索**：对齐 Pi Session Header (`type: "session"`) 与 `CustomMessage` 规范；提供 `/tree` 会话分支 DAG 树状视图、`/fork` 历史节点分叉、`/clone` 全量状态探索副本，以及 `/resume` 下 `Ctrl+D` 历史会话删除与活跃会话防御保护；
  - **精确 Token 与成本核算**：提取 native provider cache metadata（OpenAI/Anthropic/Antigravity），精确计算缓存命中率（`CH%`）与模型家族阶梯价格，真实 Context Window 动态传导至双行底栏；
  - **输入框嵌入式转圈动效 (`CustomEditor`)**：100% 对齐 Pi 原厂 `CustomEditor`，在输入框顶部边框实时嵌入高频旋转指示器（`── ⠸ Working ──`）与上下文压缩动效（`── ⠸ Compacting context... ──`）；
  - **思考预算与快捷键**：支持 `Shift+Tab` / `Ctrl+T` 快捷键轮转思考等级，并按模型能力自动夹逼适配；
  - **上下文压缩卡片**：压缩摘要以可折叠卡片（`[compaction] Compacted from X tokens (Ctrl+O to expand)`）呈现。
- [ ] **底层可靠性与网络弹性**：
  - 流式中断与 429 / 5xx 指数退避重试；
  - 大模型 `stop_reason` 细粒度归一化处理。
