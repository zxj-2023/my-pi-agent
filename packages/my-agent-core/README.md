# my-agent-core

从零实现的最简通用 Agent 核心框架。只依赖通用库（`openai` SDK、`pydantic`、`pyyaml` 等）与标准库，**不引入任何外部 agent 框架**（langchain / langgraph 等），每一行代码都清晰、可审查。

项目定位：**纯净框架层**（独立 uv 项目，Python 包名 `my_agent_core`），提供通用 Agent 原语；上层产品（如软件开发助手 `my-coding-agent`）基于本框架组装与扩展。

> **技术设计规范**：各模块的底层实现原理与架构规范详见仓库根目录 **[`docs/core/`](../../docs/core/)**；
> 详细的项目演进与提交复盘见根目录 **[`PROGRESS.md`](../../PROGRESS.md)** 与 **[`REFERENCES.md`](../../REFERENCES.md)**。

---

## 核心特性与架构亮点

- **100% 纯原生异步 ReAct 循环**：`await agent.run(prompt)`，状态集中于单层 `Agent` 类，天然支持多轮流式推进、Token 级熔断与 `abort()` 取消隔离；
- **强类型声明式工具系统（`tools`）**：
  - `@tool` 装饰器：基于 Pydantic 从函数签名与注解自动生成标准 Function Calling JSON Schema；
  - `Tool` 实体：支持 `raw_schema`（透传外部 Schema）与 `is_parallel_safe`（声明式并发标记）；
  - `ToolRegistry`：支持单查、批量获取 Schema、`execute_batch` 并发/串行智能分流与严格保序回填；
  - **Never-Throw 保证**：工具异常绝不上抛打崩程序，统一包装为 `ToolResult(ok=False, error=...)` 引导大模型自愈。
- **12 大生命周期事件与五大决策拦截点（`events` & `hooks`）**：
  - 12 个生命周期事件 dataclass（覆盖 Agent、Turn、Message、Tool、Context 阶段）；
  - **五大生命周期决策拦截点**：
    1. `UserInput`：用户输入截获，支持 `block` 阻断或 `updated_input` 改写；
    2. `AgentStart`：启动前拦截，支持 `updated_system_prompt` 动态更新首条 system 消息；
    3. `BeforeModelCall`：调 LLM 前拦截，支持 `updated_messages` 临时改写上下文视图（**临时 View 隔离 vs Session 磁盘零污染**）；
    4. `ToolExecutionStart`：工具执行前拦截，支持 `block` 拦截高危操作或 `updated_args` 修补参数；
    5. `ToolExecutionEnd`：工具执行后拦截，支持 `updated_result` 篡改出参。
  - `MessageUpdate`：流式生成中的 Token 级实时熔断（掐断时**丢弃未完成半截文本**，防止模型断句幻觉）；
  - 统一干预数据模型：`HookResult`。
- **树状会话与原子持久化（`session`）**：
  - 树状会话拓扑：`SessionEntry`（带 id/parent_id）+ `SessionTree` + 当前指针 `current_id`；
  - 崩溃安全原子落盘：临时文件 + `fsync` + `os.replace`，断电永不损坏历史；
  - `rewind`（指针回退，历史分支完整保留）+ `fork`（派生新分支会话）；
  - Workspace 目录天然物理隔离（`<workspace>/.my_agent_core/sessions/`）。
- **四层廉价优先上下文压缩管线（`context`）**：
  - `ContextManager` 廉价优先管线：L3 大结果落盘 ➔ L1 裁切中间轮次 ➔ L2 旧结果占位（0 API 损耗）➔ L4 LLM 智能摘要（超阈才花 1 次 API）；
  - Usage 动态锚定：字符估算兜底 + `Response.usage` 官方真实消耗动态校准；
  - `retainedTail` 缓存：摘要 + 尾部快照固化为 `compaction` entry，重启免重算；
  - `compaction_floor` 护栏：压缩后指针只能回退到压缩点之后，防止缓存失效。
- **Skills 声明式管理（`skills`）**：
  - 渐进式披露：启动阶段仅将轻量 Skills 清单注入 System Prompt，省 Token 且无工具调用开销；
  - `SKILL.md` 容错解析与单 Skill 简写支持；
  - `invoke_skill` 宿主显式触发机制。
- **Subagents 与 Task 任务委派（`subagents` & `tasks`）**：
  - 声明式 `.agents/agents/*.md` 发现与专员参数配置；
  - `TaskManager` 任务状态机管理（`RUNNING` ➔ `COMPLETED` / `ERROR`）；
  - **沙箱隔离子会话**：独立落盘于 `<session_dir>/subagents/`，父会话历史保持纯净；
  - **防递归沙箱防护**：子代理强制剔除 `task` 与 `memory` 工具，并设置 `subagent_dirs=[]`、`plugin_dirs=[]` 与 `memory_dir=False`。
- **Extension 扩展与 0 Token 命令路由（`extensions`）**：
  - 静态契约面 `ExtensionAPI` + 调度总管 `ExtensionManager`；
  - 模块动态加载与单点故障隔离保护（单个扩展异常不影响主程序）；
  - `@api.on` 事件订阅、`@api.tool` 业务工具注册（后加载覆盖机制）、`@api.command` 斜杠命令反射调度（0 Token 消耗）。
- **Memory 长期记忆系统（`memory`）**：
  - `MemoryStore` 条目化存储：管理 `MEMORY.md`（上限 2200 字符）与 `USER.md`（上限 1375 字符），使用 `\n§\n` 条目切分；
  - **Frozen Snapshot（冻结快照）机制**：构造时冻结为 `<MEMORY_CONTEXT>` 注入 System Prompt，运行中写入只落盘不动快照，保护大模型 Prefix Cache 稳定；
  - `make_memory_tool` 受控维护工具：唯一子串匹配增删改、歧义冲突防护与超限引导整理。
- **Claude Code 风格 Plugin 插件分发系统（`plugins`）**：
  - 100% 对齐 Claude Code 官方规范（`.claude-plugin/plugin.json`、`skills/`、`agents/`、`.mcp.json`）；
  - `PluginManager` 统一聚合解构，自动分发注入 `SkillManager` 与 `SubagentManager`。

---

## 快速上手

### 1. 安装与运行 Demo

```powershell
uv sync                        # 安装依赖
Copy-Item .env.example .env    # 把真实配置填入 .env
uv run python -m my_agent_core.main # 运行流式打字机 demo
```

### 2. 运行离线测试套件

本包所有单元测试均使用 FakeLLM，**100% 离线确定性运行，无需网络或真实 API Key**：

```powershell
uv run python -m pytest -q
# 输出: 212 passed in ~4s
```

---

## 项目结构

```text
packages/my-agent-core/
├── pyproject.toml            # 包名 my-agent-core，src 布局 + hatchling 构建
├── .env.example              # 环境变量模板
├── src/my_agent_core/        # 核心源码包
│   ├── agent.py              # Agent 实体（状态机 + 异步 ReAct 循环 + 五大拦截点）
│   ├── registry.py           # ToolRegistry（工具注册表，并发分流与保序回填）
│   ├── events.py             # 12 大生命周期事件 + HookResult 统一干预模型
│   ├── tools/                # 工具系统
│   │   ├── __init__.py       # 核心符号统一导出
│   │   ├── core.py           # Tool 实体、ToolResult 与 @tool 装饰器
│   │   └── builtin/          # 内置工具（task.py 子代理委派桥）
│   ├── session.py            # SessionEntry + SessionTree + Session（树 + JSONL 原子落盘）
│   ├── session_store.py      # SessionStore（会话仓库，workspace 物理隔离）
│   ├── context.py            # ContextManager（四层压缩管线）+ ContextSessionBridge
│   ├── memory.py             # MemoryStore + make_memory_tool（长期记忆与快照管理）
│   ├── skills.py             # Skill + SkillManager（技能发现与清单注入）
│   ├── subagents.py          # Subagent + SubagentManager（子代理发现）
│   ├── tasks.py              # Task + TaskStatus + TaskManager（委派生命周期调度）
│   ├── extensions/           # Extension 扩展机制
│   │   ├── __init__.py       # 符号导出
│   │   └── core.py           # ExtensionAPI + ExtensionManager 核心实现
│   ├── plugins.py            # Plugin + PluginManager（Claude Code 插件聚合分发）
│   └── main.py               # 异步流式打字机 demo
└── tests/                    # 100% 离线单元测试 (212 tests)
    ├── test_agent.py         # Agent 循环、状态与 5 大决策点拦截测试
    ├── test_tools.py         # Tool / ToolResult / @tool 测试
    ├── test_registry.py      # ToolRegistry 并发分流与保序回填测试
    ├── test_events.py        # 事件 dataclass 与 HookRegistry 测试
    ├── test_session.py       # 树状分支、原子落盘与 rewind/fork 测试
    ├── test_session_store.py # SessionStore 目录隔离测试
    ├── test_context.py       # 四层压缩管线与 retainedTail 缓存测试
    ├── test_skills.py        # Skills 发现、清单注入与显式调用测试
    ├── test_subagents.py     # Subagent 发现与 frontmatter 测试
    ├── test_tasks.py         # Task 任务委派与独立子会话沙箱测试
    ├── test_extensions.py    # Extension 加载、覆盖与命令路由测试
    ├── test_memory.py        # MemoryStore、快照冻结与受控工具测试
    └── test_plugins.py       # Plugin 发现、Manifest 容错与解构测试
```

---

## 核心代码示例

### 1. 声明自定义工具并组装 Agent

```python
import asyncio
from my_agent_llm import LLM, Config
from my_agent_core.tools import tool
from my_agent_core.session_store import SessionStore
from my_agent_core.agent import Agent

# 1. 声明业务工具
@tool(name="calculator", description="计算算术表达式")
def calculate(expr: str) -> float:
    """Safely calculate expression."""
    return float(eval(expr))  # 生产环境请使用 safe eval

@tool(name="get_weather", description="获取城市天气", is_parallel_safe=True)
def get_weather(city: str) -> str:
    return f"{city}: 晴朗, 25°C"

async def main():
    # 2. 初始化会话与 Agent
    store = SessionStore()
    session = store.create_session()
    llm = LLM(Config(provider="openai", model="gpt-4o"))
    
    agent = Agent(
        llm=llm,
        session=session,
        tools=[calculate, get_weather],
        system_prompt="你是一名智能助手，请按需调用工具回答问题。"
    )
    
    # 3. 异步驱动
    answer = await agent.run("请帮我查一下北京的天气，并算一下 125 * 8 等于多少？")
    print("Agent 回答:", answer)

if __name__ == "__main__":
    asyncio.run(main())
```

### 2. 编写自定义 Extension 插件

```python
from my_agent_core.extensions import ExtensionAPI
from my_agent_core.events import BeforeModelCall, HookResult, Message

def extension(api: ExtensionAPI):
    # 1. 拦截上下文视图（Session 磁盘零污染）
    @api.on(BeforeModelCall)
    def add_safety_reminder(event: BeforeModelCall, api: ExtensionAPI):
        reminder = Message(role="user", content="[SYSTEM REMINDER: 请务必保持回答客观简洁]")
        return HookResult(updated_messages=event.messages + [reminder])
    
    # 2. 注册本地 0 Token 命令
    @api.command("ping")
    def ping_command():
        return "pong (0 API consumed)"
```

---

## 设计不变式（Architectural Invariants）

1. **Never-Throw Guarantee**：工具执行与 Hook 回调绝不上抛异常，错误转化为标准错误信息供 LLM 自我纠错；
2. **Crash-Safe Atomic Write**：所有持久化磁盘写入使用临时文件 + `fsync` + `os.replace`；
3. **Session 零污染（Zero-Pollution Invariant）**：`BeforeModelCall` 对模型视图的临时修改与子代理运行历史绝不污染父会话；
4. **Frozen Snapshot 缓存保护**：长期记忆快照在启动时冻结，运行时写入不修改快照，最大化保持大模型 Prompt Prefix Cache 命中率；
5. **子代理防递归沙箱（Anti-Recursion Sandbox）**：子代理派发时强制清空 `plugin_dirs`、`subagent_dirs` 并禁用 `task` / `memory` 工具。

---

## 演进路线图（Roadmap）

按阶段对标业界标杆机制持续迭代演进：

- [x] **阶段 1-4：核心基础架构**（Pydantic 工具系统、单层 Agent 异步 ReAct 循环、树状会话与原子落盘、四层廉价优先压缩管线）
- [x] **阶段 5：Skills 技能机制**（渐进式清单注入 + `invoke_skill` 显式调用）
- [x] **阶段 9 & 12：Extension 扩展体系**（静态契约面 `ExtensionAPI` + 调度总管 `ExtensionManager` + 五大生命周期决策拦截点）
- [x] **阶段 10：原生异步重构**（纯异步 `await agent.run()` + `is_parallel_safe` 并发分流与严格保序回填）
- [x] **阶段 11：产品与框架分层**（文件工具与 MCP 迁出至 `my-coding-agent`，框架保持纯粹通用）
- [x] **阶段 7：Memory 长期记忆系统**（`MemoryStore` 双 Markdown 存储 + Frozen Snapshot 冻结快照 + `make_memory_tool` 受控维护工具）
- [x] **阶段 13：Claude Code 风格 Plugin 插件系统**（Manifest 弹性解析 + 目录名推断兜底 + 技能/子代理/MCP 自动解构分发）
- [ ] **Pi 风格的 Steer 与 Follow-up 动态干预机制（进行中）**：
  - `steer` 动态转向：在 ReAct 循环或子代理运行中途（如工具执行间隙、下一轮大模型推理前等安全点）注入转向指令，使 Agent 实时调整执行方向，无需中断会话；
  - `follow_up` 轮次边界追加：在当前 Turn 执行结束的自然边界自动拉取并衔接后续追问/队列任务；
  - 交付模式分流（`steer` / `follow_up` / `auto`）与安全点确认。
- [ ] **Task / Todo 系统（阶段 8）**：`todo_write` 工具与 `TaskStore`，支持任务多层级拆解与实时状态看板投影。
- [ ] **可靠性增强**：网络异常重试、429 指数退避、`stop_reason` 细粒度归一化。
