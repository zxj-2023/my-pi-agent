# 前后端通信协议与内核桥接规范 (`my_coding_agent.rpc_server`)

- **定位**：Python 运行时内核与独立前端表现层之间的通信桥梁 (`src/my_coding_agent/rpc_server.py`, `my-pi-tui/src/bridge/`)
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

服务端共注册分发了 30 个强类型 RPC 业务处理方法，按功能分为 6 大领域：

#### (1) 通信生命周期与流程控制

| 方法名 | 入参 (Params) | 返回结果 (Result) | 业务行为与约束 |
| :--- | :--- | :--- | :--- |
| `initialize` | `{"workspace"?: string, "model"?: string, "thinking"?: string, "mode"?: string, "continue"?: boolean, "new_session"?: boolean, "name"?: string}` | `{"status": "ok", "workspace": "...", "model": "...", "provider": "...", "context_window": N, "usage": {...}, "thinking_level": "...", "session_id": "...", "session_file": "...", "session_name": "...", "messages": [...]}` | 双端协议握手，同步工作区与默认运行时上下文 |
| `shutdown` | `{}` | `{"status": "ok"}` | 优雅终止 Python 内核，妥善释放子进程与会话文件锁 |
| `prompt` | `{"text": string, "streamingBehavior"?: "steer" \| "followUp"}` | `{"status": "completed"}` 或 `{"status": "ok", "action": "steered"}` | 发起用户提问，微内核互斥锁保护；若已有活跃任务在执行且指定 `steer`，自动合流即时转向 |
| `steer` | `{"message"?: string, "prompt"?: string, "text"?: string}` | `{"status": "ok"}` | 在当前 Agent 运行轮次中即时插话注入转向指令（支持灵活键名） |
| `followup` | `{"message"?: string, "prompt"?: string, "text"?: string}` | `{"status": "ok"}` | 在当前任务排队队列末尾追加排程输入 |
| `clear_queue` | `{}` | `{"cleared": true, "count": number}` | 清空当前会话中所有排队待发的干预消息（包含 Steering 与 Follow-up） |
| `abort` | `{}` | `{"status": "ok"}` | 协作式中断当前正在运行的模型流式生成或工具执行进程 |

#### (2) 会话管理与 DAG 分支漫游

| 方法名 | 入参 (Params) | 返回结果 (Result) | 业务行为与约束 |
| :--- | :--- | :--- | :--- |
| `session_new` | `{}` | `{"status": "ok", "session_id": "...", "session_file": "...", "messages": []}` | 在当前工作区会话分区创建全新的空白会话 |
| `session_name` | `{"name": string}` | `{"name": "...", "status": "ok"}` | 重命名当前活跃会话名称 |
| `session_list` | `{}` | `{"sessions": [...]}` | 获取当前工作区的所有历史会话元数据（含消息数、更新时间） |
| `session_resume` | `{"session_id": string}` | `{"status": "ok", "session_id": "...", "session_name": "...", "session_file": "...", "messages": [...]}` | 恢复指定会话历史，回传完整消息快照供前端视口平滑重建 |
| `session_delete` | `{"session_id": string}` | `{"status": "ok", "deleted": string}` | 删除指定的废弃历史会话（**拦截删除当前正在使用的活跃会话**） |
| `session_history` | `{"session_id"?: string}` | `{"status": "ok", "session_id": "...", "session_name": "...", "messages": [...]}` | 检索指定会话或当前会话的线性消息列表 |
| `session_stats` | `{"session_id"?: string}` | `{sessionId, sessionFile, totalMessages, tokens, cost, ...}` | 获取 1:1 对标 Pi 原厂的财务级指标详细统计报表 |
| `session_compact` | `{"instructions"?: string}` | `{"summary": "...", "tokens_before": N, "tokens_after": M}` | 触发廉价上下文压缩与 LLM 摘要沉淀 |
| `session_tree` | `{"session_id"?: string}` | `{"nodes": [...], "tree": [...]}` | 获取当前会话完整的 DAG 分支图、节点状态与父子拓扑 |
| `session_branch` | `{"node_id": string}` | `{"status": "ok", "messages": [...]}` | 将当前会话指针切换回溯到历史任一节点状态 |
| `session_fork` | `{"entry_id": string}` | `{"status": "ok", "new_session_id": "...", "session_file": "...", "messages": [...]}` | 从指定历史消息节点分叉开辟独立平行探索会话 |
| `session_clone` | `{}` | `{"status": "ok", "new_session_id": "...", "session_file": "...", "messages": [...]}` | 100% 完整克隆当前会话消息与快照建立全新副本 |

#### (3) 模型调度与思考预算

| 方法名 | 入参 (Params) | 返回结果 (Result) | 业务行为与约束 |
| :--- | :--- | :--- | :--- |
| `models_list` | `{}` | `{"models": [...], "configured_providers": [...]}` | 动态拉取各已配置 Provider 的真实模型目录（含 4 小时磁盘缓存） |
| `model_switch` | `{"model": string, "provider"?: string}` | `{"status": "ok", "model": "...", "provider": "..."}` | 动态热切换当前使用的底层大模型与 Provider |
| `thinking_set` | `{"level": string, "persist"?: boolean}` | `{"status": "ok", "level": string}` | 设定思考预算深度，内部根据模型家族能力自动夹逼合规值 |

#### (4) 认证凭据与项目信任

| 方法名 | 入参 (Params) | 返回结果 (Result) | 业务行为与约束 |
| :--- | :--- | :--- | :--- |
| `login` | `{"provider": string, "key": string}` | `{"status": "ok", "message": "..."}` | 安全保存提供商凭据至 `~/.my-pi-agent/auth.json` |
| `auth_logout` | `{"provider": string}` | `{"status": "ok", "provider": "..."}` | 从凭据中心注销并移除指定提供商的凭据信息 |
| `trust_set` | `{"path"?: string, "trusted": boolean, "parent"?: boolean}` | `{"status": "ok", "path": string, "trusted": boolean, "decision": string}` | 记录或更新对特定工作区路径的脚本执行信任授权 |

#### (5) Shell 宏展开、调试快照与资源热重载

| 方法名 | 入参 (Params) | 返回结果 (Result) | 业务行为与约束 |
| :--- | :--- | :--- | :--- |
| `shell_exec` | `{"command": string, "exclude_from_context"?: boolean, "timeout"?: number}` | `{"status": "ok", "output": string, "exit_code": number}` | 前端触发本地 Shell 命令执行（区分静默与上下文注入） |
| `macro_expand` | `{"text": string, "skills_dir"?: string, "prompts_dir"?: string}` | `{"status": "ok", "text": string, "expanded": boolean, "expanded_text": string}` | 服务端执行 `MacroEngine` 对输入行宏（`/skill:`, `/<template>`）的即时展开 |
| `resource_reload` | `{}` | `{"status": "ok", "message": "..."}` | 动态重新扫描并热重载本地 Skills、Prompts 与 Templates 资源 |
| `debug_dump` | `{"output_path"?: string}` | `{"status": "ok", "dump_file": string, "log_file"?: string, "events_file"?: string, "snapshot": {...}}` | 导出运行时内存快照并返回当前活跃会话的调试日志与事件流路径 |

#### (6) 配置读取与设置

| 方法名 | 入参 (Params) | 返回结果 (Result) | 业务行为与约束 |
| :--- | :--- | :--- | :--- |
| `settings_get` | `{"key"?: string}` | `{"settings": {...}}` | 获取合并后的级联配置快照或指定配置键值 |
| `settings_set` | `{ [key: string]: any, "scope"?: "global" \| "project" }` | `{"status": "ok", "updated": {...}, "settings": {...}}` | 动态更新运行时配置（平铺键值如 `{"default_model": "..."}`）并同步持久化至用户主目录 |

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
