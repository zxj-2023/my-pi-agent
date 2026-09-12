# my-coding-agent

`my-pi-agent` 的产品与应用层（独立 uv 项目，Python 包名 `my_coding_agent`）。

专注于软件开发场景，对标开源标杆（**Pi**、**Tau**、**Pig-Mono**），提供生产级交互式终端 CLI、Slash 命令系统、6 大核心工程工具集（`read` / `write` / `edit` / `bash` / `grep` / `find`）、`FileMutationQueue` 细粒度单文件并发互斥锁、原生异步 MCP 客户端，以及 Dual API 门面装配。

---

## 核心功能体系

### 1. 交互式终端 CLI 与流式渲染 (Phase 2A)

- **全局命令行入口**：`my-coding-agent` 或 `python -m my_coding_agent`；
- **沉浸式流式体验 (`EventRenderer`)**：
  - 思考过程打字机 (`ThinkingDelta`)：以低对比度思考气泡独立展现模型推导过程；
  - 正文增量打字机 (`ContentDelta`)：支持 Markdown 渲染与括号标签安全转义；
  - 工具状态徽标：`⚙️ [tool_name]` 开始调用指示与 `✓ OK` / `✗ Failed` 完成反馈；
  - **彩色 Unified Diff 高亮**：针对文件修改自动生成红绿差异补丁（Syntax Highlighting）；
- **专业键盘与输入交互**：
  - 基于 `prompt_toolkit` 提供持久化命令历史（`.my_agent_core/cli_history`）；
  - Tab 键自动补全斜杠命令；
  - 流式输出期间 `Ctrl+C` 仅取消当前生成轮次，保护交互会话不崩溃；
- **Windows 控制台 UTF-8 保护 (`cli_base.py`)**：启动时自动将控制台输出流重置为 UTF-8，彻底解决 emoji 与彩色字符在 Windows 下的编码崩溃。

### 2. Slash 命令分发中枢 (`CommandDispatcher`)

内置 8 大核心生产级命令：

- `/help`：以美化表格展示当前可用命令清单与功能描述；
- `/clear`：清空终端屏幕并重绘欢迎首部；
- `/undo`：沿 `Session` 树回溯至上一轮提问的父节点（`session.rewind()`），彻底撤销上一轮所有修改；
- `/compact`：显式触发 L4 智能上下文摘要，并反馈 Token 节约统计；
- `/session`：查看当前 Session ID、持久化路径与节点统计；
- `/tasks`：展示当前 `TaskStore` 任务看板（状态、主题、依赖）；
- `/mcp`：查看已连接的 MCP 服务器状态与已挂载的外部工具清单；
- `/exit` 或 `/quit`：优雅退出。

### 3. 六大核心工程工具集

- **`read(path, offset=1, limit=None)`**：1-indexed 行切片、2000 行/50KB 智能截断与续读提示、二进制文件自动拦截；
- **`write(path, content)`**：细粒度写锁保护，自动递归建目录，`newline=""` 精确保持换行符；
- **`edit(path, edits)`**：**Multi-Edit 原子批量修改**、LF 归一化预检、UTF-8 BOM 与原始换行符（CRLF vs LF）精确保真、逆向切片替换防偏移、多区间非重叠防碰撞、**Unified Diff** 差异报告；
- **`bash(command, timeout=120, run_in_background=False)`**：原生异步子进程、高危命令防护、超时与协程取消时跨平台强杀进程树（Windows `taskkill /F /T` / POSIX `killpg`）、尾部截断（2000 行/50KB）与完整日志自动外溢至系统临时 `.log` 文件；
- **`grep(pattern, path=".", regex=False, ...)`**：纯 Python 跨平台正则/字面量搜索，自动忽略 `.git` / `.venv` 等缓存目录；
- **`find(pattern="*", path=".", limit=100)`**：纯 Python 跨平台 Glob 模式与模糊路径查找，输出正斜杠规范相对路径。

### 4. 路径哲学与并发锁

- 贯彻 **Pi 宽松 CWD 相对基准哲学**（`resolve_path`），无人工越界拦截，天然支持 Monorepo 跨包开发与系统临时日志读取；
- `FileMutationQueue` 细粒度并发锁，以规范化绝对物理路径加锁，同文件绝对排他互斥，跨文件完全并发。

### 5. `CodingAgent` Dual API

- `run_stream(user_input) -> AsyncIterator[Event]`：流式一等公民入口，供终端 TUI/CLI 实时消费全生命周期事实；
- `run(user_input) -> str`：批处理高阶入口，自动消费流式生成器并返回最终回复文本。

---

## 运行与测试

```powershell
cd packages/my-coding-agent
uv sync

# 启动交互式终端 CLI
uv run my-coding-agent
# 或
uv run python -m my_coding_agent -w . -m gpt-4o

# 运行完整离线测试套件
uv run pytest -q
# 输出: 164 passed in ~15s (100% 绿灯全通)

# 代码规范检查
uv run ruff check .
```
