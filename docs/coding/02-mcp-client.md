# 原生异步 MCP 客户端与工具桥接设计规范 (`my_coding_agent.mcp`)

- **定位**：Model Context Protocol 客户端插件与远程工具桥接引擎 (`packages/my-coding-agent/src/my_coding_agent/mcp.py`)
- **核心类**：`MCPServerConfig`, `MCPConnection`, `MCPClientManager`
- **扩展入口**：`extension(api: ExtensionAPI)`

---

## 一、架构设计与定位

MCP (Model Context Protocol) 是连接外部丰富工具生态（如 GitHub、数据库、文件系统等）的工业标准。
在 `my-coding-agent` 中，MCP 客户端以 **标准 Extension 插件** 的形式落地，通过读取 `.mcp.json` 动态启动子进程、协商协议并自动将远程工具桥接注册进 Agent：

```text
               .mcp.json (工作区配置)
                    │
                    ▼
            MCPClientManager (多 Server 管理)
                    │
        ┌───────────┴───────────┐
        ▼                       ▼
   MCPConnection (Server A) MCPConnection (Server B)
   [AsyncExitStack 管理]    [AsyncExitStack 管理]
   ├── stdio_client 子进程  ├── stdio_client 子进程
   └── ClientSession (MCP)  └── ClientSession (MCP)
        │                       │
        └───────────┬───────────┘
                    ▼
            包装为内部 Tool 对象
     (raw_schema=远程Schema, is_parallel_safe=True)
                    │
                    ▼
        ExtensionAPI.register_tool() ➔ 注入 Agent.registry
        ExtensionAPI.command("mcp")  ➔ 注册 /mcp 状态命令
```

---

## 二、关键机制与实现亮点

### 1. `AsyncExitStack` 双扇门生命周期管理

MCP SDK 中的 `stdio_client` 与 `ClientSession` 都是异步上下文管理器。为了在长期运行的 Agent 中保持长连接，`MCPConnection` 采用 `AsyncExitStack` 优雅管理两层生命周期：

- **第一扇门**：物理传输层（`stdio_client` 子进程及其管道输入输出流）；
- **第二扇门**：协议层（`ClientSession` JSON-RPC 2.0 会话）；
- **安全退出**：调用 `aclose()` 时按压栈顺序严格倒序释放（先关 ClientSession 会话，再杀子进程），绝不泄漏系统进程句柄。

### 2. 闭包工厂消除延迟绑定陷阱（Closure Late-Binding Fix）

遍历包装远程工具时，如果直接在循环内定义 handler 函数，会导致所有工具在运行时全部调用最后一个工具（Python 循环变量延迟绑定）。
我们采用独立的 `_make_handler(conn, tool_name)` 闭包工厂函数，确保每个工具在内存中精确绑定属于自己的连接与工具名称。

### 3. 声明式 `is_parallel_safe=True` 并发加速

所有包装出的 MCP 远程工具默认标记只读并发安全，大模型同时调用多个 MCP 工具时直接享受 `asyncio.gather` 并行加速。

### 4. `/mcp` 本地状态命令

注册 `@api.command("mcp")`，支持用户在终端输入 `/mcp` 或 `/mcp status` 查看当前已连接的 MCP 服务器列表与工具总数（0 Token 消耗）。
