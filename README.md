# my-pi-agent

学习项目：从零搭建一个精简的 agent 框架，再用这个框架搭一个 coding agent。
参考对象是 pi（pi-mono）及其 Python 移植版 pig-mono（`pig-agent-core` /
`pig-coding-agent` 两层结构），本项目对应规划：

| 包 | 对应参考 | 状态 |
|---|---|---|
| `packages/my-agent-core` —— 框架层（src 布局，ReAct 循环、工具机制、事件、会话持久化、上下文管理） | `pig-agent-core` | 已实现核心（单层 `Agent` + session + context）；剩余 skills、动态工具 |
| `my_coding_agent/` —— coding agent 层（CLI 入口、内置工具、权限门控等） | `pig-coding-agent` | 未开始 |

两层都不奔生产，透明度与可理解性优先；框架层只依赖 `openai` SDK 与标准库，
不依赖任何 agent 框架。

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
