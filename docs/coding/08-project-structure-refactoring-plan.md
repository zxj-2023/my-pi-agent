# my-pi-agent 项目拓扑重构实施计划 (对标 Tau 单一工程与解耦 TUI)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 依据 `docs/coding/07-project-structure-refactoring-design.md`，将项目重构为对标 Tau 的单统一 Python 项目 + 独立顶层 `tui/` 表现层结构，彻底消灭虚拟环境分裂与跨包导包黑魔法，实现单行 `uv run pytest` 跑完全库测试。

**Architecture:**

- **后端内核单工程统合**：在根目录下建立唯一的 `pyproject.toml`、唯一的 `.venv` 与唯一的 `tests/` 目录，将原本在 `packages/` 下分散的 3 个 Python 包平移至根目录 `src/`，利用 `hatchling` 同时导出 `my_agent_llm`、`my_agent_core`、`my_coding_agent`；
- **前端交互层解耦与独立**：将 Pi-TUI 表现层提拔为顶级目录 `tui/`，拥有独立的 `package.json`，并通过根目录顶层 `npm start` 一键拉起；
- **零破坏性承诺**：重构后所有现有 575 个 Python 核心测试与 8 个 TypeScript 前端测试必须保持 **100% 绿灯全通**。

**Tech Stack:** Python 3.12, `uv`, `hatchling`, `pytest`, `Node.js`, `TypeScript`, `@earendil-works/pi-tui`.

**Spec:** `docs/coding/07-project-structure-refactoring-design.md`

## Global Constraints

- 所有的模块导包路径（`from my_agent_core import ...`, `from my_agent_llm import ...`, `from my_coding_agent import ...`）保持 100% 不变。
- 严禁向核心代码注入任何类/函数/模块级过渡垫片。
- 保持干净的 Git 历史与测试纯洁性。

---

## 实施任务总览表 (Overview)

| Task # | 核心目标 | 交付文件/目录 | 预估测试 |
| :--- | :--- | :--- | :--- |
| **Task 1** | Python 源码统一平移至根目录 `src/` 与根目录 `pyproject.toml` 配置 | `pyproject.toml`<br>`src/my_agent_llm/`<br>`src/my_agent_core/`<br>`src/my_coding_agent/` | 模块导入验证 |
| **Task 2** | 全局测试集统一平移至根目录 `tests/` 与一次性全局测试回归 | `tests/llm/`<br>`tests/core/`<br>`tests/coding/` | 575 pytest |
| **Task 3** | 前端表现层平移至顶层 `tui/`、净化 `client.ts` 与配置根目录 `package.json` | `tui/`<br>`tui/src/client.ts`<br>`package.json` | 8 npm tests |
| **Task 4** | 全 Monorepo 终极回归验证、文档更新与交付推送 | `README.md`<br>`AGENTS.md` | 583 passed |

---

## 任务执行细节 (Detailed Tasks)

### Task 1: Python 源码统一平移至根目录 `src/` 与根目录 `pyproject.toml` 配置

**Files:**

- Create: `pyproject.toml` (根目录)
- Create: `src/` (平移 `packages/my-agent-llm/src/my_agent_llm`, `packages/my-agent-core/src/my_agent_core`, `packages/my-coding-agent/src/my_coding_agent`)
- Delete: `packages/my-agent-llm/src`, `packages/my-agent-core/src`, `packages/my-coding-agent/src`

- [ ] **Step 1: 创建根目录 `src/` 并将 3 个核心 Python 源码包平移进入**

```bash
mkdir -p src
cp -r packages/my-agent-llm/src/my_agent_llm src/
cp -r packages/my-agent-core/src/my_agent_core src/
cp -r packages/my-coding-agent/src/my_coding_agent src/
```

- [ ] **Step 2: 编写根目录 `pyproject.toml`**

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

- [ ] **Step 3: 运行 `uv sync` 生成全局唯一的 `.venv` 与 `uv.lock`**

Run: `uv sync`
Expected: 成功同步所有依赖并在根目录下生成全局 `.venv`。

- [ ] **Step 4: 验证 Python 3 大核心包直接原生导入**

Run: `uv run python -c "import my_agent_llm, my_agent_core, my_coding_agent; print('All 3 core packages imported cleanly')"`
Expected: `All 3 core packages imported cleanly`

- [ ] **Step 5: 提交代码**

```bash
git add pyproject.toml uv.lock src/
git commit -m "feat(repo): 统一 Python 源码目录至 src/ 并建立全局唯一的 pyproject.toml"
```

---

### Task 2: 全局测试集统一平移至根目录 `tests/` 与一次性全局测试回归

**Files:**

- Create: `tests/llm/` (平移 `packages/my-agent-llm/tests`)
- Create: `tests/core/` (平移 `packages/my-agent-core/tests`)
- Create: `tests/coding/` (平移 `packages/my-coding-agent/tests`)
- Delete: `packages/my-agent-llm`, `packages/my-agent-core`, `packages/my-coding-agent` (全量删除)

- [ ] **Step 1: 创建根目录 `tests/` 并分别平移 3 个包的测试集**

```bash
mkdir -p tests/llm tests/core tests/coding
cp -r packages/my-agent-llm/tests/* tests/llm/
cp -r packages/my-agent-core/tests/* tests/core/
cp -r packages/my-coding-agent/tests/* tests/coding/
```

- [ ] **Step 2: 彻底删除旧版 `packages/` 下的 3 个 Python 包**

```bash
git rm -rf packages/my-agent-llm packages/my-agent-core packages/my-coding-agent
```

- [ ] **Step 3: 在根目录下运行单行命令执行全库测试回归**

Run: `uv run pytest`
Expected: 575 passed (76 in llm + 337 in core + 162 in coding)，100% 绿灯通过！

- [ ] **Step 4: 提交代码**

```bash
git add tests/
git commit -m "test(repo): 统一测试目录至 tests/ 并完成 575 个 Python 核心测试全量绿灯回归"
```

---

### Task 3: 前端表现层平移至顶层 `tui/`、净化 `client.ts` 与配置根目录 `package.json`

**Files:**

- Move: `packages/my-agent-tui` -> `tui`
- Delete: `packages/` (删除已完全清空的 packages 目录)
- Modify: `tui/src/client.ts` (简化子进程唤起逻辑，消除 `PYTHONPATH` 拼接)
- Create: `package.json` (根目录，配置 workspaces 与顶层 npm 脚本)

- [ ] **Step 1: 平移 `packages/my-agent-tui` 至顶层 `tui/`**

```bash
cp -r packages/my-agent-tui tui
git rm -rf packages/my-agent-tui
```

- [ ] **Step 2: 改造 `tui/src/client.ts` 净化子进程拉起**

在 `tui/src/client.ts` 中，由于 Python 已被统一安装在根目录的唯一 `.venv` 下：

```typescript
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "../..");

const args = ["run", "python", "-m", "my_coding_agent.rpc_server", "-w", workspace];
if (this.options.model) {
  args.push("-m", this.options.model);
}

// 直接以 repoRoot 为工作区拉起 uv，天然具备完整的模块搜索树，无需手动拼接 PYTHONPATH！
this.child = spawn("uv", args, {
  cwd: repoRoot,
  stdio: ["pipe", "pipe", "inherit"],
  windowsHide: true,
});
```

- [ ] **Step 3: 创建根目录 `package.json`**

```json
{
  "name": "my-pi-agent-workspace",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "workspaces": [
    "tui"
  ],
  "scripts": {
    "start": "npm start --prefix tui",
    "build": "npm run build --prefix tui",
    "test": "npm test --prefix tui"
  }
}
```

- [ ] **Step 4: 编译与运行测试**

Run:

```bash
npm run build
npm test
```

Expected: 8 tests passed in `tui/` (100% 绿灯全通，端到端真实子进程拉起成功)。

- [ ] **Step 5: 提交代码**

```bash
git add tui/ package.json
git commit -m "feat(tui): 将前端表现层提拔为顶层 tui/ 并配置根目录 npm 工作区与一键启动"
```

---

### Task 4: 全 Monorepo 终极回归验证、文档更新与交付推送

**Files:**

- Modify: `README.md`
- Modify: `AGENTS.md`

- [ ] **Step 1: 更新 `README.md` 与 `AGENTS.md` 架构说明**
  更新项目拓扑结构图，清晰展现根目录 `pyproject.toml` + `src/` 与 `tui/` 双核架构。

- [ ] **Step 2: 执行全库终极回归矩阵**

Run:

```bash
# 1. 根目录运行全部 Python 测试
uv run pytest

# 2. 根目录运行前端测试
npm test
```

Expected: Python 575 passed (100%), Node.js 8 passed (100%), 共计 583 passed。

- [ ] **Step 3: 提交并推送到 GitHub**

```bash
git add README.md AGENTS.md
git commit -am "chore(release): 完成 Tau 式单一工程与 Pi-TUI 解耦双核架构全量交付"
git push origin main
```

---

## 计划自检对照表 (Self-Review Against Spec)

1. **Spec 覆盖度**：
   - 根级单项目管理与 `pyproject.toml`：Task 1 全覆盖。
   - 源码统合到 `src/` 与测试统合到 `tests/`：Task 1、Task 2 全覆盖。
   - 彻底消灭 `packages/my-agent-*` 历史包袱：Task 2、Task 3 全覆盖。
   - 前端归位 `tui/` 与 `client.ts` 净化：Task 3 全覆盖。
   - 根目录 `npm start` 一键直通：Task 3 全覆盖。
   - 全量自动化测试回归与文档对齐：Task 4 全覆盖。
2. **占位符扫描**：全篇无任何 TBD/TODO，指令与代码完全确凿。
3. **零破坏性契约**：模块名、接口契约与测试用例 100% 保持自洽。
