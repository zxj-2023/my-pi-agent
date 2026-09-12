# my-coding-agent

`my-pi-agent` 的纯业务逻辑产品层（独立 uv 项目，Python 包名 `my_coding_agent`）。

专注于软件开发场景，提供 100% 纯净、无终端 UI 强绑定的核心工程工具集（`read` / `write` / `edit` / `bash` / `grep` / `find`）、`FileMutationQueue` 细粒度单文件并发互斥锁、原生异步 MCP 客户端，以及 Dual API 门面装配（`run` + `run_stream`）。

> 交互式终端 CLI 与 Slash 命令请参见 [`packages/my-agent-tui`](../my-agent-tui/)。

---

## 核心功能体系

### 1. 六大核心工程工具集

- **`read(path, offset=1, limit=None)`**：1-indexed 行切片、2000 行/50KB 智能截断与续读提示、二进制文件自动拦截；
- **`write(path, content)`**：细粒度写锁保护，自动递归建目录，`newline=""` 精确保持换行符；
- **`edit(path, edits)`**：**Multi-Edit 原子批量修改**、LF 归一化预检、UTF-8 BOM 与原始换行符（CRLF vs LF）精确保真、逆向切片替换防偏移、多区间非重叠防碰撞、**Unified Diff** 差异报告；
- **`bash(command, timeout=120, run_in_background=False)`**：原生异步子进程、高危命令防护、超时与协程取消时跨平台强杀进程树（Windows `taskkill /F /T` / POSIX `killpg`）、尾部截断（2000 行/50KB）与完整日志自动外溢至系统临时 `.log` 文件；
- **`grep(pattern, path=".", regex=False, ...)`**：纯 Python 跨平台正则/字面量搜索，自动忽略 `.git` / `.venv` 等缓存目录；
- **`find(pattern="*", path=".", limit=100)`**：纯 Python 跨平台 Glob 模式与模糊路径查找，输出正斜杠规范相对路径。

### 2. 路径哲学与并发锁

- 贯彻 **Pi 宽松 CWD 相对基准哲学**（`resolve_path`），无人工越界拦截，天然支持 Monorepo 跨包开发与系统临时日志读取；
- `FileMutationQueue` 细粒度并发锁，以规范化绝对物理路径加锁，同文件绝对排他互斥，跨文件完全并发。

### 3. 原生异步 MCP 客户端扩展 (`mcp.py`)

- 基于 `AsyncExitStack` 管理 `stdio_client` 与 `ClientSession` 协议层生命周期；
- 自动读取 `.mcp.json` 配置，批量挂载第三方 MCP 工具。

### 4. `CodingAgent` Dual API

- `run_stream(user_input) -> AsyncIterator[Event]`：流式一等公民入口，供终端 TUI/CLI 实时消费全生命周期事实；
- `run(user_input) -> str`：批处理高阶入口，自动消费流式生成器并返回最终回复文本。

---

## 运行与测试

```powershell
cd packages/my-coding-agent
uv sync

# 运行完整纯业务离线测试套件
uv run pytest -q
# 输出: 122 passed in ~13s (100% 绿灯全通)

# 代码规范检查
uv run ruff check .
```
