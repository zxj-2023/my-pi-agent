# my-agent-tui

`my-pi-agent` 的终端 UI 呈现与交互应用层（独立 uv 项目，Python 包名 `my_agent_tui`）。

对标 **Pig-Mono** (`pig-tui`) 与 **Pi** (`packages/tui`)，负责管理终端 REPL 交互循环、多行输入、Tab 命令补全、流式思考气泡与 Markdown 输出、彩色 Unified Diff 高亮渲染及 Slash 命令分发中枢。

---

## 核心功能体系

### 1. 交互式终端 REPL

- **全局控制台入口**：`my-agent-tui` 或 `python -m my_agent_tui`；
- **沉浸式流式体验 (`EventRenderer`)**：
  - `\U0001f4ad` 思考过程打字机 (`ThinkingDelta`)：以低对比度思考气泡独立展现模型推导过程；
  - 正文增量打字机 (`ContentDelta`)：支持 Markdown 渲染与括号标签安全转义；
  - 工具状态徽标：`⚙️ [tool_name]` 开始调用指示与 `✓ OK` / `✗ Failed` 完成反馈（带错误预览）；
  - **彩色 Unified Diff 高亮**：针对文件修改自动生成 Monokai 主题红绿差异补丁；
- **专业键盘与输入交互**：
  - 基于 `prompt_toolkit` 提供持久化命令历史（`.my_agent_core/cli_history`）；
  - Tab 键自动补全斜杠命令；
  - 流式输出期间 `Ctrl+C` 仅取消当前生成轮次，保护交互会话不崩溃；
- **Windows 控制台 UTF-8 保护 (`cli_base.py`)**：启动时自动将控制台输出流重置为 UTF-8，彻底解决 emoji 与彩色字符在 Windows 下的编码崩溃。

### 2. 生产级 Slash 命令中枢 (`CommandDispatcher`)

- `/help`：以美化表格展示当前可用命令清单与功能描述；
- `/clear`：清空终端屏幕并重绘欢迎首部；
- `/undo`：沿 `Session` 树回溯至上一轮提问的父节点（`session.rewind()`），并自动重置转录本与上下文状态；
- `/compact`：显式触发 L4 智能上下文摘要，并反馈 Token 节约统计；
- `/session`：查看当前 Session ID、持久化路径与节点统计；
- `/tasks`：展示当前 `TaskStore` 任务看板（状态、主题、依赖）；
- `/mcp`：查看已连接的 MCP 服务器状态与已挂载的外部工具清单；
- **`/quota`**：查询 Google Antigravity 各模型（Gemini 3.8/3.7/3.1 等）的实时免费配额进度条与重置倒计时；
- **`/model [name]`**：列出候选模型或在当前会话中即时热切换底层大模型；
- **`/login [provider]`**：自动检测并关联本地 Pi 现成凭据（`~/.pi/agent/auth.json`）；
- `/exit` 或 `/quit`：优雅退出。

---

## 运行与测试

```powershell
cd packages/my-agent-tui
uv sync

# 启动交互式编码终端
uv run my-agent-tui

# 运行独立测试套件
uv run pytest -q
# 输出: 56 passed in ~5s (100% 绿灯全通)

# 代码规范检查
uv run ruff check .
```
