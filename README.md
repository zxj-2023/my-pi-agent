# my-pi-agent

学习项目：从零搭建一个精简的 agent 框架，再用这个框架搭一个 coding agent。
参考对象是 pi（pi-mono）及其 Python 移植版 pig-mono（`pig-agent-core` /
`pig-coding-agent` 两层结构），本项目对应规划：

| 包 | 对应参考 | 状态 |
|---|---|---|
| `packages/my-agent-core` —— 框架层（src 布局，ReAct 循环、工具机制、事件、会话持久化、上下文管理、skills、动态工具） | `pig-agent-core` | 实现中（含 7-stage v1 路线图） |
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

- **框架层设计**（`docs/superpowers/specs/`，2026-08-01 系列五份）：
  框架核心（循环 / 工具 / 事件 / Agent）/ 会话持久化与恢复 / 上下文估算与压缩 /
  skills 机制 / 动态工具与可注入策略
- **实现路线**：见 `packages/my-agent-core/README.md`「TODO：v1 实现路线」（七阶段，每步带验证）
- **学习轨迹**：2026-07-29 / 2026-07-31 设计与计划文档（LangChain / LangGraph
  ReAct 学习阶段的记录，示例代码已清理，文档留档）

## 目录结构

```
my-pi-agent/
├── packages/
│   └── my-agent-core/   # 框架层独立 uv 项目（src 布局：src/my_agent_core/，含自身 README 与 tests）
├── docs/                # 设计文档 + 学习笔记
└── README.md            # 本文件（仓库级说明）
```
