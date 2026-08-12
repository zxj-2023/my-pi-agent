# my-pi-agent

**当前最好的 Python 语言 agent 框架学习项目**——从零手写一个最小但完整的 agent 框架，
不依赖任何 agent 框架（只依赖 `openai` SDK、`pydantic` 与标准库），每一行代码都可审查。

风格：**简洁、规范**——只做当前需求的最小实现，接口边界干净、职责单一、测试先行。

功能实现参考三者的架构思路，并做出整合优化：

| 参考 | 借鉴的架构思路 |
|---|---|
| **pi**（[earendil-works/pi](https://github.com/earendil-works/pi)） | 生命周期事件模型（Agent/Turn/Message/Tool 四组）、树结构会话 + rewind、摘要式压缩 |
| **pig-mono**（[kangkona/pig-mono](https://github.com/kangkona/pig-mono)） | 两层结构（`pig-agent-core` / `pig-coding-agent`）、单层 `Agent` 类、逐条原子落盘、workspace 隔离 |
| **learn-claude-code**（[shareAI-lab/learn-claude-code](https://github.com/shareAI-lab/learn-claude-code)） | 四层压缩管线（cheap-first）、hook 注册表、会话管理（树 + 缓存 entry） |

整合优化：如「非破坏视图压缩」（树永远完整，压缩只是发送前视图）+「retainedTail 缓存
+ rewind 护栏」（重启免重算、缓存永不失效）+「usage 锚定估算」（零新依赖的精度提升）。

## 已实现

### 模型边界层 `my-agent-llm`

- 统一 `LLM` 门面：`chat` / `stream` / `achat` / `achat_stream`，屏蔽 provider 差异
- 三 provider：`openai`（基准翻译）/ `deepseek`（继承 + reasoning 提取）/ `anthropic`（block 翻译 + web_search）
- 流式 tool_calls 聚合 + usage 捕获（末块带完整数据）
- 数据模型：`Message` / `Response` / `StreamChunk`

### 框架层 `my-agent-core`

- **工具层**：`@tool` 装饰器（pydantic 动态建模，支持全集类型与默认值）、
  `ToolRegistry`（注册 / 查表 / 批量 schema / 执行）、`ToolResult`（永不抛）
- **事件 + hook**：10 个事件 dataclass（Agent/Turn/Message/Tool 四组生命周期）+
  hook 注册表（`register_hook`，同一事件多回调、非 None 短路、可拦截 / 改参数 / 改结果）
- **Agent**：单层类（状态 + 循环 + 工具执行全在一个类），`run()` 内联 ReAct 循环、
  `reset()`、`max_iterations`；`session=` 持久化、`context_budget=` 上下文管理、
  `compact()` 手动压缩
- **会话持久化（session）**：树结构（entry 带 id/parent_id + current 指针）
  - `SessionTree` / `Session` / `SessionStore` 三层职责分离
  - 逐条原子落盘（临时文件 + fsync + os.replace）——崩溃永远完整快照
  - `rewind`（移动指针，旧分支保留）+ `fork`（从 entry 复制路径为新会话）
  - workspace 隔离（`<workspace>/.my_agent_core/sessions`，跨项目天然不可见）
- **上下文管理（context）**：`ContextManager` 四层压缩管线（cheap-first）
  - L3 大结果落盘 → L1 裁中间 → L2 旧结果占位（0 API，每轮例行）→ L4 LLM 摘要（超阈才 1 API）
  - usage 锚定估算（chars/4 兜底 + `Response.usage` 实测校准）
  - retainedTail 缓存（摘要 + 尾部快照持久化为 `type="compaction"` entry，重启免重算）
  - rewind 护栏（`compaction_floor`：压缩后只能回压缩点之后，缓存永不失效）
  - 摘要提示词：防注入 + 先分析再总结（`<analysis>`/`<summary>` 剥离）
  - `ContextCompacted` 事件、`ContextSessionBridge`（Context↔Session 桥）

## 未来计划

见 `packages/my-agent-core/README.md`「TODO：v1 实现路线」与「未来路线图」，要点：

- **skills 机制**：SKILL.md 发现 + 清单拼 system + `read_skill` 工具
- **动态工具**：运行中 `register_tool` / `unregister_tool` + `ToolsChanged` 事件
- **coding agent 层**（`my_coding_agent`）：CLI 入口、内置工具、权限门控、
  Prompt 管理（AGENTS.md 注入）
- **进阶**：async 化 / 流式输出 / 推理内容回传 / 结构化输出 / 交互式 REPL /
  优雅停止钩子 / reactive 应急压缩 / 成本统计 / 手动 compact 工具

## 快速开始

```powershell
cd packages/my-agent-core
uv sync
Copy-Item .env.example .env    # 然后把真实配置填进 .env
uv run python -m my_agent_core.main   # demo（Agent API）
uv run python -m pytest -q     # 离线测试（不需要 API key）
```

环境变量：

| 变量 | 必需 | 说明 |
|---|---|---|
| `OPENAI_API_KEY` | 是 | OpenAI API key |
| `OPENAI_MODEL` | 否 | 模型名，默认 `gpt-4.1-mini` |
| `OPENAI_BASE_URL` | 否 | 自定义 OpenAI 兼容端点 |

## 文档

- **实现路线**：见 `packages/my-agent-core/README.md`「TODO：v1 实现路线」（每步带验证）
- **项目进度**：见仓库根 `PROGRESS.md`（每个实现阶段的目标 / 规格 / 提交 / 改了什么 /
  关键教训 / 验证方式）

## 目录结构

```
my-pi-agent/
├── packages/
│   ├── my-agent-llm/               # 模型边界层独立 uv 项目（含自身 README）
│   │   ├── pyproject.toml          # src 布局 + hatchling 构建
│   │   ├── src/my_agent_llm/       # Python 包
│   │   │   ├── client.py           # LLM 门面（chat/stream/achat/achat_stream）
│   │   │   ├── config.py           # Config（pydantic frozen）
│   │   │   ├── models.py           # Message / Response / StreamChunk
│   │   │   └── providers/          # openai / deepseek / anthropic + 注册表
│   │   └── tests/                  # 离线测试（假 SDK 注入）
│   └── my-agent-core/              # 框架层独立 uv 项目（含自身 README）
│       ├── pyproject.toml          # src 布局 + hatchling 构建
│       ├── src/my_agent_core/      # Python 包
│       │   ├── tools.py            # Tool 类 + tool() 装饰器 + ToolResult
│       │   ├── registry.py         # ToolRegistry（注册表）
│       │   ├── events.py           # 10 个事件 dataclass + HookResult
│       │   ├── agent.py            # Agent 类（单层：循环 + 工具执行 + hook 注册表）
│       │   ├── session.py          # SessionEntry + SessionTree + Session（树 + JSONL 原子落盘）
│       │   ├── session_store.py    # SessionStore（会话仓库，workspace 隔离）
│       │   ├── context.py          # ContextManager（四层压缩管线）+ ContextSessionBridge
│       │   └── main.py             # demo 入口
│       └── tests/                  # 离线测试（7 个文件，详见包内 README）
├── PROGRESS.md                     # 项目进度记录
└── README.md                       # 本文件（仓库级说明）
```