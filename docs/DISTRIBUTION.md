# my-pi-agent 多端分发与发布全指南 (Distribution & Publishing Guide)

本文档面向 **终端用户（如何下载与使用）** 与 **开发者/维护者（如何发布至各大生态）**，详细介绍 `my-pi-agent` 的多端分发机制。

---

## 目录

1. [终端用户使用指南](#1-终端用户使用指南)
   - [途径 A：Node.js / npm 用户 (推荐一键即开)](#途径-a-nodejs--npm-用户-推荐一键即开)
   - [途径 B：Python / uv 用户](#途径-b-python--uv-用户)
   - [途径 C：跨平台一键安装脚本 (零依赖用户)](#途径-c-跨平台一键安装脚本-零依赖用户)
   - [途径 D：便携免安装绿色包 (GitHub Releases)](#途径-d-便携免安装绿色包-github-releases)
2. [维护者发布指南](#2-维护者发布指南)
   - [发布至 npm 官方仓库](#发布至-npm-官方仓库)
   - [发布至 PyPI 官方仓库](#发布至-pypi-官方仓库)
   - [构建 GitHub Release 绿色分发归档](#构建-github-release-绿色分发归档)
3. [环境自适应与内部桥接机制说明](#3-环境自适应与内部桥接机制说明)

---

## 1. 终端用户使用指南

### 途径 A: Node.js / npm 用户 (推荐一键即开)

如果你的电脑已经安装了 Node.js (>=18)，无需手动克隆代码仓库，直接在任何终端执行：

```bash
# 免安装秒级拉起
npx my-pi-agent

# 或者全局安装，随时随地直接使用
npm install -g my-pi-agent
my-pi-agent
```

- **参数支持**：支持所有 CLI 选项，例如续接会话 `my-pi-agent -c`，指定模型 `my-pi-agent -m deepseek-chat`。

---

### 途径 B: Python / uv 用户

如果你的主力开发环境是 Python，推荐使用 Astral `uv` 极速运行：

```bash
# 免安装秒级运行
uvx my-pi-agent

# 或者通过 uv tool / pipx 全局持久安装
uv tool install my-pi-agent
# 安装后直接敲命令
my-pi-agent
```

> **注意**：由于 my-pi-agent 呈现层采用与 Pi 原厂 100% 像素级对齐的 `@earendil-works/pi-tui`，需要系统预先安装 Node.js 运行时。

---

### 途径 C: 跨平台一键安装脚本 (零依赖用户)

适合不想手动管理包依赖的用户，一条命令自动下载并配置全局 PATH：

- **macOS / Linux (Shell)**:

  ```bash
  curl -fsSL https://raw.githubusercontent.com/.../install.sh | bash
  ```

- **Windows (PowerShell)**:

  ```powershell
  irm https://raw.githubusercontent.com/.../install.ps1 | iex
  ```

脚本会自动将 `my-pi-agent` 注入用户全局 PATH，重启终端后即可直接键入 `my-pi-agent` 启动。

---

### 途径 D: 便携免安装绿色包 (GitHub Releases)

1. 在 GitHub Releases 下载对应版本的 `my-pi-agent-vX.Y.Z-portable.zip` 或 `.tar.gz`；
2. 解压到任意目录；
3. 双击 `my-pi-agent.cmd` (Windows) 或在终端执行 `./my-pi-agent` (Linux/macOS) 即可直接启动！

---

## 2. 维护者发布指南

### 发布至 npm 官方仓库

1. 确认版本号已在 `package.json` 与 `pyproject.toml` 中统一对齐；
2. 执行全量测试与编译：

   ```bash
   npm test
   uv run python -m pytest
   ```

3. 登录并发布：

   ```bash
   npm login
   npm publish
   ```

   *发布钩子 `prepack` 会自动触发 `npm run build --prefix my-pi-tui` 确保编译产物最新。*

---

### 发布至 PyPI 官方仓库

1. 使用 `uv` 编译构建 Python Wheel 与源码包：

   ```bash
   uv build
   ```

2. 发布至 PyPI：

   ```bash
   uv publish
   ```

---

### 构建 GitHub Release 绿色分发归档

运行项目内置的自动化打包构建工具：

```bash
uv run python scripts/build_dist.py
```

该命令会自动完成：

- TypeScript TUI 编译；
- 收集 Python 核心与前端 JS 产物；
- 注入跨平台 `.cmd` 与 `.sh` 启动脚本；
- 在 `dist/` 目录下生成：
  - `dist/my-pi-agent-v0.1.0-portable.zip`
  - `dist/my-pi-agent-v0.1.0-portable.tar.gz`
将这两个文件直接上传到 GitHub Releases 附件即可。

---

## 3. 环境自适应与内部桥接机制说明

`my-pi-agent` 采用独特的**双核分发桥接机制**：

```text
               ┌───────────────────────┐
               │    my-pi-agent CLI    │
               └───────────┬───────────┘
                           │
       ┌───────────────────┴───────────────────┐
       ▼                                       ▼
【Node.js 侧启动 (npx)】               【Python 侧启动 (uvx)】
tui/src/client.ts                     my_coding_agent/cli.py
  - 自动探测系统 uv                     - 自动探测系统 node
  - 降级探测 python3/python             - 透传 --python-executable
  - 启动 Python rpc_server              - 桥接启动 tui/bin/my-agent.js
```

无论用户从哪一端切入，两端均具备对偶的环境探针，确保用户体验完全一致、开箱即用。
