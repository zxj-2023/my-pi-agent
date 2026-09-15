# Pi 原厂交互层 (TUI) 移植与架构解耦二次开发设计规范

- **日期**：2026-09-15
- **状态**：已批准 (Approved)
- **范围**：`tui/` 模块交互层重构与 Python RPC 桥接驱动
- **设计者**：Pi Agent & User

---

## 一、背景与设计目标

### 1.1 背景与核心痛点

在 `my-pi-agent` 当前架构中，用户曾尝试在 `tui/src/app.ts` 单文件中手工逆向并复刻 Pi 原厂的终端交互界面。然而，构建完整的终端 Agent TUI 涉及极其繁琐的细节，包括：

- ANSI 字符序列处理、终端光标与焦点管理；
- 视口动态高度重算与历史消息滚动同步（滚动错位、闪烁、重叠）；
- 思维链（Thinking）折叠与流式 Markdown 高亮交替输出；
- 全屏动态选择器（`/model`, `/session`, `/tree` 等）的视口抽换与键盘按键冲突处理。

自研代码随着各种边界情况修复迅速膨胀至 1800+ 行单体，结构臃肿且体验漏洞频出。而实际上，Pi 原厂（`@earendil-works/pi-coding-agent`）内部的 `modes/interactive/` 已经过长期打磨，拥有 100% 像素级保真、流畅的快捷键与视口管理能力。

### 1.2 核心目标 (Goals)

1. **100% 原厂交互保真**：完整引入 Pi 原厂 `modes/interactive` 模块源码及相关组件（如 `AssistantMessageComponent`、`ToolExecutionComponent`、`FooterComponent`、全套 Selectors、`chat-viewport`、`tui-renderer`），消除自研手写带来的各种边缘 Bug。
2. **三层分耦架构**：
   - **UI 呈现层**：100% 原厂无损，负责绘制与用户按键；
   - **桥梁驱动层 (`KernelBridge`)**：负责将用户动作转为 Python JSON-RPC 2.0，并将 Python 流式事件转为标准 UI 事件；
   - **内核运行层**：维持 Python 后端 (`my_coding_agent.rpc_server`) 逻辑完整与纯粹。
3. **彻底铲除单体债务**：废弃并替换 1800 行手写单体 `tui/src/app.ts`，代码模块化、高内聚、低耦合。
4. **自主可控与二次开发就绪**：源码全部纳入 `tui/src/` 中，不再受制于第三方黑盒封装，方便后续自由添加新功能或专属状态指示器。

### 1.3 非目标 (Non-Goals)

- 本次重构不修改 Python 内核业务逻辑（`src/my_coding_agent/` 与 `src/my_agent_core/`），Python 端已就绪的全套 RPC 协议保持稳定。
- 不构建 Web 浏览器界面，专注于 CLI/TUI 终端交互体验。

---

## 二、目录结构与架构分层 (Directory Structure & Architecture)

重构后 `tui/src/` 的清晰目录布局如下：

```text
tui/src/
├── index.ts                       # CLI 入口与命令行参数解析（--model, --resume, --thinking 等）
├── bridge/                        # 【桥梁层：连接 UI 与 Python RPC】
│   ├── kernel-bridge.ts           # 充当轻量 Session Adapter，承接 UI 交互动作并转发给 Python
│   ├── event-translator.ts        # 将 Python JSON-RPC 2.0 事件流转译为标准化 AgentSessionEvent
│   └── client.ts                  # 管理 PythonKernelClient 子进程生命周期与 stdio JSON-RPC 通信
├── interactive/                   # 【Pi 原厂交互层：100% 保真与细腻体验】
│   ├── interactive-mode.ts        # 原厂主交互控制器（将内部 session 依赖改为接入 KernelBridge）
│   ├── chat-viewport.ts           # 原厂滚动视口管理器（处理动态内容高度计算与平滑滚动）
│   ├── tui-renderer.ts            # 原厂终端双缓冲渲染器（CSI 2026 同步输出，零闪烁）
│   ├── components/                # 原厂全套成熟组件
│   │   ├── assistant-message.ts   # 支持思维链折叠、流式代码高亮与错误渲染
│   │   ├── tool-execution.ts      # 工具调用动态加载圈、结果输出折叠、耗时计算
│   │   ├── user-message.ts        # 用户气泡与引用显示
│   │   ├── footer.ts              # 底部 Token 进度条、上下文百分比、耗时与模型显示
│   │   ├── dynamic-border.ts      # 智能动态边框与状态颜色映射
│   │   ├── model-selector.ts      # 模型选择器（支持模糊搜索与 Tab 作用域切换）
│   │   ├── session-selector.ts    # 会话选择器（历史记录检索与指标显示）
│   │   ├── tree-selector.ts       # 分支树选择器（DAG 拓扑可视化导航）
│   │   ├── thinking-selector.ts   # 思考预算等级选择器
│   │   ├── settings-selector.ts   # 设置项切换选择器
│   │   ├── login-dialog.ts        # 凭据绑定对话框
│   │   └── logout-selector.ts     # 凭据清除选择器
│   └── theme/                     # 原厂 24-bit TrueColor 主题体系与语法着色器
└── utils/                         # 原厂底层支持工具（ANSI 长度计算、视觉截断、剪贴板等）
```

---

## 三、事件流动与数据协议映射 (Data Flow & Event Mapping)

### 3.1 用户输入与控制链路 (UI -> Python)

```text
[ 用户键盘输入 / 快捷键 ]
        │
        ▼
[ interactive-mode.ts ] (捕获回车提交、Esc 中断、Ctrl+O 展开)
        │  bridge.prompt(text) / bridge.abort() / bridge.steer(text)
        ▼
[ KernelBridge ] (封装为 JSON-RPC 2.0 请求)
        │  {"method": "prompt", "params": {"text": "..."}}
        ▼
[ PythonKernelClient ] (stdio 写管道)
        │
        ▼
[ Python rpc_server.py ] (协程接收，调度 agent.run_stream(text))
```

### 3.2 流式增量装配与事件映射 (Python -> UI)

Python 服务端在 `run_stream` 过程中推送 `event` 通知。由 `EventTranslator` 负责组装与标准化：

| Python 事件 | 参数与有效载荷 | 转译映射为标准 UI 行为 / AgentSessionEvent |
| :--- | :--- | :--- |
| `agent_start` | `system_prompt`, `user_input` | 清空 pending 队列，初始化 assistant 消息渲染组件 |
| `turn_start` | `iteration` | 触发工作态指示器旋转（Working Indicator） |
| `message_start` | `role="assistant"` | 挂载 `AssistantMessageComponent`，开始流式监听 |
| `message_update` | `delta` (正文增量) | 追加至正文块 `content: [{type: "text", text: "..."}]`，流式打字与语法高亮 |
| `message_update` | `reasoning_delta` (思考增量) | 追加至思维块 `content: [{type: "thinking", thinking: "..."}]`，折叠统计字符数 |
| `tool_execution_start` | `toolCallId`, `toolName`, `args` | 挂载 `ToolExecutionComponent`，呈现转动加载状态与参数卡片 |
| `tool_execution_update` | `toolCallId`, `partialResult` | 更新工具执行中间状态与局部输出 |
| `tool_execution_end` | `toolCallId`, `result`, `isError` | 标记工具完成，停止加载圈，计算耗时，超长结果进行视觉截断 |
| `message_end` | `stopReason` | 结束流式状态，固化消息块，重设光标至编辑区 |
| `turn_end` | 无 | 结束本轮迭代，触发 Footer 统计指标重绘 |
| `agent_end` | `stop_reason` | 整体任务收尾，UI 进入完全 Idle 待机状态 |

### 3.3 中断控制 (Abort & Steer)

- 当用户在流式生成期间按下 `Esc` 或 `Ctrl+C` 时：
  1. `interactive-mode` 拦截信号，本地立即将活跃的 Spinner 标记为停止；
  2. `KernelBridge.abort()` 异步发送 `{"method": "abort"}` 到 Python；
  3. Python 后端取消当前未完成的流式协程，触发状态机回到 Idle 并回传中断事件；
  4. UI 恢复 Editor 焦点，不破坏上下文历史。

---

## 四、命令系统与交互选择器对接 (Slash Commands & Selectors)

### 4.1 本地命令与远端命令分流

1. **纯前端即时命令**：
   - `/clear`：直接清空 `chat-viewport` 的渲染节点，瞬时重绘，无需通过网络；
   - `/help`：本地弹出原厂快捷键与可用斜杠命令说明清单。
2. **数据驱动型选择器命令**：
   - `/model` (Ctrl+M)：通过 `KernelBridge.listModels()` 获取可用模型，在 `ModelSelectorComponent` 中展示；用户按 Tab 切换“已配置 (Configured)”与“全部候选 (All)”；选定后向 Python 发送 `model_switch`；
   - `/session` (Ctrl+R)：通过 `KernelBridge.listSessions()` 获取历史列表并按更新时间倒序呈现；回车后向 Python 发送 `session_resume`，清空视口并按拓扑重播消息；
   - `/tree`：通过 `KernelBridge.getTree()` 渲染 DAG 分支树，支持导航并向 Python 发送 `session_branch` 分支切换；
   - `/thinking`：弹出思考等级列表 (`off`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`)，选定后向 Python 发送 `thinking_set` 并同步更新 Editor 边框颜色；
   - `/login` / `/logout`：弹出原厂 `LoginDialogComponent` 与 `LogoutSelectorComponent`，密钥保存至全局 `~/.my-pi-agent/auth.json`。

### 4.2 焦点管理保证

原厂 `showSelector(selector)` 模式保证在弹窗存活期间接管所有终端键盘事件，任何字符输入直接输入到选择器的搜索框中；按下 `Esc` 退出或 `Enter` 确认后，自动清理并安全归还焦点到主编辑框。

---

## 五、异常处理、终端自适应与状态同步 (Error Handling & Edge Cases)

1. **Python 进程异常退出与断连保护**：
   - `PythonKernelClient` 监听 `exit` / `error` 事件；
   - 一旦 Python 意外退出，TUI 在聊天区输出醒目的红色警告条，告知退出代码与原因，同时主动退出终端 Raw 模式，恢复系统光标，防止终端卡死或无法输入。
2. **终端动态缩放与窄屏保护 (SIGWINCH)**：
   - 采用原厂 `chat-viewport.ts` 监听尺寸变更事件，触发增量布局重算；
   - 宽度不足 60 列时，`FooterComponent` 自动隐藏 Cost 与 Token 细节，仅保留工作路径与模型徽章，保证排版不撕裂。
3. **会话恢复原子化历史重放**：
   - 会话切换成功后，前端原子化拉取 `session_history`，依次组装 `UserMessageComponent`、带折叠的 `AssistantMessageComponent` 及标记已完成的 `ToolExecutionComponent`，视口平滑滚动到底部。

---

## 六、验证计划与测试策略 (Verification & Testing Strategy)

### 6.1 自动化测试矩阵

- **单元测试 (`test/bridge/event-translator.test.js`)**：
  - 测试正文 `delta` 与思考 `reasoning_delta` 混合流式累积；
  - 测试工具调用 start/update/end 周期中的参数与结果解析；
  - 测试异常中断信号与空字符边界。
- **桥接层测试 (`test/bridge/kernel-bridge.test.js`)**：
  - 测试调用 `prompt()`, `switchModel()`, `resumeSession()` 与底层 client 调用的正确性。
- **组件回归测试 (`test/components/*.test.js`)**：
  - 运行已有的 43+ 个组件测试，确保所有原厂组件正确接入、逻辑通过。
- **全链路集成测试 (`test/e2e.test.js`)**：
  - 拉起真实 Python `rpc_server.py`，执行提示词交互、模型切换与正常退出，全流程绿灯。

### 6.2 真机交互验收门禁 (Manual Acceptance Gates)

1. **门禁 1（启动与排版）**：`npm start` 启动瞬间，Logo、版本号、动态双边框与底部 Footer 状态条高保真显示，无闪烁；
2. **门禁 2（流式打字与思维链折叠）**：输入提问，思考过程折叠显示（按 `Ctrl+O` 自由展开/收拢），正文代码块流式打字且带高亮；
3. **门禁 3（工具动效与截断）**：执行 `read` / `bash`，Spinner 动态旋转，输出带耗时统计与自动截断；
4. **门禁 4（弹窗选择器与快捷键）**：`/model` (Ctrl+M) 模糊搜索与 Tab 切换；`/session` (Ctrl+R) 会话恢复无残影；
5. **门禁 5（异常打断与缩放）**：流式过程中按 `Esc` 立即中断并重置状态；窗口拉伸缩放界面自动自适应。
