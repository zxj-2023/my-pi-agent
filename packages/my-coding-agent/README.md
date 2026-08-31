# my-coding-agent

`my-pi-agent` 的产品与应用层（独立 uv 项目，Python 包名 `my_coding_agent`）。

专注于软件开发场景，提供工作区安全编码文件工具集（`read` / `write` / `edit` / `bash`）、`FileMutationQueue` 细粒度单文件并发互斥锁、原生异步 MCP 客户端扩展，以及开箱即用的 `CodingAgent` 组装门面。

---

## 核心功能

- **工作区安全文件工具集**：
  - `read(path, limit=None, offset=None)`：精细化行级读取与越界提示；
  - `write(path, content)`：细粒度写锁保护，自动递归建目录；
  - `edit(path, old_text, new_text)`：精确替换一次，未找到/多重匹配智能排查提示；
  - `bash(command, run_in_background=False)`：在工作区根目录执行 Shell，支持超时截断日志捕获与 `run_in_background=True` 后台非阻塞异步执行。
- **`FileMutationQueue` 单文件细粒度并发写锁**：
  - 按文件物理绝对路径管理 `asyncio.Lock`；
  - 多文件并发修改耗时直降，同名文件操作严格按序排队。
- **原生异步 MCP 客户端扩展（`mcp.py`）**：
  - 基于 `AsyncExitStack` 管理 `stdio_client` 与 `ClientSession` 协议层生命周期；
  - 自动读取 `.mcp.json` 配置，批量挂载第三方 MCP 工具。
- **`CodingAgent` 门面**：
  - 自动装配文件工具、`TaskStore` 任务看板与 `BackgroundRunner` 后台执行器；
  - 支持多轮任务规划与后台测试运行端到端流转。

---

## 运行离线测试

```powershell
cd packages/my-coding-agent
uv sync
uv run python -m pytest -q
# 输出: 22 passed in ~10s
```
