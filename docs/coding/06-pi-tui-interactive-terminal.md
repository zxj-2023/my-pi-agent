# Pi-TUI 交互式终端与表现层规范 (`tui`)

- **定位**：100% 对标 Pi 原厂体验的独立终端表现层与交互状态机 (`tui/src/`)
- **设计标杆**：`@earendil-works/pi-coding-agent`、`@earendil-works/pi-tui` (Mario Zechner)
- **核心组件**：`CustomEditor` 顶部边框嵌入式转圈动效、四大交互选择器、`CompactionSummaryMessage` 折叠卡片、思考深度快捷键轮转

---

## 一、表现层架构与视口拓扑

前端完全基于 `@earendil-works/pi-tui` 微内核构建，采用与 Pi 原厂完全一致的自顶向下容器挂载拓扑，结合终端同步输出序列（CSI 2026）消除页面重绘抖动与文字闪烁：

```text
+-------------------------------------------------------------------------------+
| HeaderComponent: Logo 标识、版本号与全局快捷键引导行                         |
+-------------------------------------------------------------------------------+
| ChatContainer (滚动视口 Transcript):                                         |
|   - UserMessageComponent: 用户提问气泡                                       |
|   - AssistantMessageComponent: 思维链 (Thinking, Ctrl+O) + 实时 Markdown 正文|
|   - ToolExecutionComponent: 工具执行参数与耗时卡片 (Ctrl+O 展开结果)          |
|   - CompactionSummaryMessageComponent: [compaction] 紧凑卡片 (Ctrl+O 展开)    |
+-------------------------------------------------------------------------------+
| StatusContainer: 历史状态备用插槽                                             |
+-------------------------------------------------------------------------------+
| EditorContainer:                                                              |
|   CustomEditor (嵌入式顶部边框 ── ⠸ Working ── 与自动补全列表)               |
+-------------------------------------------------------------------------------+
| FooterComponent (双行自适应状态栏):                                           |
|   左: 工作区绝对路径 • 分支 • 会话名称                                        |
|   右: ↑输入 ↓输出 R缓存读 W缓存写 CH% 费用 上下文% 模型 • 思考等级            |
+-------------------------------------------------------------------------------+
```

---

## 二、`CustomEditor` 顶部边框嵌入式 `── ⠸ Working ──` 转圈动效

在官方 Pi 中，状态指示器并非一条占位的普通屏幕文本，而是**精巧地嵌入在用户输入框（Editor）的顶部边框线中央**：

```text
── ⠸ Working ───────────────────────────────────────────────────────────────────
  输入框在此，光标持续处于可编辑待命状态...
─────────────────────────────────────────────────────────────────────────────────
```

### 1. 实现机制与算法 (`CustomEditor.renderTopBorder`)

`CustomEditor` 继承自 `@earendil-works/pi-tui` 的 `Editor`，重写边框生成算法：

- **挖槽算法**：当 `workingStatusIndicator` 激活时，计算当前指示器的实际视觉宽度（包含 80ms 轮转的 Braille 盲文帧 `⠋` ➔ `⠙` ➔ `⠹` ➔ `⠸` ➔ `⠼` ➔ `⠴` ➔ `⠦` ➔ `⠧` ➔ `⠇` ➔ `⠏`）；
- **动态拼装**：输出 `borderColor("── ") + status + borderColor(" ────────...")`；
- **自愈恢复**：轮次结束（`turn_end` 或 `agent_end`）时，调用 `clearStatusDisplay()`，顶部边框瞬时平滑恢复为完整的横线 `────────────────────────────`；
- **安全防悬挂**：内部动画定时器严格调用 `timer.unref()`，绝不阻碍 Node 进程的正常退出与测试执行。

---

## 三、思考预算深度与动态边框颜色映射

系统支持通过快捷键即时循环切换思考预算（Reasoning Effort）：

- **快捷键绑定**：支持 `Shift+Tab`（`\x1b[Z`）与 `Ctrl+T`；
- **自适应夹逼算法 (`getSupportedThinkingLevels`)**：
  - 非推理模型（如普通 GPT-4o、Claude 3.5 Sonnet）自动锁定在 `off`；
  - Google Gemini / Antigravity 夹逼至 `high`；
  - OpenAI o-系列支持 `low` / `medium` / `high`；
  - Claude 3.7 Sonnet 支持从 `off` 至 `max` 全档位；
- **动态边框着色**：根据思考等级（`off` ➔ 灰暗色，`high` ➔ 强调青色，`max` ➔ 明亮紫色，Shell 命令 `!` ➔ 警告黄色）实时重绘输入框边框。

---

## 四、全套交互式全屏选择器 (Modal Selectors)

所有选择器在激活时通过 `showSelector` 独占键盘输入事件，按 `Esc` 退出并归还焦点：

1. **`ModelSelectorComponent` (/model 或 Ctrl+L)**：
   - 动态拉取远程发现的模型列表；
   - 包含 Provider 徽章（`[openai]`, `[anthropic]`, `[deepseek]`, `[antigravity]`）；
   - 支持模糊搜索与按 `Tab` 切换范围（全部模型 vs 已配置 Provider 模型）；
   - 支持按 `Ctrl+S` 将当前选中模型持久化为默认配置。
2. **`SessionSelectorComponent` (/resume 或 Ctrl+R)**：
   - 呈现历史会话列表，展示消息条数、更新时间；
   - 支持对分叉会话呈现树状连线（`│`, `├─`, `└─`）；
   - 支持按 `Ctrl+D` 触发二次确认删除，内建**活跃会话删除拦截防御**。
3. **`ThinkingSelectorComponent` (/thinking)**：
   - 7 档思考深度可视化选择列表与说明。
4. **`LoginSelectorComponent` (/login)**：
   - 交互式配置各 Provider API Key；
   - 针对 Antigravity 呈现两段式向导，明确展示 `auth.json` 磁盘物理路径与一键绑定指引。

---

## 五、可折叠结构化消息组件

- **`CompactionSummaryMessageComponent`**：
  当执行 `/compact` 或发生上下文自动压缩时，不倾倒数千字摘要，而是呈现 `[compaction] Compacted from X tokens (Ctrl+O to expand)` 紧凑卡片，按 `Ctrl+O` 无缝展开阅读 Markdown 详情；
- **`AssistantMessageComponent`**：
  思维链（Thinking）默认以 `◈ 思考过程 (N 字符，按 Ctrl+O 展开)` 折叠呈现，正文支持流式 Markdown、语法高亮代码块与错误警告框；
- **`ToolExecutionComponent`**：
  工具入参与局部运行日志默认收敛，支持 `Ctrl+O` 展开全量执行日志或查看生成的 Unified Diff。

---

## 六、输入行即时宏扩展引擎 (MacroEngine)

终端输入行内置了即时宏语法扩展引擎（`MacroEngine`，位于 `src/my_coding_agent/macro.py`），在用户按下回车提交提示词前完成本地语法展开，兼具命令行效率与模型上下文精确控制：

### 1. Shell 宏执行管道 (`!cmd` 与 `!!cmd`)

- **上下文注入宏 (`!cmd`)**：
  在工作区同步执行指定的 Shell 命令，捕获输出与退出码，格式化为代码块自动追加至当前轮次的用户提问中：

  ```text
  $ git status (已加入上下文) (Exit: 0)
  ```text
  modified: src/app.ts
  ```

  ```
  模型可直接读取最新命令执行现场，避免用户手动复制粘贴。
- **静默探查宏 (`!!cmd`)**：

  执行命令并在视口即时回显输出，但内部打上 `exclude_from_context: true` 标记，**彻底排除在模型上下文之外**。适用于本地环境试探、临时文件查看或清屏操作，零 Token 消耗，绝不污染对话历史。
- **实时边框变色反馈**：
  当用户在输入框中以 `!` 开头键入时，`CustomEditor` 边框颜色即时动态响应切换为预警黄色（`warning`），提供极高的操作确定感。

### 2. 技能即时展开宏 (`/skill:<name> [args]`)

当用户输入形如 `/skill:review target=src/` 时，`MacroEngine` 自动：

1. 联动 `SkillManager` 寻址并加载项目本地或全局 `~/.my-pi-agent/skills/<name>/SKILL.md`；
2. 剥离 YAML Frontmatter 元数据，将主体工作流规范包装为高辨识度的标准 XML 容器：

   ```xml
   <skill name="review">
   # Review Guidelines
   ...步骤与检查清单...
   </skill>
   target=src/
   ```

3. 一并注入提示词尾部，使模型严格遵循预设的工程技能规范执行任务。

### 3. 提示词模板展开宏 (`/<template> [args]`)

支持从项目或全局 `prompts/<template>.md` 加载通用提示词模板：

1. **参数解析**：使用标准 POSIX 规范的 `shlex.split` 进行带引号参数切分；
2. **变量替换**：将模板中的 `$1`, `$2` 等占位符替换为具体入参，`$@` / `$*` 替换为全量追加参数；
3. 允许开发者将复杂的日常指令（如重构、单测生成、架构审计）沉淀为参数化模版，实现一键展开执行。
