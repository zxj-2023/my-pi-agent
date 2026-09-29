# ACP (Agent Client Protocol) 集成规范 (`my_acp_agent`)

- **定位**：把 `my_coding_agent` 产品层包装为符合 ACP 规范的 Agent，供 Zed / Neovim 等编辑器作为外部 Agent 驱动
- **协议标准**：Agent Client Protocol（Zed Industries 主导的开放标准），基于 JSON-RPC 2.0 over stdio
- **官方 SDK**：`agent-client-protocol`（Python），版本 `>=0.12.1`
- **核心能力**：会话生命周期、流式消息与思考块、工具调用卡片、**反向权限审批**、会话模式切换

---

## 一、为什么需要这一层

`my_coding_agent` 已经有一套自研的私有 JSON-RPC 协议（`rpc_server.py` + `tui/src/protocol.ts`），
但那套协议是**单向**的：服务端只能应答请求、广播通知，无法主动向客户端发起请求。

ACP 的关键差异在于**双向**：Agent 可以在执行工具前向编辑器发起 `session/request_permission`
并等待用户裁决。这正是 `PermissionGate` 早已预留、但 TUI 链路从未接通的 `confirm_callback` 扩展点。

因此本层的定位是**纯适配**，不重复实现任何 Agent 能力：

```text
编辑器 (Zed / Neovim)
        ⇅  ACP: JSON-RPC 2.0 over stdio
src/my_acp_agent/          ← 本层：协议翻译 + 生命周期编排
        ↓  直接调用（同进程）
src/my_coding_agent/       ← 复用：CodingAgent / 7 大工具 / PermissionGate
        ↓
src/my_agent_core/         ← 复用：ReAct 微内核 / 会话树 / 压缩管线
```

**内核层零改动**。ACP 适配层与 `rpc_server.py` 是平级的两个传输层实现。

---

## 二、模块结构

```text
src/my_acp_agent/
├── __init__.py          导出 AcpAgent
├── agent.py             AcpAgent —— ACP Agent 协议实现
├── events.py            内核事件 → session/update 的纯函数翻译
├── permissions.py       PermissionGate ↔ session/request_permission 桥接
└── server.py            stdio 入口（python -m my_acp_agent.server）
```

### 2.1 `events.py` —— 事件翻译层

`my_agent_core` 广播的是一等公民事实事件（frozen dataclass），ACP 侧需要的是
`session/update` 通知。映射关系如下：

| 内核事件 | ACP 更新 | 说明 |
| :--- | :--- | :--- |
| `MessageUpdate`（正文增量） | `agent_message_chunk` | 流式正文 |
| `MessageUpdate`（`reasoning_content`） | `agent_thought_chunk` | 思考过程折叠块 |
| `ToolExecutionStart` | `tool_call` | 工具卡片创建，带 `kind` / `locations` |
| `ToolExecutionEnd` | `tool_call_update` | 状态 `completed` / `failed` + 结果文本 |
| `MessageEnd` | — | 仅用于累加 usage，不产生通知 |
| `AgentEnd` | — | 由 `PromptResponse.stop_reason` 承载 |

工具类别映射（决定编辑器侧图标与 UI 处理）：

| 工具 | ACP `ToolKind` |
| :--- | :--- |
| `read` / `ls` | `read` |
| `write` / `edit` | `edit` |
| `bash` | `execute` |
| `grep` / `find` | `search` |

工具结果超过 `MAX_RESULT_CHARS`（8000 字符）时截断，避免超大输出撑爆 JSON-RPC 帧。

### 2.2 `permissions.py` —— 反向审批桥接

```text
PermissionGate.confirm_callback
        ↓
AcpPermissionBridge.confirm()
        ↓
conn.request_permission(...)  →  编辑器弹窗
        ↓
allow_once / allow_always / reject_once / reject_always
```

- `allow_always` / `reject_always` 按**会话 + 工具名**记忆，避免同一会话内反复弹窗；
- 连接未就绪时保守放行（与 `PermissionGate` 无回调时的既有语义一致）；
- 反向请求抛异常（编辑器断连/取消）时**保守拒绝**，避免无人值守下静默执行写操作。

### 2.3 `agent.py` —— 协议实现

一个 ACP 会话对应一个 `CodingAgent` 实例，`session_id` **直接复用** my-pi-agent 的会话 UUID。
因此会话文件、`/tree` 分支、`--continue` 续接与 TUI 侧完全互通 —— 同一个项目在
Zed 里和终端里看到的是同一批会话。

已实现的 ACP 方法：

| ACP 方法 | 行为 |
| :--- | :--- |
| `initialize` | 声明能力：`loadSession` + `sessionCapabilities.list` |
| `session/new` | 创建会话并落盘（保证 `session/list` 立即可见） |
| `session/load` | 加载历史会话并回放消息给编辑器 |
| `session/list` | 列出当前工作区历史会话 |
| `session/set_mode` | 切换权限模式 |
| `session/prompt` | 驱动 `CodingAgent.run_stream()` 并翻译事件流 |
| `session/cancel` | 协作式中断当前生成 |
| `session/close` | 释放会话与 MCP 连接 |

会话模式与 `PermissionGate` 的对应：

| ACP mode | PermissionGate mode | 行为 |
| :--- | :--- | :--- |
| `review` | `review` | 写操作前逐次请求审批（默认） |
| `autonomous` | `autonomous` | 自动放行写操作 |
| `strict` | `strict` | 只读，拒绝一切写操作 |
| `yolo` | `autonomous` | 完全放行（门禁内部归一化） |

---

## 三、运行方式

### 3.1 直接运行（Python）

```bash
uv run python -m my_acp_agent.server --workspace /path/to/project
```

参数：

| 参数 | 说明 |
| :--- | :--- |
| `-w, --workspace <dir>` | 工作区目录（默认当前目录） |
| `-m, --model <model>` | 指定生效模型 |
| `--mode <mode>` | 权限安全模式（默认读取用户配置，回落 `review`） |
| `--debug` | 输出调试日志到 stderr |

### 3.2 通过 npm 启动器

```bash
node bin/my-agent-acp.js --workspace /path/to/project
# 或全局安装后
my-pi-agent-acp --workspace /path/to/project
```

`bin/my-agent-acp.js` 只负责定位 Python 运行时（探测顺序与 TUI 启动器一致：
`MY_PI_AGENT_PYTHON` > `uv` > `python3` > `python` > `uv` 兜底），
随后以 **stdio 全透传**（`stdio: "inherit"`）把 stdin/stdout 直接交给 Python 内核 ——
Node 层不做任何缓冲或改写，保证 ACP 的 JSON-RPC 帧原样通过。

### 3.3 Zed 配置

在 Zed 的 `settings.json` 中加入：

```json
{
  "agent_servers": {
    "my-pi-agent": {
      "command": "node",
      "args": ["/absolute/path/to/my-pi-agent/bin/my-agent-acp.js"],
      "env": {}
    }
  }
}
```

若已全局安装 npm 包，可简化为：

```json
{
  "agent_servers": {
    "my-pi-agent": {
      "command": "my-pi-agent-acp",
      "args": [],
      "env": {}
    }
  }
}
```

---

## 四、前置条件

ACP 会话同样需要模型凭据。若未配置，`session/new` 会返回 ACP 标准认证错误
（`code: -32000, message: "Authentication required"`），并在 `data.hint` 中给出指引。

配置方式二选一：

1. 运行 `my-pi-agent` 并执行 `/login <provider> <key>`，凭据写入 `~/.my-pi-agent/auth.json`；
2. 设置环境变量（`DEEPSEEK_API_KEY` / `OPENAI_API_KEY` / `ANTHROPIC_API_KEY`）。

---

## 五、测试

```bash
uv run python -m pytest tests/acp -q
```

测试分四层：

| 文件 | 覆盖范围 |
| :--- | :--- |
| `test_events.py` | 事件翻译纯函数（工具类别、标题、路径解析、截断） |
| `test_permissions.py` | 审批桥接 + 与 `PermissionGate` 的集成 |
| `test_agent.py` | 协议方法（注入脚本化 LLM，无网络依赖） |
| `test_wire.py` | **真实 JSON-RPC 双端对接**（内存 Transport，验证编解码与路由） |

`test_wire.py` 用内存 `Transport` 把 `AcpAgent` 与官方 `ClientSideConnection`
背靠背接起来，跑完整链路，其中包含端到端验证「编辑器拒绝 → 写工具被拦截 → 文件不落盘」。

另有端到端冒烟脚本（需要真实模型凭据）：

```bash
uv run python scripts/acp_smoke.py
```

---

## 六、已知边界

以下 ACP 能力**尚未实现**，如需接入需改动工具层而非适配层：

- **`fs/read_text_file` / `fs/write_text_file`**：Agent 仍自行读写文件，未走编辑器托管。
  这意味着编辑器侧未保存的缓冲区内容 Agent 看不到。
- **`terminal/*`**：`bash` 工具自行创建进程，未使用编辑器托管终端。
- **图片 / 音频 prompt 块**：`PromptCapabilities` 声明为 `false`，非文本块被忽略。
- **`session/fork` / `session/resume`**：协议中标记为 unstable，未接入。
  内核本身具备 `/fork` 能力，后续可低成本补齐。
