# 设计文档：对标 Pig-Mono 与 Tau 的高级特性规划与架构设计规范

- **文档名称**：对标 `pig-mono` 与 `tau` 的高级特性规划与架构设计规范
- **归档路径**：`docs/coding/05-pigmono-tau-feature-parity-design.md`
- **日期**：2026-09-12
- **状态**：设计完成，待评审
- **目标范围**：
  - `packages/my-agent-tui/`（交互与呈现层）
  - `packages/my-coding-agent/`（业务与工具层）
  - `packages/my-agent-llm/`（模型与鉴权适配层）
  - `packages/my-agent-core/`（微内核保持零侵入）
- **参考标杆**：
  - `tau` (`src/tau_coding/oauth*.py`, `credentials.py`, `catalog_loader.py`, `branch_summary.py`)
  - `pig-mono` (`packages/pig-coding-agent/permissions.py`, `billing.py`, `packages/pig-tui/components.py`)
  - `pi` (`packages/ai/src/auth/oauth/`, `packages/coding-agent/src/core/trust-manager.ts`)

---

## 一、架构愿景与分层职责

目前 `my-pi-agent` 已经完成了四包解耦架构（`core` / `llm` / `coding-agent` / `tui`），并拥有 6 大核心工程工具、Multi-Edit 逆序替换、彩色 Diff 渲染以及交互式 REPL 终端。
为了使本项目达到 **Tau** 与 **Pig-Mono** 等工业级开源智能体的产品成熟度，我们需要系统性地补齐**“凭据鉴权”、“安全审查”、“生态接入”、“计费感知”与“分支记忆”**五大高级能力。

### 核心分层设计原则

1. **微内核零侵入**：`my-agent-core` 保持纯粹的通用调度微内核，不引入任何 OAuth 依赖、网络凭据读取或 UI 逻辑；
2. **鉴权职责下沉**：Token 解析与 Header 注入归属于 `my-agent-llm`；
3. **策略规则收敛**：高危命令校验与权限规则收敛于 `my-coding-agent`；
4. **用户交互挂载**：终端弹窗、按键确认与命令路由收敛于 `my-agent-tui`。

```text
+-------------------------------------------------------------------------------+
|                            my-agent-tui (终端交互)                            |
|    - 交互式命令: /login, /logout, /cost, /tree, /models                       |
|    - 权限交互: ConfirmView (在终端展示 Diff 并提示 [y/N])                     |
+-------------------------------------------------------------------------------+
                                         │ 驱动
                                         ▼
+-------------------------------------------------------------------------------+
|                        my-coding-agent (业务与工具层)                         |
|    - 权限门禁: PermissionGate (基于 ToolCallHook 拦截高危 Shell 与写操作)     |
|    - MCP 自动加载: 读取 .mcp.json 并管理 stdio 子进程生命周期                 |
|    - 分支摘要: 离开旧分支时自动调用轻量模型生成 BranchSummaryEntry            |
+-------------------------------------------------------------------------------+
                                         │ 驱动
                                         ▼
+-------------------------------------------------------------------------------+
|                         my-agent-llm (模型与鉴权适配)                         |
|    - 全局凭据中心: CredentialStore (~/.my_agent/credentials.json)              |
|    - OAuth 协议族: GitHub Copilot Device Code, Claude PKCE OAuth              |
|    - 动态计费目录: Catalog (~/catalog.toml)，计算 Token 与美元成本            |
+-------------------------------------------------------------------------------+
                                         │
                                         ▼
+-------------------------------------------------------------------------------+
|                         my-agent-core (通用微内核)                            |
|    - 纯函数 ReAct 循环、Session 树、ContextCompactor、TaskStore (保持纯洁)     |
+-------------------------------------------------------------------------------+
```

---

## 二、模块一：统一凭据中心与 OAuth 授权生态 (P0)

### 2.1 痛点与收益

- **痛点**：传统模式要求每个用户都必须自行去 OpenAI / Anthropic 绑定信用卡充值商业 API Key，门槛极高；且 API Key 经常硬编码在各个项目的 `.env` 中，跨项目无法共享且容易误提交到 Git。
- **收益**：
  1. 支持直接使用开发者已有的 **GitHub Copilot 订阅**（白嫖 GPT-4o / Claude 3.5 Sonnet / o1，无需额外充值）；
  2. 支持使用 **Claude Pro/Max 订阅** 进行 PKCE 授权；
  3. 全局凭据存储在用户主目录，跨所有项目无缝共享。

### 2.2 用户全局凭据中心 (`CredentialStore`)

- **存储路径**：`~/.my_agent/credentials.json`
- **安全规范**：文件权限设置为 `0600`（仅当前系统用户可读写），写入时采用原子替换（临时文件 + `os.replace`）。
- **数据结构**：

  ```json
  {
    "active_profiles": {
      "github-copilot": "default",
      "anthropic": "work"
    },
    "credentials": {
      "github-copilot": {
        "access_token": "ghu_xxxxxx",
        "refresh_token": "ghr_xxxxxx",
        "expires_at": 1726156800,
        "token_type": "Bearer",
        "account_id": "user@github"
      }
    }
  }
  ```

- **凭据加载优先级**：
  `显式构造参数` > `当前项目 .env 环境变量` > `全局 ~/.my_agent/credentials.json`。

### 2.3 GitHub Copilot OAuth (RFC 8628 Device Code Flow)

为什么优先实现 Copilot OAuth？

- **零本地端口依赖**：采用标准的设备码流程（Device Flow），不需要在本地启动 HTTP 服务器监听回调，在无头服务器、远程 SSH 或 Docker 中体验极佳；
- **用户心智极简**：
  1. 用户在终端输入 `/login copilot`；
  2. 终端打印：

     ```text
     请在浏览器打开: https://github.com/login/device
     输入一次性验证码: ABCD-1234
     等待授权中... [======]
     ```

  3. 轮询 GitHub 授权端点，获取 Access Token；
  4. 自动通过 Copilot Token 交换端点（`https://api.github.com/copilot_internal/v2/token`）换取模型网关访问凭证并保存在 `CredentialStore`。
- **运行期注入**：`my-agent-llm` 增加 `CopilotProvider`，请求网关地址指向 `https://api.githubcopilot.com`，自动附加 `Editor-Version` 与 `Copilot-Integration-Id` 请求头。

---

## 三、模块二：安全审批与 Accept-on-Diff 权限门禁 (P0)

对标 **Pig-Mono** 的 `PermissionPolicy` 与 **Tau** 的 `tool_call` 决策钩子。

### 3.1 三级安全审查模式

1. **`review` 模式 (默认交互模式 - 最佳体验平衡)**：
   - 只读工具（`read`, `grep`, `find`）及安全命令（`git status`, `pytest`, `uv run`）**静默自动放行**；
   - `write` 与 `edit`：在终端渲染**彩色 Unified Diff**，弹出交互式审查条，提示用户按回车确认或 `n` 拒绝；
   - 包含 `rm`, `git reset`, 管道覆写或未知 `bash` 命令时，高亮打印命令并要求明确确认。
2. **`autonomous` / `yolo` 模式 (无人值守模式)**：
   - 适合 CI/CD 自动化流水线或自动化基准测试，所有工具自动放行，仅保留底层硬性黑名单阻断（如 `rm -rf /`）。
3. **`strict` 模式 (强安全模式)**：
   - 任何有副作用的调用均需用户逐项按键审批。

### 3.2 零侵入微内核实现

利用 `my-agent-core` 的 `ToolCallHook` 纯外部织入：

```python
class PermissionGate:
    def __init__(self, mode: str = "review", console: Console | None = None):
        self.mode = mode
        self.console = console or Console()

    async def __call__(self, hook: ToolCallHook) -> HookResult:
        if self.mode == "autonomous":
            return HookResult()

        # 只读工具直接放行
        if hook.tool_name in ("read", "grep", "find"):
            return HookResult()

        # 写文件或编辑：展示彩色 Diff
        if hook.tool_name in ("write", "edit"):
            approved = await self._prompt_diff_approval(hook)
            if not approved:
                return HookResult(block=True, reason="用户在审查 Diff 后拒绝了修改。")

        # Shell 命令审查
        if hook.tool_name == "bash":
            approved = await self._prompt_bash_approval(hook)
            if not approved:
                return HookResult(block=True, reason="用户拒绝了此 Shell 命令的执行。")

        return HookResult()
```

---

## 四、模块三：模型知识库与动态计费监控 (P1)

对标 **Tau** 的 `catalog.toml` 与 **Pig-Mono** 的 `BillingTracker`。

### 4.1 模型目录库 (`catalog.toml`)

- 摆脱代码中硬编码上下文窗口与单价的缺陷；
- 维护主流大模型的静态特征字典与阶梯价格表：

  ```toml
  [openai.gpt-4o]
  context_window = 128000
  max_output_tokens = 4096
  cost = { input = 2.5, output = 10.0, cache_read = 1.25 }

  [deepseek.deepseek-chat]
  context_window = 64000
  max_output_tokens = 8192
  cost = { input = 0.14, output = 0.28, cache_hit = 0.014 }

  [anthropic.claude-3-5-sonnet]
  context_window = 200000
  max_output_tokens = 8192
  cost = { input = 3.0, output = 15.0, cache_read = 0.3 }
  ```

### 4.2 实时成本核算器 (`BillingTracker`)

- 在每轮 ReAct 结束时，解析 `Response.usage`（`prompt_tokens`, `completion_tokens`, `cached_tokens`）；
- 根据当前模型匹配单价，精确计算美元与人民币开销；
- **`/cost` 终端命令**：输出漂亮的分项统计表格（输入 Token、输出 Token、Cache 命中率、累计总消费）。

---

## 五、模块四：会话树交互式漫游与分支摘要 (P1)

对标 **Tau** 的 `branch_summary.py` 与 **Pi** 的分支导航。

### 5.1 痛点与机制

- **痛点**：当用户尝试了某个解决思路发现不通，调用 `/undo` 回退并开启新思路时，大模型在新的分支中完全不知道上一条分支尝试了什么，容易重复犯同样的错误。
- **自动分支摘要 (Branch Summary)**：
  - 当用户从节点 $B$ 回退到祖先节点 $A$ 并派生新节点 $C$ 时；
  - 后台使用轻量级快速模型（如 `deepseek-chat` 或 `gemini-flash`）对已放弃的分支 $A \rightarrow B$ 进行 100 字以内的要点总结（“尝试了方案 X，但因为报错 Y 失败”）；
  - 将总结作为 `BranchSummaryEntry` 挂载在节点 $C$ 的上下文视口中；
  - **效果**：Agent 继承了失败教训，绝不重复踩坑，同时不产生长上下文 Token 浪费。

### 5.2 终端交互式会话树浏览器 (`/tree`)

- 在终端中以漂亮的缩进树结构输出历史对话分支；
- 支持查看当前活跃叶子节点指针（`*`）与快速跳转命令（`/checkout <entry_id>`）。

---

## 六、模块五：开箱即用工作区 MCP 自动挂载 (P1)

对标 **Pi** 与 **Claude Code** 的即插即用工作区生态。

### 6.1 运行机制

- `CodingAgent` 在初始化时：
  1. 探测工作区根目录下是否存在 `.mcp.json`；
  2. 若存在，自动解析其中的 `mcpServers` 配置（命令、参数、环境变量）；
  3. 通过已就绪的 `my_coding_agent.mcp.MCPClientManager` 自动异步拉起各外部子进程；
  4. 将发现的远程外部工具自动注册到当前 Agent 的 `ToolRegistry`；
  5. 注册会话退出钩子（或上下文管理器退出），确保退出时 100% 优雅终结所有 MCP 子进程，绝不留下孤儿进程。

---

## 七、模块六：Monorepo 工程打包基建规范 (P0)

对标 `pig-mono` 的 UV Workspace 组织形式。

### 7.1 根目录 `pyproject.toml` (UV Workspace)

在仓库根目录添加统领性 `pyproject.toml`：

```toml
[tool.uv.workspace]
members = ["packages/*"]

[tool.uv.sources]
my-agent-core = { workspace = true }
my-agent-llm = { workspace = true }
my-coding-agent = { workspace = true }
my-agent-tui = { workspace = true }
```

- **收益**：在根目录下执行 `uv sync` 一次性完成所有 4 个子包的依赖解析与可执行脚本安装；在根目录下执行 `uv run pytest` 可以并行测试全库。

### 7.2 元数据规范化补齐

为全仓库 4 个子包全面补充 PEP 621 标准元数据：

- `authors = [{ name = "zxj", email = "..." }]`
- `license = "MIT"`，并在根目录下创建标准 `LICENSE` 文件；
- `[project.urls]` 添加 GitHub 仓库、个人博客专栏与反馈链接；
- `classifiers` 声明支持的 Python 版本与运行环境。

---

## 八、建议的分期推进路线图 (Roadmap)

```text
Phase 3A: 工程基建规范与 Monorepo UV Workspace 整合 ⭐ 【立即执行】
  ├── 1. 建立根目录 pyproject.toml ([tool.uv.workspace]) 与 LICENSE
  └── 2. 规范化 4 个子包的 authors、license、urls、classifiers 元数据

Phase 3B: 全局凭据中心与 GitHub Copilot Device Code OAuth ⭐ 【核心高价值】
  ├── 1. 实现用户主目录 CredentialStore (~/.my_agent/credentials.json)
  ├── 2. 实现 GitHub Copilot Device Flow OAuth (RFC 8628) 与 Token 交换
  ├── 3. my-agent-llm 增加 CopilotProvider 支持已有订阅调用
  └── 4. my-agent-tui 增加 /login 与 /logout 命令

Phase 3C: Accept-on-Diff 权限审查门禁与 Turnkey MCP 自动挂载
  ├── 1. 实现基于 ToolCallHook 的 PermissionGate (Diff 终端审查提示)
  └── 2. CodingAgent 自动探测并挂载当前工作区 .mcp.json

Phase 3D: 模型知识库、成本核算与会话树漫游
  ├── 1. 引入 catalog.toml 与 BillingTracker (计算 USD 成本，支持 /cost)
  └── 2. 会话分支漫游 (/tree) 与放弃分支自动 Branch Summary 总结
```
