# my-pi-agent 项目拓扑重构设计规范 (对标 Tau 单一工程与解耦 TUI)

> **文档版本**: 1.0.0  
> **创建日期**: 2026-09-13  
> **设计目标**: 彻底消除 Python 虚拟环境与多包割裂痛点，**对标 HuggingFace 官方 Tau 架构与 Pi 前端哲学**，将项目重构为“根目录统一 Python 业务内核 + 独立顶层 `tui/` 表现层”的极简现代化结构。

---

## 1. 背景与重构动因 (Context & Motivation)

### 1.1 现状与痛点分析 (The Problem)

在先前的迭代中，项目借鉴了 TypeScript 生态的 npm monorepo 模式，在 `packages/` 目录下建立了多个子包：

```text
my-pi-agent/
└── packages/
    ├── my-agent-llm/       (独立的 pyproject.toml / 独立的 .venv / 独立的 uv.lock)
    ├── my-agent-core/      (独立的 pyproject.toml / 独立的 .venv / 独立的 uv.lock)
    ├── my-coding-agent/    (独立的 pyproject.toml / 独立的 .venv / 独立的 uv.lock)
    └── my-agent-tui/       (Node.js / TypeScript 前端工程)
```

这种结构在日常开发中暴露了 **3 大严重痛点**：

1. **虚拟环境与依赖分裂**：
   - 每个 Python 子包各自拥有一套 `.venv`，每次切换包开发都需重复 `uv sync`，重复安装 `pydantic`、`httpx` 等大型依赖，造成磁盘浪费；
   - 子包间通过本地相对路径 editable 引用（`my-agent-llm = { path = "../my-agent-llm" }`），环境极其脆弱，频繁出现模块解析警告。
2. **测试体验严重割裂**：
   - 缺乏全局测试入口。为了验证改动是否破坏既有功能，开发者必须在 3 个不同目录下执行 3 次 `uv run pytest`，无法用单行命令一网打尽。
3. **运行时路径依赖黑魔法 (`PYTHONPATH` 拼接)**：
   - 因为各个子包物理隔离，当外部前端（`tui/`）通过子进程拉起 Python 内核时，不得不手动用代码计算 `repoRoot` 并在环境变量中硬拼凑：
     `PYTHONPATH = "packages/my-coding-agent/src:packages/my-agent-core/src:..."`
     这属于典型的偶合技术债务。

---

### 1.2 标杆对比：Tau (HuggingFace) 是如何优雅设计的？

查阅 HuggingFace 官方 `tau` 仓库（`D:/code/python/agent-program/tau/`），其结构具有极高的工业美感：

- 根目录只有一个统一的 `pyproject.toml` 和全局唯一的 `.venv`；
- 统一源码目录 `src/` 下划分 3 个顶级命名空间包：
  - `src/tau_ai/`：模型直连与流式抽象；
  - `src/tau_agent/`：框架微内核与会话持久化；
  - `src/tau_coding/`：业务编码工具与 CLI；
- 根目录下直接敲 **`uv run pytest`**，可以在 3 秒内并发运行全库所有测试用例；
- 借由 `hatchling` 构建工具，一个工程可以同时对外打包分发这 3 个模块。

---

## 2. 重构目标与核心原则 (Goals & Principles)

1. **Python 侧单核统合 (Unified Python Core)**：
   - 根目录下建立唯一的 `pyproject.toml`、唯一的 `.venv` 与唯一的 `uv.lock`；
   - 根目录下提供统一的 `tests/` 目录，单行 `uv run pytest` 即可跑完全部 575+ 个 Python 测试；
   - 源码统合在根目录 `src/` 下，完全保留 `my_agent_llm`、`my_agent_core`、`my_coding_agent` 三大模块命名空间，**对外的所有导入语句（`from my_agent_core import Agent` 等）100% 无需修改**。
2. **前端交互层纯粹独立 (`tui/`)**：
   - 将 Pi-TUI 交互表现层提拔为仓库顶级的独立目录 **`tui/`**；
   - `tui/` 拥有自己纯粹的 `package.json`、`tsconfig.json` 和启动脚本 `bin/my-agent.js`；
   - 彻底删除已经清空的旧版 `packages/` 目录，消除 Python 与 Node.js 混合存放的语义混淆。
3. **零破坏性迁移 (Zero-Regression Guarantee)**：
   - 现有 575 个 Python 离线测试与 8 个 TypeScript 自动化/端到端测试，在重构后必须继续保持 **100% 绿灯通过**；
   - 彻底消除 `client.ts` 中的 `PYTHONPATH` 拼接黑魔法。

---

## 3. 目标目录拓扑对比 (Before vs After)

### 重构前 (Before)

```text
my-pi-agent/
└── packages/
    ├── my-agent-llm/             # 独立的 pyproject.toml, .venv
    │   ├── src/my_agent_llm/
    │   └── tests/
    ├── my-agent-core/            # 独立的 pyproject.toml, .venv
    │   ├── src/my_agent_core/
    │   └── tests/
    ├── my-coding-agent/          # 独立的 pyproject.toml, .venv
    │   ├── src/my_coding_agent/
    │   └── tests/
    └── my-agent-tui/             # Node.js/TS 依赖混在 packages 目录下
        ├── src/
        └── package.json
```

### 重构后 (After)

```text
my-pi-agent/
├── pyproject.toml                # ⭐ 全局统一的 Python 构建与依赖配置
├── uv.lock                       # 全局唯一的 Python 依赖锁定文件
├── .venv/                        # 全局唯一的 Python 虚拟环境
│
├── src/                          # ⭐ 统合的 Python 业务源码
│   ├── my_agent_llm/             # 1. 模型直连抽象层 (Antigravity/DeepSeek/OpenAI)
│   ├── my_agent_core/            # 2. 框架微内核层 (ReAct循环/树状会话/Skills/Subagents)
│   └── my_coding_agent/          # 3. 业务工具层 (6大编码工具/文件锁/MCP/RPC服务端)
│
├── tests/                        # ⭐ 全局统一测试集 (uv run pytest 跑完全部)
│   ├── llm/                      # LLM 层单元测试 (原 packages/my-agent-llm/tests)
│   ├── core/                     # 框架内核单元测试 (原 packages/my-agent-core/tests)
│   └── coding/                   # 业务与工具单元测试 (原 packages/my-coding-agent/tests)
│
├── tui/                          # ⭐ 独立的终端交互表现层 (Node.js/TS, 基于 @earendil-works/pi-tui)
│   ├── package.json              # 依赖 @earendil-works/pi-tui, chalk, marked
│   ├── tsconfig.json
│   ├── bin/
│   │   └── my-agent.js           # CLI 启动入口
│   ├── src/                      # app.ts, client.ts, components/, theme/
│   └── test/                     # 前端 8 个自动化测试用例
│
├── docs/                         # 统一文档中心
│   └── coding/                   # 系统设计与架构规范
└── README.md
```

---

## 4. 根目录 `pyproject.toml` 统一规范

在项目根目录下生成标准配置：

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "my-pi-agent"
version = "0.1.0"
description = "Minimalist Pi-style coding-agent framework and CLI with Pi-TUI"
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
    "openai>=2.50.0",
    "anthropic>=0.40.0",
    "pydantic>=2.0",
    "httpx>=0.27.0",
    "python-dotenv>=1.0,<2.0",
    "pyyaml>=6.0",
    "mcp>=2.0.0,<2.1",
]

[dependency-groups]
dev = [
    "pytest>=8.0,<10.0",
    "anyio>=4.0",
    "ruff>=0.16.7",
]

# 对标 Tau，利用 hatchling targets 同时发布/导出 3 个内部核心包
[tool.hatch.build.targets.wheel]
packages = [
    "src/my_agent_llm",
    "src/my_agent_core",
    "src/my_coding_agent",
]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
addopts = "-ra -q"

[tool.ruff]
target-version = "py311"
line-length = 120

[tool.ruff.lint]
select = ["E", "F"]
ignore = ["E501"]
```

---

## 5. 前后端通信与子进程唤起极简化 (`tui/src/client.ts`)

在重构前，由于 Python 模块分散在各个子包下，`client.ts` 必须动态注入 `PYTHONPATH`。  
在重构后，由于整个工程挂载在根目录的唯一 `.venv` 下，`tui/src/client.ts` 的子进程唤起代码彻底去掉了所有黑魔法：

```typescript
// 重构后的优雅唤起：原生依托 repoRoot 下的统一 Python 虚拟环境
const args = ["run", "python", "-m", "my_coding_agent.rpc_server", "-w", workspace];
if (this.options.model) {
  args.push("-m", this.options.model);
}

this.child = spawn("uv", args, {
  cwd: repoRoot, // 直接以根目录为工作目录，原生拥有完整的模块搜索树
  stdio: ["pipe", "pipe", "inherit"],
  windowsHide: true,
});
```

---

## 6. 实施路线图与验证契约 (Implementation Phases & Verification)

### 阶段一：目录平移与组织整理

1. 建立根目录 `src/`，将：
   - `packages/my-agent-llm/src/my_agent_llm` -> `src/my_agent_llm`
   - `packages/my-agent-core/src/my_agent_core` -> `src/my_agent_core`
   - `packages/my-coding-agent/src/my_coding_agent` -> `src/my_coding_agent`
2. 建立根目录 `tests/`，将：
   - `packages/my-agent-llm/tests` -> `tests/llm`
   - `packages/my-agent-core/tests` -> `tests/core`
   - `packages/my-coding-agent/tests` -> `tests/coding`
3. 将 `packages/my-agent-tui/` 平移至顶层 `tui/`。
4. 删除空的 `packages/` 目录。

### 阶段二：根级配置与依赖锁定

1. 写入根目录 `pyproject.toml`；
2. 执行 `uv sync` 构建统一的本地虚拟环境，并生成全局唯一的 `uv.lock`。

### 阶段三：前端 `client.ts` 净化与测试

1. 简化 `tui/src/client.ts` 中的 `repoRoot` 路径与子进程唤起逻辑；
2. 进入 `tui/` 执行 `npm run build` 与 `npm test`，确保 8 个前端测试（包含真实 Python 子进程端到端测试）全通。

### 阶段四：全库回归与验收交付

1. 在根目录执行单行命令：

   ```bash
   uv run pytest
   ```

   验证全部 **575 个 Python 单元测试 100% 绿灯全通**；
2. 在 `tui/` 目录下执行：

   ```bash
   npm test
   ```

   验证全部 **8 个前端测试 100% 绿灯全通**；
3. 更新 `README.md` 与相关规约，完成 Git 提交并推送到 GitHub。
