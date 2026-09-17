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

### 2. 双向自愈启动桥接 (Bi-directional Bootstrap)

系统支持无论从 Node.js 环境（`npm link` / `npx`）还是 Python 环境（`uvx` / `uv tool` / `python -m`）启动，均能自动探寻另一端运行时并建立连接：

1. **从 Node.js 端启动 (`tui/bin/my-agent.js`)**：
   按以下优先级链式自动寻找合法的 Python 解释器环境：
   - 命令行显式传入的 `--python-executable`；
   - 项目自包含虚拟环境：探测 `<package-root>/.venv/Scripts/python.exe`（Windows）或 `<package-root>/.venv/bin/python`（POSIX）；
   - 当前激活的虚拟环境：检查环境变量 `VIRTUAL_ENV`；
   - 系统全局 `python` 或 `python3`；
   - 若未探测到就绪环境，以醒目的终端输出引导开发者执行 `uv sync`。
2. **从 Python 端启动 (`src/my_coding_agent/cli.py`)**：
   `pyproject.toml` 注册了 `[project.scripts] my-pi-agent = "my_coding_agent.cli:main"`。当通过 Python 生态唤起时：
   - 自动探查操作系统 `node` 运行时；
   - 借助 `find_tui_entry()` 在开发树、包内嵌目录或 `sys.prefix/share` 寻址 `my-agent.js`；
   - 自动透传当前环境的 `--python-executable sys.executable`，无缝拉起前端交互界面。

---

## 三、命令行参数与启动选项 (CLI Flags)

全局 CLI 支持参数对齐日常研发工作流（`my-agent [options] [prompt]`）：

```bash
# 在指定工作区启动
my-pi-agent -w /path/to/project

# 续接当前项目最近一次历史会话
my-pi-agent -c

# 启动并直接为当前新会话命名
my-pi-agent -n "优化数据库连接池"

# 显式指定模型与思考预算启动
my-pi-agent -m deepseek-chat --thinking high

# 启动并直接提交首轮提示词
my-pi-agent "请帮我检查当前项目的未提交代码"
```

| 参数选项 | 简写 | 描述 | 默认值 |
| :--- | :--- | :--- | :--- |
| `[prompt]` | - | 可选首轮用户初始提问，直接在启动后提交执行 | 空 |
| `-w, --workspace <dir>` | `-w` | 目标工程根目录路径 | 当前工作目录 (`process.cwd()`) |
| `-c, --continue` | `-c` | 一键续接当前项目最近一次历史会话 | `false` |
| `-r, --resume [id]` | `-r` | 启动时打开交互式会话选择器，或直接恢复指定 ID 会话 | - |
| `--new-session` | - | 强制开启全新会话（默认行为） | `true` |
| `-n, --name <title>` | `-n` | 启动时直接为该会话命名 | `未命名会话 (default)` |
| `-m, --model <model>` | `-m` | 初始激活的大语言模型标识 | `settings.json` 中的配置 |
| `--thinking <level>` | - | 初始思考深度等级 (`off`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`) | `settings.json` 或 `off` |
| `--no-session` | - | 内存无痕沙箱模式（不持久化写入 session 文件） | `false` |
| `--mode <mode>` | - | 权限安全模式：`review` (默认) \| `yolo` \| `strict` | `review` |
| `--python-executable <path>` | - | 显式指定拉起内核的 Python 解释器绝对路径 | 自动自愈探测 |
| `-h, --help` | `-h` | 打印命令行参数帮助手册 | - |

---

## 四、多渠道发布与分发路线 (Distribution Matrix)

1. **npm 官方 Registry**：
   - 依赖项内聚，用户直接通过 `npx my-pi-agent` 或 `npm install -g my-pi-agent` 全局安装；
2. **PyPI / uvx 工具链**：
   - 支持通过 `uv tool install my-pi-agent` 安装，由 uv 自动管理自闭环的 Python 运行时环境；
3. **便携式单二进制构想 (Portable Standalone)**：
   - 采用 PyInstaller 或 embedded Python 将后端与 Node.js 单执行文件打包，实现零依赖双击即用。
