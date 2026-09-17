# 工程发布、全平台分发与全局 CLI 规范 (`distribution`)

- **定位**：工程分发体系、跨平台 CLI 绑定与多渠道安装打包规范 (`package.json`, `pyproject.toml`, `tui/bin/`)
- **核心能力**：全局 CLI（`my-pi-agent` 与 `my-agent` 双命令绑定）、npm workspaces 与 `npm link` 原生支持、Python 单一工程统一内核、跨平台分发路径

---

## 一、双引擎统一分发拓扑 (Dual-Engine Architecture)

`my-pi-agent` 采用了 **“Python 统一业务内核 + TypeScript 独立交互前端”** 的高效融合架构：

```text
根目录 (Tau 式单一 Python 项目与 npm monorepo)
├── pyproject.toml              # Python uv 依赖声明 (单 .venv 运行 660+ 测试)
├── package.json                # npm workspaces 配置，声明全局 CLI 命令 bin
├── src/                        # Python 后端内核 (my_agent_core, my_coding_agent, my_agent_llm)
└── tui/                        # TypeScript 前端 (独立构建，100% 对标 Pi 原厂终端)
    └── bin/
        └── my-agent.js         # 全局可执行 Shebang 入口脚本
```

---

## 二、全局 CLI 绑定规范 (`npm link` & `npm install -g`)

通过在根目录 `package.json` 配置 `workspaces` 与顶层 `bin` 映射：

```json
{
  "name": "my-pi-agent",
  "version": "0.1.0",
  "bin": {
    "my-pi-agent": "tui/bin/my-agent.js",
    "my-agent": "tui/bin/my-agent.js"
  },
  "workspaces": [
    "tui"
  ]
}
```

### 1. 全局即时链接 (Local Development Link)

在项目根目录下执行：

```bash
npm link
```

即可将 `my-pi-agent` 与 `my-agent` 注册至全局 PATH，允许开发者在操作系统的任意工作区目录中秒级唤起体验。

### 2. 子进程 Python 内核自愈探测

`tui/bin/my-agent.js` 在启动时，按以下优先级链式自动寻找合法的 Python 解释器环境：

1. **项目自包含虚拟环境**：探测 `<package-root>/.venv/Scripts/python.exe`（Windows）或 `<package-root>/.venv/bin/python`（POSIX）；
2. **当前环境激活的虚拟环境**：检查环境变量 `VIRTUAL_ENV`；
3. **系统全局 Python**：回退至全局 `python` 或 `python3`；
4. **自检失败优雅提示**：若未探测到依赖就绪的 Python 运行时，以醒目的终端警告输出诊断步骤（`uv sync` 指引）。

---

## 三、命令行参数与启动选项 (CLI Flags)

全局命令支持直接传入参数对齐日常研发工作流：

```bash
# 在指定工作区启动
my-pi-agent /path/to/project

# 显式指定模型启动
my-pi-agent -m gpt-4o

# 启动并设定初始思考预算
my-pi-agent --thinking high

# 直接恢复历史会话
my-pi-agent -r session-12345
```

| 参数选项 | 简写 | 描述 | 默认值 |
| :--- | :--- | :--- | :--- |
| `[workspace]` | - | 目标工程根目录路径 | 当前工作目录 (`process.cwd()`) |
| `--model` | `-m` | 初始激活的大语言模型标识 | `settings.json` 中的 `defaultModel` |
| `--thinking` | `-t` | 初始思考预算等级 (`off`, `low`, `high`, `max`) | `settings.json` 中的配置或 `off` |
| `--resume` | `-r` | 恢复指定的历史会话 ID | 自动进入新建或最近会话 |
| `--version` | `-v` | 输出当前版本号 | - |
| `--help` | `-h` | 打印可用命令行参数帮助手册 | - |

---

## 四、多渠道发布与分发路线 (Distribution Matrix)

1. **npm 官方 Registry**：
   - 依赖项内聚，用户直接通过 `npx my-pi-agent` 或 `npm install -g my-pi-agent` 全局安装；
2. **PyPI / uvx 工具链**：
   - 支持通过 `uv tool install my-pi-agent` 安装，由 uv 自动管理自闭环的 Python 运行时环境；
3. **便携式单二进制构想 (Portable Standalone)**：
   - 采用 PyInstaller 或 embedded Python 将后端与 Node.js 单执行文件打包，实现零依赖双击即用。
