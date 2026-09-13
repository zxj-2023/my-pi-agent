# my-pi-agent Pi-TUI 前端表现层设计规范 (Pi-Shell + Python Kernel 双核架构)

> **文档版本**: 1.0.0  
> **创建日期**: 2026-09-12  
> **设计目标**: 彻底告别传统 Python 终端界面的粗糙与割裂，**最大化直接复用 Pi 原厂现成的 `@earendil-works/pi-tui` 渲染引擎与交互组件**，构建高质感、高流畅度、工业级的终端编程智能体。

---

## 1. 核心理念与技术选型（Philosophy & Principles）

### 1.1 核心原则：能用 Pi 现成的，坚决不重复造轮子

Pi 的终端交互层是由资深图形专家 **Mario Zechner** 精心调教的工业级成果，包含：

- **差量重绘引擎 (`TuiMainScreen`)**：基于终端行级差量更新，无任何虚拟 DOM 开销，千轮对话恒定 0 延迟；
- **同步输出协议 (`CSI 2026`)**：原子性垂直刷新，彻底消灭字符撕裂与闪烁；
- **Main Screen 原生滚轮模式**：不劫持全屏（Alt-Screen），保留终端原生历史与滚轮翻页；
- **中文输入法 (IME) 硬件光标锚定 (`CURSOR_MARKER`)**：输入法候选浮窗永远精准对齐当前光标；
- **24-bit TrueColor 卡片视觉系统 (`dark.json`)**：圆角细线卡片、柔和底色气泡、点阵动态微动画；
- **成熟的 Coding Agent 组件树**：`AssistantMessageComponent`（流式 Markdown 与折叠思考块）、`ToolExecutionComponent`（就地更新折叠卡片与参数/结果高亮）、`Editor`（多行富文本输入框）。

**我们的策略**：
将 `my-coding-agent` 作为纯粹的**无头 Python 业务内核（Python Kernel）**，通过 `packages/my-agent-shell`（TypeScript / Node.js）直接装配 Pi 现成的 TUI 渲染器与组件，两者通过标准的 **stdio JSON-RPC 双向流**无缝连接。

---

## 2. 整体双核架构全景（Architecture Overview）

```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                 终端 TTY (用户交互端)                                   │
│           (键盘输入、鼠标滚轮、24-bit TrueColor、中文 IME 候选框、CSI 2026 同步屏障)       │
└───────────────────────────────────────────▲────────────────────────────────────────────┘
                                            │ Direct TTY (Raw Mode & ANSI Escape)
┌───────────────────────────────────────────▼────────────────────────────────────────────┐
│                    前端表现层 Shell: packages/my-agent-shell (Node.js/TS)              │
│                                                                                        │
│   ┌────────────────────────────────────────────────────────────────────────────────┐   │
│   │                     @earendil-works/pi-tui 原生核心库                          │   │
│   │   • TuiMainScreen: 差量重绘 / Main-screen 滚轮保留 / CSI 2026 同步输出           │   │
│   │   • Editor: 多行富文本输入框 / 光标移动 / CURSOR_MARKER 输入法锚定               │   │
│   │   • Theme System: Pi 官方 dark.json / light.json 柔和调色盘                     │   │
│   └────────────────────────────────────────────────────────────────────────────────┘   │
│   ┌────────────────────────────────────────────────────────────────────────────────┐   │
│   │                        Pi 官方开箱即用组件树 (直接复用)                        │   │
│   │   • UserMessageComponent: 柔和灰色底色消息气泡 (userMsgBg: #343541)            │   │
│   │   • AssistantMessageComponent: 流式 Markdown 增量渲染 + 动态思考折叠块         │   │
│   │   • ToolExecutionComponent: 圆角边框卡片 + 点阵 Spinner + 就地状态变绿折叠     │   │
│   │   • FooterComponent: 实时状态底栏 (Git 分支、模型标签、实时 Token、执行耗时)   │   │
│   └────────────────────────────────────────────────────────────────────────────────┘   │
│   ┌────────────────────────────────────────────────────────────────────────────────┐   │
│   │                      PythonKernelClient (stdio RPC 客户端)                     │   │
│   │   • 启动并管理子进程: uv run python -m my_coding_agent.rpc_server              │   │
│   │   • 双向管道: stdin 发送指令，stdout 监听事件流，stderr 捕获日志                │   │
│   └────────────────────────────────────────────────────────────────────────────────┘   │
└───────────────────────────────────────────▲────────────────────────────────────────────┘
                                            │
                                            │ 跨进程双向 stdio 协议 (JSON-RPC)
                                            │ • Requests: initialize, prompt, steer, abort...
                                            │ • Events: agent_start, message_update, tool...
                                            │
┌───────────────────────────────────────────▼────────────────────────────────────────────┐
│                 后端业务内核: packages/my-coding-agent (Python 3.12 / uv)              │
│                                                                                        │
│   ┌────────────────────────────────────────────────────────────────────────────────┐   │
│   │             RPC Server 门面 (my_coding_agent/rpc_server.py)                    │   │
│   │   • 解析 stdin JSON 请求，驱动 CodingAgent.run_stream(prompt)                  │   │
│   │   • 监听 CodingAgent 事件流，序列化为 JSON 推入 stdout                         │   │
│   │   • 隔离 stderr：所有 print() 与 logging 重定向到 stderr，绝不污染 RPC 数据流  │   │
│   └────────────────────────────────────────────────────────────────────────────────┘   │
│   ┌────────────────────────────────────────────────────────────────────────────────┐   │
│   │                       已完全建成的 4 大核心 Python 包                          │   │
│   │   • my-coding-agent: 6 大编码工具、文件并发锁、Turnkey MCP、Accept-on-Diff 门禁│   │
│   │   • my-agent-core: 纯函数 ReAct 循环、树状持久化会话、Cheap-First 上下文压缩   │   │
│   │   • my-agent-llm: Antigravity OAuth 专项直连、DeepSeek / OpenAI 流式推理       │   │
│   └────────────────────────────────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. 跨语言 stdio JSON-RPC 通信协议规范

协议采用单行以换行符 `\n` 分隔的 JSON 字符串（JSON Lines），与 LSP 和 MCP 的轻量模式完全对齐。

### 3.1 请求通道 (Shell → Kernel)

所有从前端发送至 Python 内核的请求均遵循标准 JSON-RPC 格式：

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "prompt",
  "params": {
    "text": "请帮我重构 calc.py"
  }
}
```

#### 支持的方法列表 (Methods)

| Method | 参数 (Params) | 语义说明 |
| :--- | :--- | :--- |
| `initialize` | `{"workspace": "/path", "model": "gemini-3.8-flash", "mode": "review"}` | 初始化内核实例与工作区环境 |
| `prompt` | `{"text": "..."}` | 提交新一轮用户提问，触发 `run_stream` |
| `steer` | `{"message": "..."}` | 实时注入即时转向纠偏指令（流式期间打字触发） |
| `followup` | `{"message": "..."}` | 追加排队追问任务 |
| `abort` | `{}` | 中止当前生成轮次（按 `Esc` 键触发） |
| `slash_command` | `{"command": "/model", "args": "deepseek-chat"}` | 执行内核级斜杠命令（如 `/undo`, `/compact`, `/model`） |
| `permission_response` | `{"request_id": "req_123", "decision": "approve" \| "reject"}` | 用户在前端卡片审查后批准或拒绝高危操作 |
| `shutdown` | `{}` | 优雅关闭内核（销毁 MCP 外部子进程并安全持久化会话） |

---

### 3.2 事件流通道 (Kernel → Shell)

Python 内核在 `run_stream` 期间通过 `stdout` 持续向前端推送事件通知。因为我们在 Phase 1 中严格按照 Pi 的架构设计了 `my_agent_core.events`，**Python 的事件与 Pi 的 `AgentEvent` 几乎 1:1 天然同构**！

```json
{
  "jsonrpc": "2.0",
  "method": "event",
  "params": {
    "type": "message_update",
    "message": {
      "role": "assistant",
      "content": [{"type": "text", "text": "正在重构..."}]
    },
    "assistantMessageEvent": {
      "type": "text_delta",
      "delta": "正在重构..."
    }
  }
}
```

#### 核心事件映射表 (Kernel Event → Pi TUI Component)

| Python 核心事件 (`my_agent_core.events`) | JSON RPC `event.type` | 前端组件行为 (`my-agent-shell`) |
| :--- | :--- | :--- |
| `AgentStart` | `agent_start` | 清空流式临时状态，开始新轮次，底栏进入 Busy 状态 |
| `MessageStart` (user) | `message_start` (user) | 挂载 `UserMessageComponent`（深灰底色气泡）上屏 |
| `MessageStart` (assistant) | `message_start` (assistant) | 实例化 `AssistantMessageComponent`，准备流式增量接收 |
| `MessageUpdate` (thinking) | `message_update` (thinking) | 调用 `assistantComponent.updateContent()`，动态展开思考块 |
| `MessageUpdate` (text) | `message_update` (text) | 驱动 `assistantComponent` 增量解析 Markdown 并刷新高亮 |
| `MessageEnd` | `message_end` | 固化当前助手消息，将思考块转为折叠状态 |
| `ToolExecutionStart` | `tool_execution_start` | 实例化 `ToolExecutionComponent`，呈现圆角边框与点阵旋转动效 |
| `ToolExecutionUpdate` | `tool_execution_update` | 更新工具调用参数与部分输出预览 |
| `ToolExecutionEnd` | `tool_execution_end` | 停止动画，卡片变绿/变红，呈现运行耗时，折叠结果 |
| `PermissionPrompt` | `permission_request` | 在输入框上方弹起 `ConfirmOverlay` 审查 Unified Diff 并等待回车确认 |
| `AgentEnd` | `agent_end` | 结束流式，更新 Footer（Token 统计与耗时），重新将输入焦点交还 `Editor` |

---

## 4. 前端组件与样式设计细节

### 4.1 直接复用 Pi 原厂的组件清单

我们将直接引入 Pi 官方在 `packages/coding-agent/src/modes/interactive/components/` 经过充分打磨的组件：

1. **`UserMessageComponent` (`user-message.ts`)**：
   - 带有 `userMsgBg`（`#343541`）淡色卡片底色；
   - 支持多行换行与长文本排版；
2. **`AssistantMessageComponent` (`assistant-message.ts`)**：
   - 内部包含 `Markdown` 渲染器与语法高亮（基于 `marked` 与语法分词）；
   - 内置可折叠的 **思考过程区块（Thinking Block）**：深灰圆角细线包裹，执行时显示动效，执行后默认折叠，按 `Ctrl+O` 随时展开/折叠；
3. **`ToolExecutionComponent` (`tool-execution.ts`)**：
   - 工具调用头部（如 `╭─ ⚙️ read src/calc.py ──────────────────╮`）；
   - 执行中微动效（点阵 Loader）；
   - 结果自动截断与语法高亮（如 `edit` 和 `write` 工具的 Unified Diff 彩色高亮）；
4. **`FooterComponent` (`footer.ts`)**：
   - 实时底栏展示：`📁 工作区` | `🌿 main` | `🤖 gemini-3.8-flash` | `📊 14.2k/1M` | `⏱️ 2.3s`；
5. **`EditorComponent` (`editor.ts` + `custom-editor.ts`)**：
   - 多行富文本输入、历史记录上下翻阅、`@` 文件模糊补全下拉气泡、中文 IME 硬件光标对齐。

---

## 5. 项目结构与目录规划

在 Monorepo 根目录下新增 `packages/my-agent-shell`：

```text
my-pi-agent/
├── packages/
│   ├── my-agent-shell/                # ⭐ 新增：基于 Pi-TUI 的纯前端表现层 (Node.js/TS)
│   │   ├── package.json               # 依赖: @earendil-works/pi-tui, chalk, marked
│   │   ├── tsconfig.json
│   │   ├── bin/
│   │   │   └── my-agent.js            # CLI 入口执行文件 (#/usr/bin/env node)
│   │   └── src/
│   │       ├── index.ts               # 主入口：初始化终端 TTY，启动 TuiMainScreen
│   │       ├── client.ts              # PythonKernelClient：管理 Python rpc_server 子进程
│   │       ├── protocol.ts            # RPC 请求/响应与 AgentEvent 类型定义
│   │       ├── theme/
│   │       │   ├── dark.json          # 移植 Pi 原厂 dark 配色
│   │       │   └── theme.ts           # 颜色与样式管理器
│   │       └── components/            # ⭐ 直接复用 Pi 核心组件
│   │           ├── user-message.ts
│   │           ├── assistant-message.ts
│   │           ├── tool-execution.ts
│   │           ├── footer.ts
│   │           └── confirm-overlay.ts
│   │
│   ├── my-coding-agent/               # Python 业务层
│   │   └── src/my_coding_agent/
│   │       ├── rpc_server.py          # ⭐ 新增：stdio JSON-RPC 服务端门面
│   │       ├── agent.py               # 原有 CodingAgent (保持纯无头)
│   │       └── ...
│   │
│   ├── my-agent-core/                 # Python 框架微内核
│   ├── my-agent-llm/                  # Python 模型直连层
│   └── my-agent-tui/                  # Python 旧版终端 (保留作为纯 Python 环境下的 headless/fallback)
```

---

## 6. 进程生命周期与异常安全性 (Resilience & Lifecycle)

1. **子进程生命周期绑定 (Tied Lifecycle)**：
   - 前端 Shell 在启动时通过 `child_process.spawn("uv", ["run", "python", "-m", "my_coding_agent.rpc_server", ...])` 唤起 Python 内核；
   - 监听 Python 进程的 `exit` 与 `error` 事件；若 Python 意外崩溃，前端弹出明确的错误卡片提示；
   - 前端退出（无论是用户按 `Ctrl+D`、输入 `/exit` 还是点击关闭终端窗口）时，向 Python 发送 `shutdown` 请求，并由 Node 的 `process.on("exit")` 保证 `SIGTERM`/`SIGKILL` 彻底杀死子进程，绝无孤儿僵尸进程。
2. **流隔离保证 (Stream Cleanliness)**：
   - Python 端的 `stdout` 严格受控，仅允许 `rpc_server.py` 输出格式化的 JSON Lines；
   - Python 内所有第三方库日志、调试信息、未捕获异常 Traceback 均重定向至 `stderr`；
   - 前端捕获 `stderr` 并写入本地临时日志文件（`.my_agent_core/kernel.log`），杜绝因第三方库非法 print 导致 TUI 协议解析失败。
3. **Esc 即时打断与动态 Steering 线程安全**：
   - 用户按 `Esc`：前端捕获键盘事件，立刻向 Python stdin 写入 `{"method": "abort"}`，Python 收到立即触发 `agent.abort()` 取消当前轮次；
   - 用户在流式生成期间直接敲字按回车：前端向 Python 写入 `{"method": "steer", "params": {"message": line}}`，Python 压入 `MessageQueue`，实现即时动态纠偏。

---

## 7. 实施路线图 (Implementation Phases)

- **Phase 1: Python 端 stdio JSON-RPC 服务端门面 (`rpc_server.py`)**：
  - 在 `my-coding-agent` 中实现 `rpc_server.py`，接收 JSON-RPC 请求，将 `run_stream` 的 `AgentEvent` 格式化输出为 JSON Lines；
  - 编写离线单元测试验证双向协议的序列化与反序列化。
- **Phase 2: 前端包骨架与 RPC 客户端搭建 (`packages/my-agent-shell`)**：
  - 初始化 `package.json`，安装 `@earendil-works/pi-tui`；
  - 实现 `client.ts`，打通对 Python `rpc_server` 的生命周期管理与事件流解析。
- **Phase 3: Pi 原厂组件组装与主题挂载**：
  - 移植 `dark.json` 配色表；
  - 接入 `AssistantMessageComponent`、`ToolExecutionComponent`、`UserMessageComponent`、`FooterComponent` 与 `Editor`；
  - 组装为完整的 `TuiMainScreen` 交互界面。
- **Phase 4: 全链路真机打通与端到端演练**：
  - 测试实时 Markdown 流式吐字、思考过程折叠展开、工具圆角卡片、Esc 取消与打字 Steering。

---

## 8. 自我审查对照表 (Self-Review Checklist)

1. **占位符检查**：文档中无任何 TBD/TODO，所有协议结构、组件职责、通信机制均有明确定义。
2. **架构一致性**：保持 Python 业务层 100% 纯无头，前端仅负责视图渲染与终端事件分发，职责界限分明。
3. **复用最大化**：完全复用 Pi 原厂成熟的 `@earendil-works/pi-tui` 与交互卡片，彻底根除重复造轮子风险。
