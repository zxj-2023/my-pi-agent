# 前后端通信协议与内核桥接规范 (`my_coding_agent.rpc_server`)

- **定位**：Python 运行时内核与独立前端表现层之间的通信桥梁 (`src/my_coding_agent/rpc_server.py`, `tui/src/bridge/`)
- **协议标准**：标准 stdio JSON-RPC 2.0 规范（无网络端口开销、跨平台高可靠）
- **核心能力**：双向流式通知、会话树 DAG 分支操作、全量 Token 与成本动态核算、Prompt Cache 命中率（`CH%`）

---

## 一、架构全景与 stdio 桥接模型

为实现 Python 后端纯业务逻辑与 TypeScript 前端独立渲染终端的彻底解耦，系统采用标准输入输出管道（stdio）构建 JSON-RPC 2.0 桥接协议：

```text
+-------------------------------------------------------------+
|                 TypeScript 独立终端 (TUI)                    |
|        InteractiveMode ➔ KernelBridge ➔ PythonKernelClient  |
+-------------------------------------------------------------+
                              ▲
                              │ stdin / stdout (JSON-RPC 2.0 单行文本流)
                              ▼
+-------------------------------------------------------------+
|               Python 内核服务端 (rpc_server.py)             |
|          CodingAgent ➔ ReAct 微内核 ➔ Session DAG 存储      |
+-------------------------------------------------------------+
```

### 1. 通信规约

- **传输层**：标准输入（stdin）与标准输出（stdout），每条 JSON 载荷以单个换行符（`\n`）严格界定；
- **编码格式**：全链路统一为 UTF-8；
- **标准错误**：stderr 专用于底层调试与关键诊断追踪，绝不掺杂业务协议数据。

---

## 二、JSON-RPC 2.0 方法清单与协议规范

### 1. 核心请求与命令方法 (Request / Response)

| 方法名 | 入参 (Params) | 返回结果 (Result) | 业务行为与约束 |
| :--- | :--- | :--- | :--- |
| `prompt` | `{"text": string}` | `{"status": "ok"}` | 发起用户提问，触发 ReAct 微内核调度，后续事件以 `event` 异步推送 |
| `abort` | `{}` | `{"status": "aborted"}` | 中断当前正在运行的模型流式或工具进程 |
| `model_list` | `{}` | `{"models": [...], "current": "..."}` | 动态拉取各已配置 Provider 的真实模型目录（含 4 小时磁盘缓存） |
| `model_switch` | `{"model": string}` | `{"status": "ok", "current": "..."}` | 动态热切换当前使用的底层模型与 Provider |
| `thinking_set` | `{"level": string}` | `{"status": "ok", "level": "..."}` | 设定思考预算深度，内部根据模型家族能力自动夹逼合规值 |
| `session_list` | `{}` | `{"sessions": [...]}` | 获取当前工作区的所有历史会话元数据（含消息数、更新时间） |
| `session_resume` | `{"session_id": string}` | `{"status": "ok", "messages": [...]}` | 恢复指定会话历史，回传完整消息历史供前端视口平滑重建 |
| `session_tree` | `{}` | `{"nodes": [...], "tree": [...]}` | 获取当前会话的 DAG 分支图、根节点与父子指针关系 |
| `session_fork` | `{"entry_id": string}` | `{"status": "ok", "new_session_id": "..."}` | 从指定历史消息节点分叉出全新平行探索会话分支 |
| `session_clone` | `{}` | `{"status": "ok", "new_session_id": "..."}` | 100% 完整克隆当前会话的全部消息与快照副本 |
| `session_delete` | `{"session_id": string}` | `{"status": "ok"}` | 删除指定的废弃历史会话（**拦截删除当前正在使用的活跃会话**） |
| `session_compact` | `{"instructions": string}` | `{"summary": "...", "tokens_before": N, "tokens_after": M}` | 触发上下文廉价压缩与摘要沉淀 |
| `session_stats` | `{}` | `{session_file, messages, tokens, cost, ...}` | 获取 1:1 对标 Pi 原厂的详细指标统计报表 |

### 2. 状态码与异常安全保障

- `-32600`：Invalid Request（JSON 序列化失败或入参结构非法）；
- `-32601`：Method Not Found（未识别的远端调用）；
- `-32000`：Server Error（工具执行异常，返回结构化诊断文本）；
- `-32005`：Active Session Conflict（拒绝删除当前正在使用的活跃会话）。

---

## 三、异步流式事件体系 (Notification)

在处理 `prompt` 期间，Python 内核以 `{"jsonrpc": "2.0", "method": "event", "params": {...}}` 向前端高频广播 ReAct 内部阶段：

| 事件类型 (`params.type`) | 关键载荷字段 | 前端 TUI 交互映射 |
| :--- | :--- | :--- |
| `agent_start` | `system_prompt`, `user_input` | 激活输入框顶部边框转动动效 `── ⠸ Working ──` |
| `turn_start` | `iteration` | 启动单轮迭代计时与指示器刷新 |
| `message_start` | `role="assistant"` | 在视口挂载 `AssistantMessageComponent` |
| `message_update` | `delta`, `reasoning_delta` | 累加正文文本与思考内容，实时高亮打字 |
| `tool_execution_start` | `toolCallId`, `toolName`, `args` | 挂载 `ToolExecutionComponent`，呈现参数折叠卡片 |
| `tool_execution_update` | `toolCallId`, `partialResult` | 增量流式更新工具输出（如 bash 实时执行日志） |
| `tool_execution_end` | `toolCallId`, `result`, `isError` | 标记工具完成，停止旋转，计算实际耗时 |
| `message_end` | `usage`, `contextWindow` | 固化本条消息，更新底部 Footer 上下文占用比例 |
| `turn_end` | `usage` | 结束当前单轮，触发 Footer 统计更新 |
| `agent_end` | `stop_reason`, `usage` | 停止边框旋转，安全释放光标至编辑区，进入待命态 |
| `context_compacted` | `tokensBefore`, `tokensAfter` | 视口呈现可展开的 `[compaction]` 摘要卡片 |

---

## 四、全量 Token 与成本动态核算公式

为了 100% 对齐 Pi 原厂的财务级指标透明度，服务端在 `_compute_session_usage` 中实现了一套精准的 Prompt Cache 与多阶梯成本核算引擎：

```text
              Native Provider API 响应 (OpenAI / Anthropic / Antigravity)
                                         │
        ┌────────────────────────────────┼────────────────────────────────┐
        ▼                                ▼                                ▼
  cache_read (命中读取)           cache_write (写入缓存)            uncached_input (未缓存输入)
        │                                │                                │
        └────────────────────────────────┼────────────────────────────────┘
                                         ▼
                      总输入 Token = uncached_input + cache_read
```

### 1. 缓存命中率算法 (`CH%`)

$$\text{Cache Hit Rate (CH)} = \frac{\text{cache\_read}}{\text{uncached\_input} + \text{cache\_read} + \text{cache\_write}} \times 100\%$$

当会话包含有效缓存读取时，底部 Footer 与 `/session` 命令自动显示 `CH: XX.X%`，帮助开发者直观感知提示词缓存节约的开销。

### 2. 真实成本分级费率模型 (Cost Breakdown)

支持依据当前活跃模型家族（GPT-4o、Claude 3.7 Sonnet、DeepSeek V3/R1、Gemini 2.5 Pro）应用差分费率：

$$\text{Cost} = (\text{uncached\_input} \times P_{\text{in}}) + (\text{cache\_read} \times P_{\text{hit}}) + (\text{cache\_write} \times P_{\text{write}}) + (\text{output} \times P_{\text{out}})$$

确保用户在本地终端中随时掌握精准到毫厘的真实 API 账单。
