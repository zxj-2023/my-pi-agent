# 产品层完整架构与工程工具链设计规范 (`my_coding_agent`)

- **定位**：面向生产级编码助手的完整产品层 (`packages/my-coding-agent`)
- **设计标杆**：`pi` (`packages/coding-agent`)、`tau` (`tau_coding`)、`pig-mono` (`pig-coding-agent`)
- **核心模块**：`agent.py`（双接口门面）、`tools/`（6 大核心工具体系）、`mutation_queue.py`（单文件并发锁）、`prompt.py`（专业提示词组装与上下文发现）、`mcp.py`（MCP 客户端）

---

## 一、架构全景与分层职责

坚持 **“框架通用微内核，产品垂直工程化”** 原则：

- 底层 `my-agent-core` 负责 ReAct 微内核调度、Session 持久化树、上下文滑动与廉价压缩、任务管理及后台守护进程；
- 边界层 `my-agent-llm` 负责模型多厂商适配与增量流式累加；
- 产品层 `my-coding-agent` 负责为编写代码定制的 6 大工具箱、文件并发保护、工作区上下文扫描与 TUI/CLI 双接口驱动。

```text
+-------------------------------------------------------------------------------+
|                                CodingAgent 门面                               |
|        - run(user_input: str) -> str (批处理聚合入口)                         |
|        - run_stream(user_input: str) -> AsyncIterator[AgentEvent] (流式入口)  |
+-------------------------------------------------------------------------------+
                                         │
       ┌─────────────────────────────────┼─────────────────────────────────┐
       ▼                                 ▼                                 ▼
【专业 Coding 提示词】            【6 大核心工程工具】               【细粒度并发锁】
- 资深工程师质量准则              - read (行切片/截断/续读)          - FileMutationQueue
- 先读后改/唯一匹配规范           - write (全量覆盖/建父目录)        - 基于 resolve() 路径
- <project_context> 自动注入      - edit (Multi-Edit/CRLF/BOM/Diff)  - 跨文件完全并发
  (AGENTS.md / README.md)         - bash (异步/杀进程树/外溢.log)    - 同文件串行隔离
- 动态技能清单 (Skills)           - grep (原生跨平台正则检索)
                                  - find (原生跨平台 Glob 匹配)
                                         │
                                         ▼
                             resolve_path (以 workspace 为基准)
                                         │
                                         ▼
                            my-agent-core (Agent 微内核)
```

---

## 二、路径设计哲学：以工作区为基准的宽松解析（方案 C：Pi 原生哲学）

在标杆项目 `pi` 源码中（`packages/coding-agent/src/core/tools/`），所有工具均直接使用 `path.resolve(cwd, filePath)` 解析路径，坚决不在应用层做人工越界拦截（杜绝伪沙箱）：

1. **工作区（`cwd`）是工作基准点，而非虚拟牢笼**：
   - 真实工程师在终端工作时，`cwd` 是为了便利展开相对路径；
   - 工程师拥有读取上级配置、跨目录引用或修改同级项目的完全自由，Agent 作为拟人化的软件工程师，不应被人为沙箱报错（如 `ValueError("Path escapes workspace")`）打断正常开发。
2. **现代开发拓扑的刚性需求**：
   - **Monorepo 多包联动**：在 `packages/my-coding-agent` 开发测试时，频繁需要读取同级 `packages/my-agent-core` 或根目录 `pyproject.toml`；
   - **环境与全局配置感知**：需要读取 `~/.gitconfig` 或查看环境上下文；
   - **临时文件与日志自省**：`bash` 执行命令外溢的大日志存放在系统全局临时目录（如 `/tmp/` 或 `%TEMP%`），必须允许 Agent 阅读。
3. **安全防线转移**：
   - 安全性依赖于透明的 Tool Call 审计、受控环境与 Git 版本控制审查，而非应用层字符串沙箱。
   - `FileMutationQueue` 依然采用规范化绝对物理路径（`path.resolve()`）作为全局锁键，跨目录或相对路径均映射到同一把文件锁，100% 杜绝并发写冲突。

---

## 三、六大核心工具体系规范

| 工具 | 输入参数 | 核心行为与安全规范 |
| :--- | :--- | :--- |
| **`read`** | `path`, `offset=1`, `limit=None` | 支持 1-indexed 行切片；默认 2000 行/50KB 智能头部截断；末尾提示 `[Showing lines X-Y of Z. Use offset=Y+1 to continue.]`；自动探测二进制文件拦截。 |
| **`write`** | `path`, `content` | 递归自建不存在的父目录；`FileMutationQueue` 路径锁保护；返回写入字节数与行数统计。 |
| **`edit`** | `path`, `edits: list[EditBlock]`, `old_text=None`, `new_text=None` | 支持多段原子替换；自动保全 **UTF-8 BOM** 与原始换行符（**CRLF vs LF**）；逆向偏移替换防漂移；非重叠校验；生成并返回 **Unified Diff**。 |
| **`bash`** | `command`, `timeout=120`, `run_in_background=False` | `asyncio.create_subprocess_shell` 异步执行；命令黑名单防护；Windows `taskkill /F /T` / POSIX `killpg` 杀进程树；尾部截断（2000 行/50KB）并将全量输出外溢至系统临时 `.log` 文件。 |
| **`grep`** | `pattern`, `path="."`, `regex=False`, `case_sensitive=False`, `max_matches=100`, `glob_filter=None` | 跨平台纯 Python 实现；自动解析 `.gitignore` 并忽略缓存目录；输出带文件名与行号的紧凑结果。 |
| **`find`** | `pattern="*"`, `path="."`, `limit=100` | 跨平台 Glob 模式与模糊匹配；过滤 `.git`, `.venv` 等杂质目录；输出相对路径列表。 |

---

## 四、对外 API 架构：Pi 与 Tau 标杆对比与 Dual API 设计

### 1. 标杆项目（Pi vs Tau）在调用模型上的实现方式

- **Pi（TypeScript）采用 Observer 订阅模式**：
  `agent.subscribe(listener)` 注册事件观察者，`await agent.prompt(text)` 返回 `Promise<void>`。TUI 与 Session 持久化均作为观察者被动接收 Push 事件。
- **Tau（Python）采用 AsyncIterator 生成器模式**：
  `session.prompt(text) -> AsyncIterator[CodingSessionEvent]`。每一轮思考 delta、文本与工具状态均通过 `yield` 产出，调用方通过 `async for` 主动 Pull 消费。适合流式但对纯脚本和单元测试不够友好（需要写样板代码累加事件）。

### 2. `my-coding-agent` 的最优收敛：双接口驱动（Dual API）

融合 Tau 的 Pythonic 异步生成器核心与 Pi 的极简批处理体验：

```python
class CodingAgent:
    def __init__(self, *, workspace, llm, session, system_prompt=None, extra_tools=(), **agent_kwargs): ...

    async def run_stream(self, user_input: str) -> AsyncIterator[AgentEvent]:
        """实时流式事件一等公民入口（CLI/TUI 终端交互、打字机动画、工具进度）"""
        async for event in self.agent.prompt_stream(user_input):
            yield event

    async def run(self, user_input: str) -> str:
        """批处理一次性高阶入口（自动化测试、离线脚本、快速调用，内部消费 run_stream 并聚合最终文本）"""
        return await self.agent.run(user_input)
```

---

## 五、测试与质量保证

1. **`edit` 极端边界**：多段替换、BOM 保全、CRLF 跨行修改验证、重叠区间拒绝、Unified Diff 校验。
2. **`bash` 进程与外溢**：超时杀进程树验证（无孤儿进程留存）、大日志外溢至临时文件验证。
3. **`FileMutationQueue` 压力**：同文件并发写排队互斥、不同文件完全并行无阻塞。
4. **端到端 E2E 闭环**：多轮 ReAct 真实场景驱动。
