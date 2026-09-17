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
