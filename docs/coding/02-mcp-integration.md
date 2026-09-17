# 原生 MCP 客户端与扩展集成规范 (`my_coding_agent.mcp`)

- **定位**：Model Context Protocol (MCP) 原生客户端与多服务端桥接引擎 (`src/my_coding_agent/mcp.py`)
- **协议标杆**：Anthropic Model Context Protocol 规范
- **核心组件**：`MCPServerConfig`、`MCPConnection`、`MCPClientManager`、`ExtensionAPI` 桥接

---

## 一、架构设计与定位

Model Context Protocol (MCP) 是连接外部丰富工具生态（如 GitHub、数据库、分析引擎、本地文件系统等）的开放标准。
在 `my-pi-agent` 中，MCP 客户端作为产品层原生扩展组件集成，负责读取工作区配置、动态启动子进程、协商协议并自动将远程工具无缝注册至内部 `ToolRegistry`：

```text
               工作区 .mcp.json 配置
                        │
                        ▼
         MCPClientManager (多服务连接管理器)
                        │
        ┌───────────────┴───────────────┐
        ▼                               ▼
  MCPConnection (Server A)        MCPConnection (Server B)
  [AsyncExitStack 双扇门管理]      [AsyncExitStack 双扇门管理]
  ├── stdio_client 子进程传输层   ├── sse_client 网络传输层
  └── ClientSession (MCP 协议层)  └── ClientSession (MCP 协议层)
        │                               │
        └───────────────┬───────────────┘
                        ▼
            动态抽取并包装为内部 Tool
     (raw_schema=远程Schema, is_parallel_safe=True)
                        │
                        ▼
         注入 CodingAgent.agent.registry
         注册 /mcp 本地状态检查命令
```

---

## 二、关键机制与实现亮点

### 1. `AsyncExitStack` 双扇门生命周期管理

MCP SDK 中的底层传输层（`stdio_server` / `sse_client`）与上层协议层（`ClientSession`）均为异步上下文管理器。为了在常驻 Agent 进程中保持稳定的长连接与优雅退出，`MCPConnection` 采用 `AsyncExitStack` 统筹两层生命周期：

- **第一扇门（物理传输层）**：拉起外部子进程或建立 SSE 网络连接，绑定输入输出管道；
- **第二扇门（协议协商层）**：创建 `ClientSession`，完成协议版本协商与能力初始化（`initialize()`）；
- **退出安全保证**：在调用 `aclose()` 时，按压栈顺序严格倒序优雅释放（先断开 ClientSession 协议连接，再终止物理子进程），杜绝进程句柄泄漏或僵尸进程。

### 2. 闭包工厂消除延迟绑定陷阱 (Closure Late-Binding)

在动态遍历并注册多个 MCP 工具时，若直接在循环体内构造 `handler` 函数，会由于 Python 变量的闭包延迟绑定，导致所有工具最终调用到的均是最后一个注册的工具。
系统设计了独立的闭包工厂函数 `_make_handler(conn, tool_name)`：

```python
def _make_handler(conn: MCPConnection, name: str):
    async def _handler(**kwargs):
        return await conn.call_tool(name, kwargs)
    return _handler
```

确保每个注册到 `ToolRegistry` 的工具对象严格捕获其专属的连接与工具标识。

### 3. 多模型 Schema 平坦化与兼容适配

部分大模型提供商（如 Google Cloud Code Assist / Antigravity）在接收带有 `$defs` 或 `$ref` 嵌套的 JSON Schema 时会触发 Protobuf 400 校验异常。
产品层在转换 MCP 工具 Schema 时执行自动平坦化展开，生成原生标准参数树，确保跨 OpenAI、Anthropic、DeepSeek、Antigravity 均可稳定解析。

### 4. 默认并发安全加速 (`is_parallel_safe=True`)

绝大多数 MCP 查询工具（如代码搜索、文档查询、元数据拉取）均为无副作用的只读操作。包装出的内部 `Tool` 默认标记 `is_parallel_safe=True`，使 LLM 单轮发起的多个工具调用能够直接享受 `asyncio.gather` 并发调度加速。

---

## 三、工作区 `.mcp.json` 规范与按需加载

在 `CodingAgent` 启动时，会自动探测当前工作区根目录是否存在 `.mcp.json` 配置文件。配置格式兼容标准 MCP 服务端声明：

```json
{
  "mcpServers": {
    "git": {
      "command": "uvx",
      "args": ["mcp-server-git", "--repository", "."],
      "env": {}
    },
    "sqlite": {
      "command": "uvx",
      "args": ["mcp-server-sqlite", "--db-path", "app.db"]
    }
  }
}
```

- **惰性按需初始化**：仅在实际执行请求或执行首轮交互前调用 `ensure_mcp_loaded()`，避免无关冷启动延时；
- **容错隔离**：单个 MCP Server 启动失败或崩溃不会中断 Agent 整体运行，错误将记录为结构化日志并通过状态面板可见。

---

## 四、`/mcp` 状态与调试命令

在终端中输入 `/mcp` 或 `/mcp status`，可在零 Token 消耗下即时检查：

- 当前已连接的 MCP 服务器名称与状态（Online / Offline）；
- 各服务器暴露出的工具清单与入参概要；
- 便于在多工具编排与外部服务接入时快速排查联调。
