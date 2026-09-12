# 设计文档：对标 Tau 与 Pig-Mono 产品层高级特性规划暨 Antigravity OAuth 专项设计规范

- **文档名称**：对标 `tau` 与 `pig-mono` 的高级特性规划暨 Antigravity OAuth 架构设计规范
- **归档路径**：`docs/coding/05-product-layer-advanced-features-design.md`
- **日期**：2026-09-12
- **状态**：设计完成，待评审
- **目标包**：
  - `packages/my-agent-tui/`（终端呈现与交互组件层）
  - `packages/my-coding-agent/`（业务、工具与安全策略层）
  - `packages/my-agent-llm/`（大模型、鉴权与 Antigravity 提供商层）
  - `packages/my-agent-core/`（通用调度微内核保持零侵入）
- **参考标杆**：
  - `pi`：`pi-antigravity` (`C:/Users/ASUS/.pi/agent/auth.json`, `antigravity-quota.ts`)、`packages/tui`
  - `tau`：`src/tau_coding/` (`commands.py`, `branch_summary.py`, `catalog_loader.py`, `project_trust.py`)
  - `pig-mono`：`packages/pig-tui/` (`components.py`, `prompt.py`)、`packages/pig-coding-agent/` (`permissions.py`, `file_reference.py`, `billing.py`)

---

## 一、架构愿景与解耦定位

在完成了四包解耦架构后，本规范致力于将 **Tau**、**Pig-Mono** 与 **Pi** 中最精良的工程特性体系化吸收，重点攻克：

1. **OAuth 鉴权专项聚焦**：**只做 Antigravity OAuth**（参考 `pi-antigravity` 与 Google Cloud Code Assist 协议），彻底摆脱繁琐的信用卡付费与商业 API Key 门槛，直接复用开发者本地已有的 Google/Antigravity 免费顶极大模型配额（Gemini 3.8/3.7/3.1, Claude Sonnet 4.6）；
2. **交互式安全审查门禁 (`ConfirmView` & `PermissionGate`)**：吸收 Pig-Mono 的 `PermissionPolicy`，在写文件与高危 Shell 执行前弹出终端彩色 Diff 审查条；
3. **提示词 `@` 文件引用快速补全 (`file_reference.py`)**：吸收 Pig-Mono 的 `@filename` 自动发现与上下文嵌入；
4. **会话树分支漫游与分支记忆 (`TreeBrowser` & `branch_summary.py`)**：吸收 Tau 的分支自动总结机制，避免回退后重复踩坑；
5. **开箱即用工作区生态 (`Turnkey MCP`)**：自动发现并挂载当前工作区的 `.mcp.json`。

### 架构协同全景图

```text
+-------------------------------------------------------------------------------+
|                                  my-agent-tui                                 |
|  - 交互组件: ConfirmView (Diff审查提示条), TreeBrowser (会话树漫游器)          |
|  - 输入增强: FileReferenceCompleter (@文件名自动补全与动态注入)               |
|  - 交互命令: /login antigravity, /quota, /tree, /cost, /mcp                   |
+-------------------------------------------------------------------------------+
                                         │ 驱动与渲染
                                         ▼
+-------------------------------------------------------------------------------+
|                                my-coding-agent                                |
|  - 权限审批: PermissionGate (基于 ToolCallHook 拦截 write/edit/高危 bash)  |
|  - 工作区生态: Turnkey MCP (自动发现 .mcp.json 并管理 stdio 外部子进程生命周期)|
|  - 分支记忆: BranchSummaryManager (回滚撤销时调用轻量模型总结失败经验)         |
+-------------------------------------------------------------------------------+
                                         │ 调度
                                         ▼
+-------------------------------------------------------------------------------+
|                                 my-agent-llm                                  |
|  - Antigravity OAuth: 自动发现并复用 ~/.pi/agent/auth.json，支持 Token 自动刷新 |
|  - AntigravityProvider: 对接 cloudcode-pa.googleapis.com (Gemini 3.8/3.7 等) |
|  - Catalog & Billing: 模型元数据库与实时 Token/成本核算                      |
+-------------------------------------------------------------------------------+
                                         │ 底层微内核
                                         ▼
+-------------------------------------------------------------------------------+
|                                my-agent-core                                  |
|  - 纯函数 ReAct 微内核、Session DAG 树、ContextCompactor、TaskStore (零侵入保持纯粹)|
+-------------------------------------------------------------------------------+
```

---

## 二、模块一：Antigravity OAuth 鉴权与模型接入专项设计 (P0 核心高价值)

### 2.1 为什么 OAuth 专项只做 Antigravity？

1. **开发者体验与成本降维打击**：Google Cloud Code Assist (Antigravity) 提供了海量免费、高并发的顶尖大模型配额（包含 `gemini-3.8-flash`、`gemini-3.7-flash`、`gemini-3.1-pro` 以及 `claude-sonnet-4-6`），完全无需个人绑卡充值；
2. **本地现成凭据无缝继承（极度优雅）**：本地系统已经在使用 Pi，且在 `~/.pi/agent/auth.json` 中已经存在授权好的有效 Google OAuth Refresh Token 与 Access Token。我们无需让用户重新扫码登录，即可直接复用该凭据，真正做到“零配置开箱即用”！

### 2.2 凭据解析与发现拓扑 (`AntigravityAuthResolver`)

在 `my-agent-llm` 中建立分层凭据解析器：

```text
           获取 Antigravity 访问凭据 (Access Token & Project ID)
                                   │
      ┌────────────────────────────┼────────────────────────────┐
      ▼ 1. 显式环境变量           ▼ 2. 项目/用户全局凭据库     ▼ 3. 无缝继承 Pi 本地凭据
ANTIGRAVITY_API_KEY /      ~/.my_agent/credentials.json     ~/.pi/agent/auth.json
ANTIGRAVITY_ACCESS_TOKEN     (优先读取当前项目的凭据)         (读取 antigravity / google-antigravity)
```

- **自动静默刷新机制**：
  - 检查 Token 是否过期（`expires < time.time() * 1000 + 300000`，即剩余有效期不足 5 分钟）；
  - 若已过期，自动使用 `refresh_token` 向 Google OAuth 端点发起刷新请求：
    `POST https://oauth2.googleapis.com/token`
    参数包含 `client_id`, `client_secret`, `refresh_token`, `grant_type="refresh_token"`；
  - 刷新成功后自动将新生成的 `access_token` 写回凭据存储。

### 2.3 `AntigravityProvider` 实现规范

- **包位置**：`packages/my-agent-llm/src/my_agent_llm/providers/antigravity.py`
- **通信网关**：
  - Candidate 官方端点：`https://cloudcode-pa.googleapis.com` 与 `https://daily-cloudcode-pa.googleapis.com`；
  - User-Agent 标记：`antigravity/cli/1.1.23 (aidev_client; os_type=windows; arch=amd64; auth_method=consumer)`；
  - 自动向请求头注入：
    - `Authorization: Bearer <access_token>`
    - `x-goog-user-project: <projectId>`（默认为 `aicode-consumers`）
- **流式增量与思考链解包**：
  - 完整兼容 `StreamAccumulator`，将 Antigravity 返回的 `thoughtSignature` / `reasoning_content` 映射为 `ThinkingDeltaEvent`；
  - 将工具调用映射为规范化的 `ToolCall`。

### 2.4 终端交互命令

在 `my-agent-tui` 中支持：

- `/login antigravity`：如果本地检测到 `~/.pi/agent/auth.json`，直接提示 `✓ 已自动关联本地 Pi Antigravity 凭据 (账号: nujabesnan@gmail.com)`；若无，引导打开浏览器进行 Google OAuth 授权；
- `/quota`：调用 `v1internal:retrieveUserQuotaSummary` 接口，在终端以彩色进度条展示各模型（如 `gemini-3.8-flash`）的剩余配额百分比与重置倒计时。

---

## 三、模块二：交互式安全审查门禁与确认对话框 (P0 安全基石)

学习自 **Pig-Mono** 的 `packages/pig-tui/src/pig_tui/components.py:ConfirmView` 与 `packages/pig-coding-agent/src/pig_coding_agent/permissions.py:PermissionPolicy`。

### 3.1 终端确认组件 `ConfirmView` (`my_agent_tui.components.confirm`)

- **定位**：运行在终端 REPL 主循环中的微型轻量审查组件（基于 `prompt_toolkit` / `rich`）。
- **表现形态**：

  ```text
  ┌── ⚠️  文件修改审查 [write / edit] ────────────────────────┐
  │ 目标: src/calculator.py                                   │
  │ --- a/src/calculator.py                                   │
  │ +++ b/src/calculator.py                                   │
  │ @@ -1,3 +1,3 @@                                           │
  │ -    return a - b                                         │
  │ +    return a + b                                         │
  └───────────────────────────────────────────────────────────┘
  是否确认应用以上修改？ [Y/n]: 
  ```

- **快捷键响应**：回车 / `y` / `Y` 批准放行；`n` / `N` / `Esc` 阻断拒绝。

### 3.2 业务权限策略 `PermissionGate` (`my_coding_agent.permissions`)

- **实现机制**：通过 `my-agent-core.ToolCallHook` 纯外部织入，**底层微内核零修改**。
- **三级工作模式**：
  1. **`review` 模式（默认交互模式，最佳 DX 平衡）**：
     - 只读工具（`read`, `grep`, `find`）与非破坏性白名单命令（`git status`, `pytest`, `uv run` 等）**静默自动放行**；
     - `write` 与 `edit`：触发 `ConfirmView` 展示彩色 Unified Diff，等待用户确认；
     - 包含 `rm`, `git reset`, 管道重定向或跨目录写入的高危 `bash` 命令强行弹框请求确认。
  2. **`autonomous` / `yolo` 模式**：CI/CD 自动化流水线或快速脚本场景，除底层毁灭性命令（`rm -rf /`）外全自动放行。
  3. **`strict` 模式**：所有有副作用的操作均需逐项按键确认。

---

## 四、模块三：提示词 `@` 文件引用快速补全 (P1 体验利器)

学习自 **Pig-Mono** 的 `packages/pig-coding-agent/src/pig_coding_agent/file_reference.py`。

### 4.1 用户使用场景

开发者在终端提问时，经常需要指明具体文件：
`>>> 请帮我重构 @src/main.py，并在 @tests/test_main.py 中补充用例`

### 4.2 架构与实现方案

1. **输入阶段 Tab 自动补全 (`FileReferenceCompleter`)**：
   - 当用户在输入框键入 `@` 时，`prompt_toolkit` 自动触发文件补全器；
   - 自动扫描工作区文件树（跳过 `.git`, `.venv`, `node_modules` 等无关目录），实时弹出文件名候选菜单供上下键选择。
2. **提交阶段自动上下文注入 (`expand_file_references`)**：
   - 在将用户输入提交给 `CodingAgent` 前，自动提取 `@path/to/file`；
   - 检查文件有效性并读取文件内容，在 Prompt 末尾自动组装 `<referenced_files>` 代码块：

     ```markdown
     <referenced_file path="src/main.py">
     def hello(): pass
     </referenced_file>
     ```

   - **巨大收益**：大模型无需在第一轮额外消耗 1 个 Tool Turn 专门去 `read` 该文件，直接在首轮对话中拿到文件内容并开始分析，**节约 50% 往返耗时与 API 开销**！

---

## 五、模块四：会话树交互式漫游与分支自动记忆 (P1)

学习自 **Tau** 的 `tau_coding/branch_summary.py` 与 `TreePickerScreen`。

### 5.1 痛点与解决方案

- **痛点**：用户在多轮交互中尝试方案 A 发现不通，输入 `/undo` 回退并尝试方案 B 时，大模型在新的分支中完全失去了上一条分支的记忆，往往会把之前失败的弯路重新走一遍。
- **自动分支摘要机制 (`BranchSummaryManager`)**：
  - 当检测到当前会话指针从叶子节点 $B$ 回退到祖先节点 $A$ 并开启新分支 $C$ 时；
  - 后台自动调用轻量快速模型（如 `gemini-3.8-flash`）对被放弃的分支进行 150 字以内的浓缩总结：
    `"在尝试解决加法 Bug 时，曾尝试方案 X 修改了 Y 文件，但因为报错 Z 失败。"`
  - 将此总结作为一条标准的 `BranchSummaryEntry` 挂载在节点 $C$ 的系统上下文中；
  - **效果**：大模型继承了上一次尝试的失败教训，绝不重犯同样错误，且完全不污染长上下文。

### 5.2 终端交互式会话树选择器 (`TreeBrowser`)

- 在 `my-agent-tui` 中支持 `/tree` 命令；
- 以缩进 ASCII 树形图直观呈现历史对话分支、各分支的主题意图、当前所在分支标记（`*`）；
- 支持直接输入 `/checkout <node_id>` 瞬间在不同思路分支之间穿梭。

---

## 六、模块五：开箱即用工作区 `.mcp.json` 自动扫描挂载 (P1)

学习自 **Pi** 与 **Claude Code**。

### 6.1 核心机制

- `CodingAgent` 在启动初始化时：
  1. 探测工作区根目录下是否存在 `.mcp.json`；
  2. 若存在，自动解析其中的 `mcpServers` 配置字典；
  3. 通过已就绪的 `my_coding_agent.mcp.MCPClientManager` 自动拉起各 stdio 子进程（如官方 Postgres MCP、Git MCP、Fetch MCP 等）；
  4. 将发现的远程外部工具自动注册到当前 Agent 的 `ToolRegistry`；
  5. 注册会话退出钩子（`AsyncExitStack`），确保终端关闭时 100% 优雅终结所有 MCP 子进程，绝不留下后台僵尸进程。

---

## 七、模块六：模型特性目录与实时计费监控 (P2)

学习自 **Tau** 的 `data/catalog.toml` 与 **Pig-Mono** 的 `billing.py`。

### 7.1 模型元数据目录 (`catalog.toml`)

- 集中管理主流大模型的上下文窗口大小（如 128k / 200k / 1M）、最大输出 Token、以及分阶梯的计费单价；
- 摆脱代码中硬编码窗口阈值的技术债务。

### 7.2 实时成本核算器 (`BillingTracker`) 与 `/cost` 命令

- 每次收到 `Response.usage` 时自动计算并累加美元与人民币开销；
- 在 `my-agent-tui` 中输入 `/cost`，输出漂亮的费用账单表格（输入 Token、输出 Token、Cache 命中率、累计总花费）。

---

## 八、模块七：可插拔底层 I/O 操作协议 (`operations.py`) (P2)

学习自 **Pig-Mono** 的 `packages/pig-coding-agent/src/pig_coding_agent/operations.py`。

### 8.1 架构与解耦机制

- 目前 `my-coding-agent` 的工具（`read`, `write`, `edit`, `bash`）直接硬编码调用本地文件 API 与 `asyncio.create_subprocess_shell`；
- 引入 Python `Protocol` 将文件与子进程 I/O 抽象化：
  - `FileOperations`: 抽象 `read_text`, `write_text`, `exists`, `mkdir`, `iterdir`, `glob` 等方法；
  - `ShellOperations`: 抽象 `run_command(cmd, cwd, env, timeout)` 等命令执行方法；
- **收益**：
  - 本地默认使用 `LocalFileOperations`；
  - 单元测试时可无缝注入 `FakeFileOperations` 进行高并发高密度的纯内存离线测试；
  - 未来如果要支持将 Agent 隔离运行在远程 Docker 容器、云端 Sandbox（如 E2B / Firecracker）中，只需提供 `DockerFileOperations`，上层工具链和 Agent 逻辑 100% 保持不变！

---

## 九、模块八：流式生成期间按键监听与动态转向 (`LiveInputListener`) (P1)

学习自 **Pig-Mono** 的 `packages/pig-tui/src/pig_tui/keylistener.py` 与 **Pi** 的 Steering 机制。

### 9.1 痛点与解决方案

- **痛点**：在大模型流式输出几十秒或正在调用工具时，底层的 `prompt_toolkit` 是处于未激活状态的，此时终端完全无法响应用户的键盘输入。用户如果发现模型理解错了，只能被动干等，或者强行 Ctrl+C 粗暴杀死会话；
- **解决方案 (`LiveInputListener`)**：
  - 在大模型流式生成与工具执行期间，以非阻塞方式在后台监听键盘输入：
    - Windows: 基于 `msvcrt.kbhit()` 与 `msvcrt.getwch()`；
    - POSIX: 基于 `termios` 与 `tty.setcbreak()`；
  - **按键响应**：
    - 按 **`Esc` 键**：立即触发当前 Turn 的 `CancellationToken`，温和中止当前轮次生成；
    - **直接敲字并按回车**：不中断会话，直接将用户输入的纠偏文字作为 `Steering` 消息推入 `my-agent-core` 的 `MessageQueue.push_steering()`；
    - **无缝衔接**：在当前工具执行完或下一次大模型推理前，智能体自动提取此 Steering 消息即时修正方向，实现真正的人机实时协同！

---

## 十、模块九：命令路由哲学对比（为何拒绝拆分 6 个 `interaction_*.py`？）

深入审视 **Pig-Mono** 的 `interaction_routes.py`、`interaction_dispatcher.py`、`interaction_views.py`、`interaction_flows.py`、`interaction_runtime.py`、`interaction_catalog.py`。

### 10.1 Pig-Mono 为什么要拆出 6 个 interaction 文件？
- Pig-Mono 在终端设计了一套类似 Web 前端框架（如 React-Router / Vue-Router）的路由跳转机制：
  - `interaction_routes.py` 是路由映射表（区分无参路由 `simple_routes` 与带参前缀路由 `prefix_routes`）；
  - `interaction_dispatcher.py` 是分发匹配引擎；
  - `interaction_views.py` 负责展示面板（视图层）；
  - `interaction_flows.py` 负责处理多步向导（比如弹出选择会话的交互列表）；
  - `interaction_runtime.py` 负责覆盖层状态机。

### 10.2 我们需要照搬吗？（决策：坚决不照搬，保持极简 CommandDispatcher）
- **判定：不需要照搬拆分，严防过度设计**！
  - 理由：将 ~10 个命令的交互拆成 6 个文件会导致阅读与追踪代码极其碎片化，违反了“50 行能清晰解决绝不写 200 行”的原则；
  - **我们的演进方案**：保留目前在 `my_agent_tui/commands.py` 中实现的单一高内聚 `CommandDispatcher`（约 180 行），仅吸收其**“前缀带参路由支持（如 `/skill:<name>`）”**与**“多步选择向导（Picker Flows）”**的逻辑，使代码保持紧凑、直观且零过度抽象。

---

## 十一、建议的分期推进路线图 (Roadmap)

```text
Phase 3A: Antigravity OAuth 专项直连与本地凭据无缝继承 ⭐ 【立即推进 / 免费顶尖大模型接入】
  ├── 1. 实现 AntigravityAuthResolver（自动探测 ~/.pi/agent/auth.json，支持 Google OAuth 静默刷新）
  ├── 2. my-agent-llm 新增 AntigravityProvider（对接 cloudcode-pa.googleapis.com 网关）
  └── 3. my-agent-tui 增加 /login antigravity 与 /quota 配额查询命令

Phase 3B: Accept-on-Diff 权限审查门禁与确认对话框 ⭐ 【安全核心】
  ├── 1. my-agent-tui 构建 ConfirmView 终端确认与彩色 Diff 审查组件
  └── 2. my-coding-agent 实现 PermissionGate（基于 ToolCallHook 拦截高危写操作与命令）

Phase 3C: 提示词 @ 文件引用快速补全与工作区 Turnkey MCP
  ├── 1. my-agent-tui 输入框支持 @ 文件名 Tab 自动补全并在提交前自动注入文件快照
  └── 2. CodingAgent 启动时自动探测并挂载工作区 .mcp.json

Phase 3D: 流式动态转向 (LiveInputListener) 与分支失败记忆 (branch_summary.py)
  ├── 1. my-agent-tui 增加 LiveInputListener (流式输出期间按 Esc 取消 / 输入回车触发 Steer)
  └── 2. 回退分支时自动触发轻量模型生成 BranchSummaryEntry 挂载公共祖先

Phase 3E: 模型知识库 (catalog.toml)、计费账单 (/cost) 与 I/O 协议抽象 (operations.py)
```
