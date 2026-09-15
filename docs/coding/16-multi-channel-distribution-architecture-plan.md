# my-pi-agent 三维一体多端分发与发布体系实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 依据 `docs/coding/15-multi-channel-distribution-architecture-design.md`，构建工业级三维一体多端分发体系（npm/npx、PyPI/uvx、独立安装脚本与便携打包器），让任何用户在没有预装完整开发环境的情况下，均可秒级一键运行 `my-pi-agent`。

**Architecture:**

- **Python CLI 门面 (`src/my_coding_agent/cli.py`)**：提供 `[project.scripts] my-pi-agent = "my_coding_agent.cli:main"`，自动探测系统 Node.js 并桥接拉起 TUI 前端，支持 `uvx my-pi-agent`。
- **npm 自适应环境探针 (`tui/src/client.ts` & `tui/bin/my-agent.js`)**：在 Node 启动端自适应探测 `uv` 与 `python`，并支持 `--python-executable` 显式透传；配置根目录 `package.json` 支持 `npx my-pi-agent`。
- **自动化跨平台打包器 (`scripts/build_dist.py`)**：一键完成 TUI 编译、Python Wheel 构建与绿色便携 Release Zip 打包。
- **一键安装脚本 (`install.sh` & `install.ps1`)**：分别针对 Unix (Linux/macOS) 与 Windows PowerShell 提供零配置安装入 PATH 的脚本。
- **分发与发布指南 (`docs/DISTRIBUTION.md`)**：提供完整发布与使用手册。

**Tech Stack:** Python 3.11+, TypeScript, Node.js, hatchling, `@earendil-works/pi-tui`, PowerShell, Bash.

---

## 实施任务总览表 (Overview)

| Task # | 核心任务 | 交付文件 / 模块 | 预估验证 |
| :--- | :--- | :--- | :--- |
| **Task 1** | Python 端 CLI 启动器与入口点实现 | `src/my_coding_agent/cli.py`<br>`pyproject.toml`<br>`tests/coding/test_cli.py` | 4 项 Python 单元测试 |
| **Task 2** | npm / npx 自适应环境探针与发布配置 | `tui/src/client.ts`<br>`tui/bin/my-agent.js`<br>`package.json` | 2 项 TUI 测试 + 编译通过 |
| **Task 3** | 自动化跨平台打包发布工具实现 | `scripts/build_dist.py`<br>`tests/coding/test_build_dist.py` | 2 项构建与打包集成测试 |
| **Task 4** | 跨平台一键安装脚本 (Shell & PowerShell) | `install.sh`<br>`install.ps1`<br>`tests/coding/test_install_scripts.py` | 2 项脚本语法与行为测试 |
| **Task 5** | 全平台分发手册编写与终极全量回归 | `docs/DISTRIBUTION.md`<br>`npm test`<br>`uv run python -m pytest` | 645+ 项全库测试绿灯 |

---

## 任务执行细节 (Detailed Tasks)

### Task 1: Python 端 CLI 启动器与入口点实现

**Files:**

- Create: `src/my_coding_agent/cli.py`
- Create: `tests/coding/test_cli.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: 编写 `tests/coding/test_cli.py` 测试用例**

编写对 `my_coding_agent.cli` 的单元测试：

- 测试参数透传与解析；
- 测试在有 Node 环境下正确定位 `my-agent.js` 并执行桥接；
- 测试在无 Node 环境下输出友好的安装引导提示而绝不抛出未捕获异常。

- [ ] **Step 2: 运行测试验证失败**

Run: `uv run python -m pytest tests/coding/test_cli.py`
Expected: FAIL (`ModuleNotFoundError: No module named 'my_coding_agent.cli'`).

- [ ] **Step 3: 实现 `src/my_coding_agent/cli.py`**

- 实现 `find_tui_entry() -> Path | None`，优先查找开发工作区 `tui/bin/my-agent.js`，次选包内安装的静态目录；
- 实现 `main()` 函数：
  - 检查 `sys.argv` 中的帮助与基础选项；
  - 检查 `shutil.which("node")`：
    - 若找到，使用 `subprocess.run(["node", str(tui_entry), *sys.argv[1:], "--python-executable", sys.executable])`；
    - 若未找到，打印格式精美的安装提示，引导安装 Node.js。

- [ ] **Step 4: 配置 `pyproject.toml` 并验证测试通过**

在 `pyproject.toml` 中增加：

```toml
[project.scripts]
my-pi-agent = "my_coding_agent.cli:main"
```

Run: `uv run python -m pytest tests/coding/test_cli.py`
Expected: PASS (4 passed).

---

### Task 2: npm / npx 自适应环境探针与发布配置

**Files:**

- Modify: `tui/src/client.ts`
- Modify: `tui/bin/my-agent.js`
- Modify: `package.json`

- [ ] **Step 1: 更新 `tui/bin/my-agent.js` 支持 `--python-executable`**

解析命令行传入的 `--python-executable <path>` 参数，并将其传递给 `AgentApp` 启动配置。

- [ ] **Step 2: 重构 `tui/src/client.ts` Python 运行时自适应发现逻辑**

实现三级降级发现策略：

1. 若调用方传入了 `options.pythonExecutable`，直接使用该路径；
2. 若环境变量或系统 PATH 中存在 `uv`（通过 `whichSync("uv")` 校验），使用 `uv run python -m my_coding_agent.rpc_server`；
3. 检查系统是否存在 `python3` 或 `python`；
4. 若均不存在，输出明确格式化的引导日志，避免黑盒崩溃。

- [ ] **Step 3: 配置根目录 `package.json` 发布元数据**

将根目录 `package.json` 的 `"private"` 调整为支持发布的包，声明 `"bin": { "my-pi-agent": "tui/bin/my-agent.js" }` 与 `"files"` 列表。

- [ ] **Step 4: 编译并运行 TUI 单元测试**

Run: `npm run build --prefix tui && npm test`
Expected: 21 passed (100% 绿灯).

---

### Task 3: 自动化跨平台打包发布工具实现

**Files:**

- Create: `scripts/build_dist.py`
- Create: `tests/coding/test_build_dist.py`

- [ ] **Step 1: 编写 `tests/coding/test_build_dist.py`**

测试 `build_dist.py` 的关键流程模块（文件清单收集、启动脚本生成、版本号读取）。

- [ ] **Step 2: 运行测试验证失败**

Run: `uv run python -m pytest tests/coding/test_build_dist.py`
Expected: FAIL.

- [ ] **Step 3: 实现 `scripts/build_dist.py`**

- 自动执行 `npm run build --prefix tui` 编译前端；
- 收集必要的运行产物：`tui/dist/`、`tui/bin/`、`src/`、`pyproject.toml`；
- 生成跨平台绿色便携启动脚本：`my-pi-agent.cmd` 与 `my-pi-agent` (Shell)；
- 打包为 `dist/my-pi-agent-v0.1.0-portable.zip`。

- [ ] **Step 4: 运行测试与试运行构建**

Run: `uv run python -m pytest tests/coding/test_build_dist.py`
Expected: PASS.

---

### Task 4: 跨平台一键安装脚本 (Shell & PowerShell)

**Files:**

- Create: `install.sh`
- Create: `install.ps1`
- Create: `tests/coding/test_install_scripts.py`

- [ ] **Step 1: 编写 `install.sh` (Linux/macOS)**

- 检查环境中的 `curl`, `tar`, `node`, `uv` / `python`；
- 支持下载解压到 `$HOME/.my-pi-agent/bin`；
- 写入 PATH 导出语句到用户 `.bashrc` / `.zshrc`。

- [ ] **Step 2: 编写 `install.ps1` (Windows PowerShell)**

- 检查系统环境；
- 解压到 `$HOME\.my-pi-agent\bin`；
- 创建 `my-pi-agent.cmd` 启动脚本；
- 通过 PowerShell Registry / Environment 将该目录安全追加至用户 PATH。

- [ ] **Step 3: 编写语法与逻辑验证测试并运行**

Run: `uv run python -m pytest tests/coding/test_install_scripts.py`
Expected: PASS.

---

### Task 5: 全平台分发手册编写与终极全量回归

**Files:**

- Create: `docs/DISTRIBUTION.md`
- Verify: 全量 Python (645+ tests) 与 TypeScript (21 tests)

- [ ] **Step 1: 编写 `docs/DISTRIBUTION.md` 用户与开发者使用指南**

覆盖：

1. 用户端安装体验（npm、uvx、一键脚本）；
2. 开发者发布到 npm 的完整指令；
3. 开发者发布到 PyPI 的完整指令；
4. 本地构建绿色发布包流程。

- [ ] **Step 2: 执行前端 TUI 编译与回归测试**

Run: `npm run build --prefix tui && npm test`
Expected: 21 passed.

- [ ] **Step 3: 执行后端 Python 全量回归测试**

Run: `uv run python -m pytest`
Expected: 全部 645+ 项测试 100% 绿灯通过。

- [ ] **Step 4: 静态类型检查**

Run: `npx pyright`
Expected: 0 errors, 0 warnings.
