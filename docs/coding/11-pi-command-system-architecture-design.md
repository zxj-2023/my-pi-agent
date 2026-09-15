# my-pi-agent 对标 Pi 核心命令与输入宏系统架构设计规范

- **文档名称**：对标 Pi 核心命令、会话树漫游与输入宏系统架构设计规范
- **归档路径**：`docs/coding/11-pi-command-system-architecture-design.md`
- **日期**：2026-09-14
- **状态**：设计完成，已通过 Pi 源码逆向审校
- **目标包**：
  - `tui/`（TUI Slash Commands 补全与路由、模态选择器窗口、输入行宏前置解析）
  - `src/my_coding_agent/`（stdio JSON-RPC 2.0 服务端方法扩展、Shell 宏执行管道）
  - `src/my_agent_core/`（会话树分支切换、Fork/Clone 派生、上下文压缩集成）
  - `src/my_agent_llm/`（动态模型切换、各 Provider 思考深度映射、凭据注销）

---

## 一、需求背景与命令范围 (Scope & Exclusions)

为让 `my-pi-agent` 在交互体验与工程深度上完全对齐原厂 Pi，本规范致力于完整复刻 Pi 的全套核心会话管理、模型切换、系统诊断命令以及输入行即时宏扩展体系。

### 1.1 明确排除的命令（已获用户确认）

1. **`scoped-models`**：快速轮转模型管理（当前主打核心大模型直接切换，暂不引入复杂轮转列表）；
2. **`export`**：会话导出为独立 HTML/JSONL（暂不需要离线单页导出）；
3. **`copy`**：复制最后一条回答（已有终端鼠标原生选中与操作系统剪贴板）；
4. **`share`**：上传至 GitHub Gist 公开分享（纯本地私有运行，无需云端分享）；
5. **`hotkeys`**：打印快捷键列表（已有内建的 `/help` 帮助卡片）。

---

### 1.2 目标命令全景矩阵 (Target Command Matrix)

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│                           my-pi-agent 命令全景矩阵                           │
├──────────────────────────────────────────────────────────────────────────────┤
│ 1. 会话控制体系                                                               │
│    • /new                      结束当前会话，开启全新的空白 Session 文件       │
│    • /resume [session_id]      列出/模糊搜索或恢复当前工作区的历史会话          │
│    • /name [title]             查看或设置当前 Session 的友好显示名称           │
│    • /compact [prompt]         触发上下文 L4 级 LLM 摘要压缩 (支持引导指令)    │
│    • /tree                     展示当前会话 DAG 树，支持分支漫游与回退分叉      │
│    • /fork                     选择历史某轮提问，分叉派生为独立新会话文件       │
│    • /clone                    将当前活跃分支完整克隆为新会话文件               │
│                                                                              │
│ 2. 模型与认证控制                                                             │
│    • /model [provider/model]   切换当前生效模型，支持无参弹出模型选择列表       │
│    • /thinking [level]         调节思考预算 (off/minimal/low/medium/high/max)  │
│    • /login [provider] [key]   配置/绑定指定 Provider 的凭证                  │
│    • /logout [provider]        注销或清除指定 Provider 的已存凭据              │
│    • /quota                    查看模型调用配额与余量状态                      │
│                                                                              │
│ 3. 系统与安全环境                                                             │
│    • /session                  查看当前会话统计、模型、Token 及全局集中存储路径│
│    • /settings [key] [val]     查看或就地修改配置项                            │
│    • /reload                   热重载 Skills、Prompts、Extensions 与 AGENTS.md │
│    • /trust [status]           设置或查看当前项目的信任状态 (~/.my-pi-agent/)  │
│                                                                              │
│ 4. 输入行即时宏扩展 (Input Bar Macros)                                        │
│    • !command                  执行本地命令，输出结果**送入大模型上下文**       │
│    • !!command                 执行本地命令，仅屏幕渲染，**不送入模型上下文**   │
│    • /skill:<name> [args]      展开指定 Skill 的 SKILL.md 模板                │
│    • /<template> [args]        展开 prompts/ 目录下的模板并传参替换 $1, $@     │
│                                                                              │
│ 5. CLI 启动参数对齐 (CLI Flags)                                               │
│    • -c, --continue            一键续接当前项目最近一次会话                    │
│    • -r, --resume              启动时直接打开交互式会话选择器                  │
│    • --new-session             强制新建会话                                   │
│    • -n, --name <title>        启动时直接为会话命名                            │
│    • --thinking <level>        启动时指定思考深度                              │
│    • --no-session              无痕沙箱模式，不向磁盘写入 session 文件         │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 二、会话生命周期与 DAG 树状分支系统

基于对 Pi `session-manager.js` 与 `interactive-mode.js` 的源码解构，会话系统采用 **纯只追加 JSONL 记录 + 内存 DAG 投影** 模型。

### 2.1 `/new`（新建会话）

1. **工作流**：
   - 终止当前运行的流式任务与工具调用；
   - 生成新的 UUIDv7 `sessionId` 与 ISO 时间戳；
   - 构造第 1 行 Header：`{"type": "session", "version": 3, "id": sessionId, "timestamp": ts, "cwd": workspace, "parentSession": null}`；
   - 重置内存中的 `byId`、`leafId = null` 以及消息列表；
   - 重新发射当前模型的 `model_change` 与 `thinking_level_change` 基础条目。
2. **延期落盘铁律（Deferred Disk-Write Invariant）**：
   - Pi 严格保证：**若一个会话没有任何助手回复或有价值交互，绝不在磁盘生成孤儿空文件**；
   - 只有在首条 `role: "assistant"` 消息到达时，才真正调用 `openSync(file, "wx")` 创建物理文件并批量刷入前面的 entries。

### 2.2 `/resume [session_id]`（会话恢复）

1. **会话枚举与快速检索**：
   - 扫描 `~/.my-pi-agent/sessions/<project-slug>-<hash>/` 下的所有 `.jsonl` 文件；
   - 采用 4096 字节缓冲区仅读取第 1 行 Header，提取 `id`、`timestamp`、`cwd`，避免大文件一次性全量加载爆内存；
   - 逆向扫描最新几行提取 `session_info` 标题与最后修改时间，按 `modified` 倒序排布。
2. **CWD 安全校验与跨项目 Fork**：
   - 校验 Header 中的 `cwd` 是否存在；若不存在，提示用户选择是否使用当前目录继续；
   - 若通过全局 ID 恢复了其他工程的会话，主动提示是否派生（Fork）到当前工作区。
3. **DAG 祖先链回溯投影**：
   - 沿 `leafId` 向上回溯 `parentId` 直至根节点，生成拓扑有序的历史列表；
   - 定位最新的 `compaction` 节点，过滤掉早于 `firstKeptEntryId` 的已压缩历史，重建上下文。

### 2.3 `/name [title]`（会话重命名）

- 向当前会话以当前 `leafId` 为父节点追加一条 `session_info` 记录：

  ```json
  {"type": "session_info", "id": "e4f2a1b9", "parentId": "c7a8b1...", "timestamp": "...", "name": "重构认证模块"}
  ```

- 严格遵循只追加原则，不修改前面任何行；读取时逆向搜索最新的 `session_info` 记录。

### 2.4 `/tree`（DAG 会话树漫游）

1. **节点树构建**：
   - 内存加载所有 entries，建立 `Map<id, SessionTreeNode>`，构建树状多叉分支；
2. **分支漫游与回退**：
   - 用户选择历史上的某个 node：
     - 若该 node 为 User 提问：将 `leafId` 置为 `node.parentId`，并将用户提问文本原样回填到输入框供修改；
     - 若该 node 为 Assistant / Tool：直接将 `leafId` 重指向该 node，不污染输入框。
3. **分支放弃总结 (`branch_summary`)**：
   - 当从一条深层分支跳跃到另一条旧分支时，系统自动收集被遗弃子分支上的代码修改足迹与关键决策，调用 LLM 生成一段简短摘要；
   - 在新分支目标点追加一条 `branch_summary` 记录，让新分支继承被遗弃分支的踩坑经验，避免重复犯错。

### 2.5 `/fork` vs `/clone`（会话派生与克隆）

| 维度 | `/fork` | `/clone` |
| :--- | :--- | :--- |
| **语义** | 回退到历史某个提问，修改并开辟新线 | 在当前状态完整克隆当前活跃分支进行实验 |
| **目标节点** | 用户交互挑选历史上的某条 `user` 提问 | 自动锚定当前最新的 `leafId` |
| **切入点** | `targetLeafId = selectedEntry.parentId` | `targetLeafId = activeLeaf.id` |
| **输入框表现** | 自动提取该提问内容回填输入框供重写 | 清空输入框 |
| **底层操作** | 沿路径截取 entries，写入全新的 `.jsonl` 文件，并记录 `parentSession` 来源链接 | 将当前活跃分支路径 entries 复制写入全新 `.jsonl` 文件 |

### 2.6 `/compact [instructions]`（手动上下文压缩）

- 立即打断当前轮次；
- 沿当前 leaf 逆向计算 Token 累加，直到达到 `keepRecentTokens` 预算，确定安全截断点（确保不截断在工具调用中间）；
- 调用 LLM 执行 6-Section 结构化摘要（`SUMMARIZATION_PROMPT`），附带文件修改足迹；
- 追加一条 `compaction` entry（包含 `summary`、`firstKeptEntryId`、`tokensBefore`），并在内存上下文将前面历史替换为 `CompactionSummaryMessage`。

---

## 三、模型、思考等级与凭证控制体系

### 3.1 `/model [provider/model]`（模型动态切换）

1. **3 级匹配解析瀑布流**：
   - 级别 1（精确 `provider/model`）：如 `openai/gpt-4o`、`antigravity/gemini-3.8-flash`；
   - 级别 2（斜杠拆分模糊匹配）：如 `deepseek/chat` $\to$ `deepseek/deepseek-chat`；
   - 级别 3（裸模型 ID 匹配）：在全量可用模型中查找，若存在唯一匹配则命中，若歧义（如多家都有 `gpt-4o`）则提示指定 Provider。
2. **会话状态固化**：
   - 切换成功后，向 session 写入 `{"type": "model_change", "provider": "...", "modelId": "..."}`；
   - 若用户在模型选择器按 `Ctrl+S`，同步调用 `settings.default_model` 持久化至 `~/.my-pi-agent/settings.json`。

### 3.2 `/thinking [level]`（思考深度动态调节）

1. **档位定义**：`off`、`minimal`、`low`、`medium`、`high`、`xhigh`、`max`。
2. **写入会话**：向 session 写入 `{"type": "thinking_level_change", "thinkingLevel": "..."}`。
3. **不同 Provider 的底层参数映射**：
   - **OpenAI / DeepSeek**：映射至 `reasoning_effort: "low" | "medium" | "high"`（`off` 则不传）；
   - **Anthropic**：
     - 若支持自适应思考：`thinking: {type: "adaptive"}, output_config: {effort: "low"|"medium"|"high"}`；
     - 若为预算思考：`thinking: {type: "enabled", budget_tokens: N}`（`minimal: 1024`, `low: 2048`, `medium: 8192`, `high: 16384`）；
     - `off`：`thinking: {type: "disabled"}`；
   - **Google Gemini**：
     - Gemini 3 系列：`thinkingConfig: {includeThoughts: true, thinkingLevel: "LOW" | "HIGH"}`；
     - Gemini 2 系列：`thinkingConfig: {includeThoughts: true, thinkingBudget: N}`（`off` 则 `thinkingBudget: 0`）。

### 3.3 `/logout [provider]`（凭据注销与清理）

- 若无参数：列出当前 `auth.json` 中保存了凭证的 Provider 列表供选择；
- 若有参数（如 `/logout deepseek`）：
  - 在 `FileLock` 保护下从 `~/.my-pi-agent/auth.json` 中安全删除该 Provider 字段；
  - 原子替换保存；
  - 提示用户：`"已清除 deepseek 的本地存储凭据。工作区 .env 中的环境变量保持不变。"`

---

## 四、资源热重载与项目安全信任

### 4.1 `/reload`（资源热重载）

在不重启终端的情况下，重新扫描并热重载以下 6 大类资源：

1. **`Settings`**：重新合并全局 `~/.my-pi-agent/settings.json` 与当前项目级配置；
2. **`Project Context`**：重新读取当前工作区的 `AGENTS.md`、`CLAUDE.md` 与 `README.md` 并刷新系统提示词模板；
3. **`Skills`**：重新扫描全局 `skills/`、项目级 `skills/` 与 `.agents/skills/`；
4. **`Prompt Templates`**：重新扫描 `prompts/` 下的 Markdown 模板；
5. **`Extensions`**：清空模块缓存并重新加载 Python 扩展；
6. **输出格式化报告**：在屏幕打印重载摘要与命名冲突检测（如：`✓ Reloaded 12 skills, 4 templates, updated AGENTS.md`）。

### 4.2 `/trust [status]`（项目安全信任）

1. **信任存储**：`~/.my-pi-agent/trust.json`，结构为 `{"/abs/path/to/project": true | false}`。
2. **向上继承算法**：
   - 检查当前 `cwd` 是否在 `trust.json` 中；
   - 若未配置，逐级向上检索父级目录（Trust Parent Folder 机制）；
   - 只要某个祖先目录被信任，其所有子仓库默认信任。
3. **安全门禁**：
   - 未信任项目：拒绝读取项目级 `.my-pi-agent/settings.json` 与项目级可执行扩展代码，防御克隆开源仓库被植入恶意脚本。

---

## 五、输入行即时宏扩展系统 (Input Bar Macros)

### 5.1 本地命令宏：`!command` vs `!!command`

```text
用户输入
   │
   ├── 以 "!" 开头? ───────────────────────────────────────────────┐
   │                                                               │
   ├── [是] 检查是否以 "!!" 开头                                    │ [否]
   │       ├── [!cmd]  isExcluded = false, role: bashExecution     ▼
   │       │          输出包装为 ```ran ...```，转化为 user 消息进入 LLM 上下文  普通提问
   │       │
   │       └── [!!cmd] isExcluded = true, role: bashExecution
   │                  终端屏幕打印，存盘记录，但 convertToLlm 返回 None (不入模型上下文)
```

1. **编辑器动态视觉变色**：
   - 当用户在输入框打出开头的 `!` 时，TUI 输入框边框颜色实时切换为橙黄色（Bash Mode 指示色）；
   - 按 `Esc` 或退格删除 `!`，立刻恢复默认的思考状态色。
2. **`!command`（进上下文）**：
   - 提取命令内容，调用 Shell 执行并捕获输出；
   - 在转录本生成消息实体：`{"role": "bashExecution", "command": cmd, "output": out, "excludeFromContext": false}`；
   - 模型协议转换层将其转换为标准 `role: "user"` 消息：

     ````markdown
     Ran `git status`
     ```text
     On branch main
     nothing to commit, working tree clean
     ```
     ````

   - 模型在下一次推理时可直接基于该命令输出进行分析。
3. **`!!command`（静默执行，不进上下文）**：
   - 生成消息实体时标记 `excludeFromContext: true`；
   - 在 TUI 界面上渲染该次输出（以便开发者肉眼查看）；
   - 但在向大模型发送上下文（`_provider_context`）时，**完全丢弃该条消息**，实现 0 Token 消耗的本地快速探查。

---

### 5.2 技能展开宏：`/skill:<name> [args]`

1. **识别机制**：输入文本以 `/skill:` 开头；
2. **提取与解包**：
   - 提取 `name = text.split(" ")[0].slice(7)`；
   - 提取 `args = text.slice(first_space + 1)`；
   - 从 `SkillManager` 提取对应 `SKILL.md`，剥离 YAML Frontmatter，仅保留正文；
3. **XML 标准封装格式**：

   ```markdown
   <skill name="deploy" location="D:/code/.../SKILL.md">
   References are relative to D:/code/...

   # Deploy Procedure
   ...
   </skill>

   staging --dry-run
   ```

4. **前端卡片渲染**：TUI 中将其收缩为精美的 `[skill: deploy]` 可折叠徽章，参数作为跟随用户消息清晰呈现。

---

### 5.3 模板展开宏：`/<template> [args]`

1. **匹配机制**：以 `/` 开头且非内置 Slash 命令的输入，尝试匹配 `prompts/<template>.md`；
2. **Bash 风格传参分词**：
   - 严格支持单双引号包裹：`/review "src/main.py" 'arg with space' 123`；
   - 解析出 `args = ["src/main.py", "arg with space", "123"]`；
3. **变量替换语法全集**：
   - `$1`, `$2`, `$N`：位置参数（缺省替换为空串）；
   - `$@`, `$ARGUMENTS`：全部参数空格连接；
   - `${N:-default}`：带默认值的位置参数；
   - `${@:-default}`：无参时的全局默认值；
   - `${@:N}`：从第 N 个参数开始截取到末尾（Slicing）；
   - `${@:N:L}`：从第 N 个参数开始截取 L 个。

---

## 六、stdio JSON-RPC 2.0 扩展方法规范

前端 Node.js TUI 与 Python 后端通过以下新增的 RPC 方法进行通信：

| Method | Request Params | Response Result | 语义说明 |
| :--- | :--- | :--- | :--- |
| **`session_new`** | `{}` | `{"status": "ok", "session_id": "...", "session_file": "..."}` | 结束当前会话并开启全新空白 Session |
| **`session_list`** | `{"all_projects": false}` | `{"sessions": [{"id": "...", "name": "...", "modified": 178..., "message_count": 12}]}` | 列出当前工作区的历史会话列表 |
| **`session_resume`** | `{"session_id": "..."}` | `{"status": "ok", "session_id": "...", "messages": [...]}` | 切换并载入指定历史会话 |
| **`session_name`** | `{"name": "新标题"}` | `{"status": "ok", "name": "新标题"}` | 设置当前会话标题，写入 `session_info` |
| **`session_tree`** | `{}` | `{"nodes": [...], "active_leaf_id": "...", "root_id": "..."}` | 获取当前会话的完整 DAG 节点拓扑 |
| **`session_branch`** | `{"target_id": "...", "summarize": false}` | `{"status": "ok", "leaf_id": "...", "editor_text": "..."}` | 切换活动分支或回退，返回回填输入框文本 |
| **`session_fork`** | `{"entry_id": "..."}` | `{"status": "ok", "new_session_id": "...", "prompt_text": "..."}` | 从历史某点分叉开辟新会话文件 |
| **`session_clone`** | `{}` | `{"status": "ok", "new_session_id": "..."}` | 将当前分支完整克隆为新会话 |
| **`session_compact`** | `{"instructions": "重点总结测试"}` | `{"status": "ok", "tokens_before": 15000, "tokens_after": 3200}` | 触发手动上下文压缩 |
| **`shell_exec`** | `{"command": "git status", "exclude_from_context": false}` | `{"status": "ok", "output": "...", "exit_code": 0}` | 执行 `!cmd` 或 `!!cmd` |
| **`model_switch`** | `{"provider": "...", "model": "...", "persist": false}` | `{"status": "ok", "model": "..."}` | 切换当前模型，支持写入 settings 默认值 |
| **`thinking_set`** | `{"level": "high", "persist": false}` | `{"status": "ok", "level": "high"}` | 切换思考深度，写入 session 记录 |
| **`auth_logout`** | `{"provider": "deepseek"}` | `{"status": "ok", "provider": "deepseek"}` | 从 `auth.json` 抹除凭证 |
| **`resource_reload`** | `{}` | `{"status": "ok", "summary": "Reloaded 12 skills..."}` | 热重载所有资源并返回变更摘要 |
| **`trust_set`** | `{"trusted": true, "parent": false}` | `{"status": "ok", "decision": "trusted"}` | 记录当前目录或父目录的信任决策 |

---

## 七、CLI 启动参数规范对齐

统一对齐 Python 内核与 `tui/bin/my-agent.js` 的命令行参数：

```text
my-agent [options] [prompt]

选项列表：
  -c, --continue            一键续接当前项目最近一次历史会话
  -r, --resume              启动时直接打开交互式会话选择器
  --new-session             强制开启全新会话 (默认)
  -n, --name <title>        启动时直接为该会话命名
  -m, --model <model>       指定使用的模型 (例如 deepseek-chat, gemini-3.8-flash)
  --thinking <level>        指定思考预算等级 (off/minimal/low/medium/high/max)
  --no-session              内存无痕沙箱模式 (不持久化 session 文件)
  -w, --workspace <dir>     指定操作的工作区目录 (默认当前目录)
  --mode <mode>             权限安全模式: review (默认) | yolo | strict
  -h, --help                查看 CLI 帮助说明
```

---

## 八、实施分步规划 (Implementation Phases)

1. **Phase 1: 内核会话命令与分支漫游 RPC (`rpc_server.py` + `session/`)**：
   - 接入 `session_new`, `session_list`, `session_resume`, `session_name`, `session_tree`, `session_branch`, `session_fork`, `session_clone`, `session_compact`；
   - 编写离线测试覆盖全部状态流转与分支回退。
2. **Phase 2: 输入行宏系统与 Shell 通道 (`interactive-mode.js` + `rpc_server.py`)**：
   - 实现 `!cmd`（入上下文）与 `!!cmd`（静默探查）前置解析与执行管道；
   - 实现 `/skill:<name>` 与 `/<template>` 变量展开。
3. **Phase 3: 模型、思考、凭证与重载 (`model_switch`, `thinking_set`, `auth_logout`, `resource_reload`, `trust_set`)**：
   - 接入多 Provider 思考预算映射；
   - 实现凭据安全抹除与资源热重载汇报。
4. **Phase 4: TUI 交互模态与补全集成 (`tui/src/app.ts`)**：
   - 挂载全套 Slash 命令自动补全；
   - 实现 `/resume` 会话挑选浮层与 `/tree` 分支 ASCII 渲染。
5. **Phase 5: CLI 参数对齐与端到端全量回归**：
   - 打通 `-c`, `-r`, `-n`, `--thinking`, `--no-session` 启动参数；
   - 跑完全库 615+ Python 与 Node 自动化测试矩阵。
