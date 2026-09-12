# 产品层全景功能规划与 TUI 独立分层架构设计规范

- **定位**：产品层全景功能规划与 `my-agent-tui` 独立解耦架构设计规范
- **目标包**：
  - 新建：`packages/my-agent-tui/` (`src/my_agent_tui/`)
  - 纯化：`packages/my-coding-agent/` (`src/my_coding_agent/`)
- **参考标杆**：
  - `pig-mono`：`packages/pig-tui`（纯终端呈现库）+ `packages/pig-coding-agent`（业务与装配）
  - `tau`：`tau_coding/commands.py`（协议化命令系统）+ `tau_coding/tui`（会话树与组件视图）
  - `pi`：`packages/tui`（自研终端组件库）+ `packages/coding-agent`（编程助手产品）

---

## 一、架构分层与解耦动机

在 `my-pi-agent` 演进初期，我们将交互式 CLI 与终端渲染逻辑（`cli.py`、`renderer.py`、`commands.py`）临时放置在 `packages/my-coding-agent` 中。
然而，随着对开源标杆 **Pig-Mono**（`pig-tui` 独立呈现库）和 **Pi**（`packages/tui` 独立库）的深入探索，我们发现**将“终端呈现与输入”与“编码业务逻辑与工具集”紧耦合存在明显的架构弊端**：

1. **终端依赖污染纯业务逻辑**：
   `my-coding-agent` 核心职责是为写代码提供 6 大高鲁棒性文件工具（`read/write/edit/bash/grep/find`）、`FileMutationQueue` 细粒度文件锁、MCP 外部扩展与 Dual API（`run` / `run_stream`）。强行引入 `prompt_toolkit` 与 `rich` 会使得如果未来有人想把 `my-coding-agent` 作为后端服务嵌入 VS Code 插件、Web API、CI/CD 自动化流水线或 RPC Daemon 时，被迫带上终端 UI 的沉重包袱。
2. **呈现层组件无法通用化复用**：
   交互式打字机渲染器（`EventRenderer`）、多行输入与 Tab 命令补全（`PromptSession`）、Windows 字符集守护（`_force_utf8_streams`）、以及未来规划的差异审查弹框（`ConfirmView`）和会话树选择器（`TreeBrowser`），本就属于通用的终端 TUI 资产，不应被私有化在 coding 专有包中。

### 目标分层拓扑

```text
                                  用户直接交互入口
                                         │
                                         ▼
                      +--------------------------------------+
                      |            my-agent-tui              |
                      | (独立 UV 项目 packages/my-agent-tui) |
                      |                                      |
                      |  - cli.py: REPL 循环、命令行参数解析  |
                      |  - renderer.py: 思考流打字机/Diff高亮|
                      |  - commands.py: Slash 命令路由分发中枢|
                      |  - cli_base.py: 跨平台 Windows UTF-8  |
                      |  - components/: 确认对话框/树选择器  |
                      |  - 命令入口: my-agent-tui            |
                      +------------------+-------------------+
                                         │ 单向依赖
                                         ▼
                      +--------------------------------------+
                      |           my-coding-agent            |
                      |       (100% 纯净业务与工具库)        |
                      |                                      |
                      |  - tools/: 6 大核心工具链实现        |
                      |  - mutation_queue: 单文件并发互斥锁  |
                      |  - mcp.py: 原生异步 MCP 客户端扩展   |
                      |  - prompt.py: 编码提示词与上下文注入 |
                      |  - agent.py: CodingAgent 门面        |
                      |    (提供纯净 run() 与 run_stream())  |
                      +------------------+-------------------+
                                         │
                   ┌─────────────────────┴─────────────────────┐
                   ▼                                           ▼
+------------------------------------+       +------------------------------------+
|          my-agent-core             |       |            my-agent-llm            |
| (ReAct微内核 / Session树 / 上下文) |       | (统一大模型网关 / 多厂商 / 流式累加) |
+------------------------------------+       +------------------------------------+
```

---

## 二、开源标杆全景功能深度规划

通过对 `tau_coding`、`pig-tui` 与 `pig-coding-agent` 的源码深入探索，我们为产品层的长远演进规划了以下 5 大核心功能子系统：

### 1. 终端交互组件库（对标 `pig-tui` 与 `pi/packages/tui`）

- **`EventRenderer` (流式事实监听器)**：
  - 单向监听 ReAct 循环生命周期事件；
  - `\U0001f4ad` 思考气泡（Thinking Delta）：以低对比度 `dim italic` 打字机展现内部推导；
  - 正文增量流（Content Delta）：Markdown 打字机输出并转义 Rich 样式标记；
  - 工具调用徽标：`⚙️ [tool]` 启动指示与 `✓ OK` / `✗ Failed` 完成反馈；
  - Unified Diff 彩色高亮：自动拦截 ````diff```` 代码块并调用 `Syntax(..., "diff", theme="monokai")` 进行红绿增删行高亮渲染。
- **`ConfirmView` (交互式审批对话框，对标 `pig-tui/components.py:ConfirmView`)**：
  - 在执行高危操作（如破坏性 `bash` 命令、写覆盖文件）前，在终端弹出 `[Y/n]` 确认条，支持显示变更摘要与 Diff 详情。
- **`TreeBrowser` (会话树交互式导航器，对标 `pig-tui:TreeBrowserContainer` 与 `tau:TreePickerScreen`)**：
  - 基于 `prompt_toolkit` / `rich` 渲染可按上下键选择的会话历史分支列表，展示各轮提问摘要、时间戳与活跃状态，支持一键切换。
- **`AutoCompleter` (智能输入补全，对标 `pig-tui:AutoCompleter`)**：
  - 支持 `/` 斜杠命令的 Tab 自动补全，支持文件路径模糊匹配补全。

### 2. Slash 命令体系（对标 `tau_coding/commands.py`）

- **协议化命令分发 (`CommandContext` & `CommandDispatcher`)**：
  - 内置 8 大核心生产级命令：
    - `/help`：以美化表格展示当前可用命令清单与功能描述；
    - `/clear`：清空终端屏幕并重绘欢迎首部；
    - `/undo`：沿 `Session` 树回溯至上一轮提问的父节点（`session.rewind()`），并自动调用 `agent.reset()` 复位上下文管理器缓存与内存转录本；
    - `/compact`：显式触发 L4 智能上下文摘要，并反馈 Token 节约统计；
    - `/session`：查看当前 Session ID、持久化路径与节点统计；
    - `/tasks`：展示当前 `TaskStore` 任务看板（状态、主题、依赖）；
    - `/mcp`：查看已连接的 MCP 服务器状态与已挂载的外部工具清单；
    - `/exit` 或 `/quit`：优雅退出。
  - **异常沙箱保护**：所有命令执行均置于顶层 `try...except` 保护之下，单个命令报错绝不击穿终端 REPL 循环。

### 3. 安全审批与权限门禁（对标 `pig-coding-agent/permissions.py`）

- **Accept-on-Diff 渐进审批模型**：
  - 只读工具（`read/grep/find`）与非破坏性白名单命令（`git status`, `pytest`, `uv run`）静默自动放行；
  - `write` 与 `edit` 在终端生成彩色 Unified Diff，等待用户按回车确认；
  - 高危 Shell 命令（含 `rm`, 重定向, 跨目录写）强行弹框请求许可；
  - 核心实现挂载于 `my-agent-core` 的 `ToolCallHook`，微内核零侵入。

### 4. 会话分支漫游与分支摘要（对标 `tau_coding/branch_summary.py` 与 `pi`）

- 在用户通过 `/undo` 或 `/session switch` 离开一条长分支并开启新探索时，触发后台轻量级 LLM 摘要，将丢弃分支的探索教训浓缩为一条 `BranchSummaryEntry` 节点挂载在公共祖先处，使 Agent 在新分支中不会重蹈覆辙，同时不占用海量上下文 Token。

### 5. 跨平台终端防护（对标 `tau_coding/cli.py`）

- **`_force_utf8_streams()`**：启动前强制将 `sys.stdout` 和 `sys.stderr` 重置为 UTF-8，彻底消灭 Windows PowerShell / CMD 下的 `UnicodeEncodeError`。

---

## 三、本次重构拆包工程规范

### 1. `packages/my-agent-tui` 新建包规划

```
packages/my-agent-tui/
├── pyproject.toml                     # 依赖：rich, prompt-toolkit, my-coding-agent
├── src/my_agent_tui/
│   ├── __init__.py                    # 导出 EventRenderer, CommandDispatcher, main
│   ├── cli_base.py                    # _force_utf8_streams, _is_utf8_encoding
│   ├── renderer.py                    # EventRenderer (思考打字机、Markdown、Diff高亮)
│   ├── commands.py                    # CommandDispatcher, CommandContext, 8大内置命令
│   ├── cli.py                         # run_cli_loop, build_prompt_session, main()
│   └── __main__.py                    # python -m my_agent_tui 入口
└── tests/
    ├── test_cli_base.py               # 编码保护测试
    ├── test_renderer.py               # 流式事件与 Diff 渲染测试
    ├── test_commands.py               # Slash 命令分发与回滚/压缩测试
    ├── test_cli.py                    # REPL 循环与参数解析测试
    └── test_cli_e2e.py                # 端到端交互模拟测试
```

### 2. `packages/my-coding-agent` 纯净化规划

- **依赖清理**：在 `pyproject.toml` 中彻底移除 `rich` 和 `prompt-toolkit` 依赖；
- **文件清理**：删除已迁出的 `cli.py`, `cli_base.py`, `renderer.py`, `commands.py`, `__main__.py`；
- **测试瘦身**：仅保留 `test_tools.py`, `test_read_tool.py`, `test_write_tool.py`, `test_edit_tool.py`, `test_bash_tool.py`, `test_grep_tool.py`, `test_find_tool.py`, `test_prompt.py`, `test_mcp.py`, `test_agent.py`, `test_coding_agent_e2e.py` 等纯业务测试；
- **顶层导出精简**：`my_coding_agent` 仅导出 `CodingAgent`, `build_coding_tools`, `FileMutationQueue`, `resolve_path`, `EditBlock`, `MCP*`，无任何 UI 概念。
