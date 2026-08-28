# Extension 扩展与命令路由机制 (`my_agent_core.extensions`)

- **定位**：代码级模块扩展与本地 0 Token 命令调度系统 (`packages/my-agent-core/src/my_agent_core/extensions/`)
- **核心类**：`ExtensionAPI`, `ExtensionManager`
- **主要实现**：`extensions/core.py`

---

## 一、架构设计与定位

`extensions` 模块为上层应用提供了向 Agent 动态注入能力与生命周期干预的官方扩展面。
其设计对标了 Pi 的 **“静态注册面（`ExtensionAPI`） + 动态调度总管（`ExtensionManager`）”** 解耦架构：

```text
                  ┌────────────────────────────────────────────────────────┐
                  │                 Extension 入口函数                     │
                  │              def extension(api: ExtensionAPI):         │
                  └───────────────────────────┬────────────────────────────┘
                                              │
                ┌─────────────────────────────┴─────────────────────────────┐
                ▼                                                           ▼
   ┌────────────────────────────────────────┐                  ┌────────────────────────────────────────┐
   │       ExtensionAPI (开发者契约面)      │                  │      ExtensionManager (调度仓储)       │
   │  • @api.on(Event)       ➔ 订阅生命周期 │                  │  • 递归扫描与动态 importlib 加载       │
   │  • @api.tool(...)       ➔ 注册业务工具 │ ──注入 Agent──►  │  • 坏扩展单点故障隔离保护 (Never-Crash)│
   │  • @api.command("name") ➔ 注册斜杠命令 │                  │  • 本地命令反射调度 (Bypass-LLM)       │
   └────────────────────────────────────────┘                  └────────────────────────────────────────┘
```

---

## 二、核心三大能力

### 1. 事件订阅与拦截：`api.on`

```python
@api.on(BeforeModelCall)
def inject_reminder(event: BeforeModelCall, api: ExtensionAPI) -> HookResult:
    # 临时注入提示，不污染底层 Session 树
    return HookResult(updated_messages=event.messages + [Message(role="user", content="[REMINDER: Be concise]")])
```

- **双参注入**：自动将底层的单参 `(event)` 包装注入 `(event, api)` 双参，让扩展在回调中可调用 `api` 挂载更多动态逻辑；
- **类型重载**：提供完整的 `@overload` 类型注解，精准支持装饰器用法。

### 2. 工具注册与覆盖：`api.tool` 与 `api.register_tool`

- `@api.tool` 内部复用底层 Pydantic 动态建模；
- **后加载覆盖机制（Overriding Power）**：Extension 在最后阶段被加载，若注册了与内置工具同名（如 `read`），会静默覆盖默认实现，方便开发者无缝替换“带权限审计的只读沙箱工具”。

### 3. 本地 0 Token 斜杠命令调度（Bypass-LLM Dispatching）

```python
@api.command("status", description="查看运行状态")
def cmd_status():
    return "Agent running normally."
```

- 用户在终端输入 `/status` 时，CLI 调用 `ExtensionManager.handle_command("status", args)`；
- 内部通过 `inspect.signature` 自动适配 0 参或 1 参函数，直接在本地返回结果，**不调用大模型、不花 Token、不污染会话历史**。

---

## 三、安全与异常防御

- **原生异步加载**：支持 `async def extension(api)` 与同步 `def` 入口，支持在启动期建立异步网络长连接（如 MCP）；
- **单点故障隔离（Fault Isolation）**：`ExtensionManager.load_extension` 内部用 `try...except` 捕获异常，单个扩展的语法或运行错误只记 Warning，绝不阻止 Agent 正常启动。
