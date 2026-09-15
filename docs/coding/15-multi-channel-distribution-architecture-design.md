# my-pi-agent 三维一体多端分发与发布体系架构设计规范

**Document ID:** `docs/coding/15-multi-channel-distribution-architecture-design.md`  
**Status:** Approved  
**Author:** AI Architecture Team  
**Date:** 2026-03-31  

---

## 1. 背景与分发愿景 (Vision & Background)

`my-pi-agent` 拥有出色的技术架构：**Python 智能内核（优雅的 ReAct 循环、多 Provider 驱动、健全的测试矩阵）+ Node.js 表现层（基于 `@earendil-works/pi-tui` 的 100% 像素级复刻）**。

为了让任何开发者或普通用户都能在自己的电脑上“一键下载并直接使用”，本项目需要建立一套工业级、开箱即用、无缝跨平台的**三维一体多端分发体系**：

1. **npm / npx 渠道**：让全栈/前端开发者通过 `npx my-pi-agent` 或 `npm i -g my-pi-agent` 零配置即开即用；
2. **PyPI / uvx 渠道**：让 Python / AI 开发者通过 `uvx my-pi-agent` 或 `uv tool install my-pi-agent` 一键拉起；
3. **独立一键脚本与绿色分发包**：通过 `curl -fsSL ... | bash` (Mac/Linux) 与 `irm ... | iex` (Windows) 让普通用户无需关心环境，一键安装全局可用。

---

## 2. 总体分发架构设计 (System Architecture)

```text
                                 ┌─────────────────────────────┐
                                 │   用户终端一键入口            │
                                 └──────────────┬──────────────┘
                                                │
         ┌──────────────────────────────┼──────────────────────────────┐
         ▼                              ▼                              ▼
  【支柱一：npm / npx】           【支柱二：PyPI / uvx】          【支柱三：独立安装脚本】
  npx my-pi-agent               uvx my-pi-agent                curl ... | bash / irm ... | iex
         │                              │                              │
         ▼                              ▼                              ▼
  tui/bin/my-agent.js           my_coding_agent/cli.py         ~/.my-pi-agent/bin/my-pi-agent
         │                              │                              │
         ├──────────────────────────────┴──────────────────────────────┤
         ▼                                                             ▼
┌──────────────────────────────┐                              ┌──────────────────────────────┐
│  自适应环境探针 (Env Probe)    │                              │  便携执行运行时 (Runtime)     │
│  1. 探测本地 uv 引擎           │                              │  - 自动化 Python venv 管理    │
│  2. 探测当前 Python 解释器    │ ───────────────────────────> │  - 自动化 Node.js 管道桥接    │
│  3. 探测系统 Node.js 运行时   │                              │  - 严格隔离于 ~/.my-pi-agent/ │
└──────────────────────────────┘                              └──────────────────────────────┘
                                                │
                                                ▼
                               ┌────────────────────────────────┐
                               │   TuiMainScreen (0 闪烁终端)   │
                               │               ↕                │
                               │   Python Kernel (JSON-RPC)     │
                               └────────────────────────────────┘
```

---

## 3. 支柱一：npm / npx 分发设计 (`package.json`)

### 3.1 发布包结构

根目录 `package.json` 配置为可发布的 npm 顶层包：

- `"name"`: `"my-pi-agent"`
- `"bin"`: `{ "my-pi-agent": "tui/bin/my-agent.js" }`
- `"files"`:
  - `tui/dist/` (编译后的 JS 产物)
  - `tui/bin/` (可执行引导脚本)
  - `tui/package.json`
  - `src/` (Python 核心源码)
  - `pyproject.toml`
  - `README.md`
  - `LICENSE`

### 3.2 自适应 Python 环境探针 (`tui/src/client.ts`)

当用户通过 `npx my-pi-agent` 启动时，`client.ts` 内部按照三级降级策略寻找 Python 运行时：

1. **策略 A（最佳优先）：探测系统 `uv`**
   - 执行 `uv --version`；若存在，使用 `uv run --python >=3.11 python -m my_coding_agent.rpc_server` 启动内核，无需用户配任何 venv。
2. **策略 B（次选）：探测系统 `python3` / `python`**
   - 检查 `python3 -m my_coding_agent.rpc_server --help`；若已安装相应依赖，直接启动。
3. **策略 C（全自动引导）：未安装 Python 时的友好指引**
   - 终端打印友好提示框，告知一键安装 `uv` 的单行指令（如 `curl -LsSf https://astral.sh/uv/install.sh | sh` 或 `powershell -c "irm https://astral.sh/uv/install.ps1 | iex"`）。

---

## 4. 支柱二：PyPI / uvx 分发设计 (`pyproject.toml`)

### 4.1 入口点配置

在 `pyproject.toml` 中增加 CLI 脚本导出：

```toml
[project.scripts]
my-pi-agent = "my_coding_agent.cli:main"
```

### 4.2 Python CLI 桥接器 (`src/my_coding_agent/cli.py`)

`cli.py` 承担 Python 端的主启动门面：

1. **参数解析**：透明透传所有参数（`-c`, `-r`, `-m`, `--thinking`, `--workspace` 等）；
2. **前端资源定位**：
   - 定位打包在 Python 包内的 `tui/bin/my-agent.js`；
3. **Node.js 运行时探测**：
   - 检查 `node -v`；若存在 Node.js，自动以子进程拉起 TUI：

     ```python
     subprocess.run(["node", tui_bin_path, *sys.argv[1:], "--python-executable", sys.executable])
     ```

   - 若用户电脑没有安装 Node.js，输出友好指导，并可优雅降级为交互式命令行/帮助信息。

---

## 5. 支柱三：独立一键安装脚本与绿色打包工具

### 5.1 自动化多端打包发布工具 (`scripts/build_dist.py`)

一个跨平台的 Python 构建脚本：

1. 编译前端 TUI (`npm run build --prefix tui`)；
2. 构建 Python Wheel 包；
3. 生成免安装绿色发布压缩包：`dist/my-pi-agent-v0.1.0-portable.zip` 与 `.tar.gz`；
4. 压缩包内包含自包含启动批处理脚本 `my-pi-agent.cmd` (Windows) 和 `my-pi-agent` (Shell)。

### 5.2 极简一键安装脚本

- **`install.sh`** (Mac / Linux)：

  ```bash
  curl -fsSL https://raw.githubusercontent.com/.../install.sh | bash
  ```

  - 自动检测并安装到 `~/.my-pi-agent/bin`；
  - 写入 `export PATH="$HOME/.my-pi-agent/bin:$PATH"` 到 `.bashrc` / `.zshrc`。
- **`install.ps1`** (Windows PowerShell)：

  ```powershell
  irm https://raw.githubusercontent.com/.../install.ps1 | iex
  ```

  - 自动解压至 `$HOME\.my-pi-agent\bin`；
  - 调用 `[Environment]::SetEnvironmentVariable` 将目录追加到用户全局 PATH。

---

## 6. 用户体验与文档规范 (`docs/DISTRIBUTION.md`)

编写完整的全平台分发使用指南 `docs/DISTRIBUTION.md`，包含：

1. **快速上手（三种方式任选其一）**：
   - 方式一：Node.js 用户 `npx my-pi-agent`
   - 方式二：Python 用户 `uvx my-pi-agent`
   - 方式三：独立一键安装（无依赖普通用户）
2. **开发者发布指引**：
   - 发布到 npm：`npm publish`
   - 发布到 PyPI：`uv build && uv publish`
   - 构建 Release 资产：`python scripts/build_dist.py`
