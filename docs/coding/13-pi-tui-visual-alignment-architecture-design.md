# my-pi-agent 基于 Pi 原厂高保真终端视觉体系设计规范

- **文档名称**：Pi 原厂高保真终端视觉、容器层叠与组件渲染架构设计规范
- **归档路径**：`docs/coding/13-pi-tui-visual-alignment-architecture-design.md`
- **日期**：2026-09-14
- **状态**：设计完成，已通过 Pi 官方 UI 源码逆向审校
- **目标包**：
  - `tui/`（`app.ts`、`components/`、`theme/`、`tui/bin/my-agent.js`）

---

## 一、设计哲学与重构目标 (Vision & Principles)

在完成了全套底层后端 RPC 协议、集中式会话隔离与命令对齐后，当前的终端交互界面存在明显的“粗糙感”与“字符乱码缺陷”：

- 使用了容易在 Windows 控制台降级为乱码问号（``）的花哨 Emoji；
- 组件装配顺序倒置，Footer 被夹在聊天区和输入框之间，割裂了界面；
- 缺少 Pi 原厂标志性的极简启动 Banner 横幅；
- 状态栏缺乏双行左右分栏排版，显得拥挤单调。

### 1.1 核心设计铁律 (Golden Rules)

1. **零花哨 Emoji 污染（Zero Emoji Clutter）**：
   彻底杜绝在状态行使用 Windows 终端无法稳定对齐宽度的彩色 Emoji（`📁`, `🌲`, `🤖`, `💰`, `⏱️`）。全量采用 ASCII-safe 或成熟 Unicode 紧凑排版符号（`~`, `(main)`, `↑`, `↓`, `✓`, `✗`）；
2. **像素级 Pi 容器拓扑（100% Pi Hierarchy Fidelity）**：
   严格对齐 Pi 原厂 `TuiMainScreen` 的自顶向下层级：
   `1. 顶部 Header ➔ 2. 中间滚动 Chat ➔ 3. 底部 Editor ➔ 4. 最底端常驻 Footer`；
3. **CSI 2026 垂直同步刷新屏障**：
   依托 `@earendil-works/pi-tui` 的同步刷新机制（`\x1b[?2026h` / `\x1b[?2026l`），保障多行渲染零撕裂、零闪烁；
4. **柔和低饱和度调色盘**：
   全面继承 Pi 官方 24-bit TrueColor `dark.json` 色卡，文字以 muted (`#808080`)、dim (`#666666`) 柔和呈现，避免刺眼的高亮撞色。

---

## 二、Pi 官方视觉实现深度调研 (Pi 源码实证)

经三路 Subagent 深入反编译调研 `@earendil-works/pi-coding-agent/dist/modes/interactive/`，提炼出以下核心事实：

### 2.1 容器装配与屏幕层级 (`interactive-mode.js`)

- `TuiMainScreen` 上的子组件严格按照线性次序挂载：
  1. `documentContainer`（内部包裹 `headerContainer`、`loadedResourcesContainer`、`chatContainer`）；
  2. `pendingMessagesContainer`（暂存的 Steer / Followup / Bash 执行指示）；
  3. `statusContainer`（Spinner 动画）；
  4. `editorContainer`（承载 `CustomEditor` 或动态模态弹窗）；
  5. `footerContainer`（承载 `FooterComponent`）。
- **关键布局原则**：Editor 位于 Footer **上方**。Editor 的下水平边框（`renderBottomBorder`）直接作为与 Footer 之间的天然分界线；Footer 自身不画上边框。

### 2.2 状态底栏 Footer 双行左右分栏排版 (`footer.js`)

- **第 1 行（工作区上下文）**：
  - 调用 `formatCwdForFooter(cwd, home)` 将用户主目录收缩为 `~`；
  - 若处于 Git 仓库，追加 `(${branch})`；
  - 若会话已命名，追加 `• ${sessionName}`；
  - 全行使用 `theme.fg("dim", ...)` 柔和灰色渲染。
- **第 2 行（统计指标与模型分栏）**：
  - **左侧数据**：`↑input ↓output Rcache Wcache $cost context%/window`，纯文字前缀（`↑`、`↓`、`R`、`W`、`$`），零 Emoji；
  - **右侧对齐**：`(${provider}) ${modelName} • ${thinkingLevel}`；
  - **空间填充算法**：使用 `padding = " ".repeat(width - visibleWidth(left) - visibleWidth(right))` 动态填充中间空格；
  - **ANSI Reset 独立染色保护**：将左侧与右侧及中间空格分别调用 `theme.fg("dim", ...)`，防止左侧上下文百分比的高亮色（黄色/红色）的 Reset 代码破坏右侧的暗灰风格。

### 2.3 消息与卡片组件规范 (`user-message.js`, `assistant-message.js`, `tool-execution.js`)

- **UserMessageComponent**：
  - 外层由 `Box(paddingX=1, paddingY=1)` 包裹，背景色为 `userMessageBg`（`#343541` 暗岩灰气泡）；
  - 内层 Markdown 文本为 `userMessageText`（`#d4d4d4`）。
- **AssistantMessageComponent**：
  - **没有外层实心 Box**！直接以普通 Markdown 流式输出，保证终端原生阅读感；
  - **思考块（Thinking Block）**：使用 `theme.italic(theme.fg("thinkingText", "Thinking..."))` 斜体暗灰（`#808080`），默认折叠或点击/快捷键展开。
- **ToolExecutionComponent**：
  - 外层使用 `Box(1, 1, bgFn)`：
    - 执行中：`toolPendingBg` (`#282832` 深海暗蓝灰)，显示实时计时 `Elapsed 1.2s`；
    - 执行成功：`toolSuccessBg` (`#283228` 深橄榄暗绿灰)，显示 `Took 0.3s`；
    - 执行失败：`toolErrorBg` (`#3c2828` 深铁锈暗红灰)；
  - 标题格式：`✓ read (src/app.ts)` 或 `$ git status`；
  - 结果超长截断：`... (N more lines, to expand)`。

---

## 三、全新 TUI 视觉架构全景设计

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ [HeaderComponent]                                                            │
│ my-pi-agent v0.1.0                                                           │
│ Esc interrupt · Ctrl+C clear/exit · / commands · ! bash · Ctrl+O more        │
│ Press Ctrl+O to show full startup help and loaded resources.                 │
│                                                                              │
│ [ChatContainer]                                                              │
│ ╭─ 用户 ───────────────────────────────────────────────────────────────────╮ │
│ │ 帮我重构 paths.py                                                        │ │
│ ╰──────────────────────────────────────────────────────────────────────────╯ │
│                                                                              │
│ 正在为您分析代码路径结构...                                                  │
│                                                                              │
│ ╭─ ⚙️ read (src/my_coding_agent/paths.py) ──────────────────────────────────╮ │
│ │ class AgentPaths:                                                        │ │
│ │     home: Path = ...                                                     │ │
│ │ ... (42 more lines, Ctrl+O to expand)                                    │ │
│ ╰─ Took 0.1s ──────────────────────────────────────────────────────────────╯ │
│                                                                              │
│ 已定位到路径定义。                                                           │
├──────────────────────────────────────────────────────────────────────────────┤
│ [Editor (CustomEditor)]                                                      │
│ ── ⠋ 思考计算中 (1.2s) ───────────────────────────────────────────────────── │
│ > 输入你的需求...                                                            │
├──────────────────────────────────────────────────────────────────────────────┤
│ [FooterComponent]                                                            │
│ ~/code/python/my-pi-agent (main) • 重构路径                                  │
│ ↑3.2k ↓450 $0.006 1.8%/128k (auto)             (openai) deepseek-flash • off │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 四、核心组件实现规范

### 4.1 `FooterComponent` 双行左右分栏排版 (`tui/src/components/footer.ts`)

```typescript
import * as os from "node:os";
import * as path from "node:path";
import { Container, Text, visibleWidth, truncateToWidth } from "@earendil-works/pi-tui";
import { theme } from "../theme/theme.js";

export interface FooterData {
  workspace: string;
  gitBranch?: string;
  sessionName?: string;
  providerName?: string;
  modelName?: string;
  thinkingLevel?: string;
  inputTokens?: number;
  outputTokens?: number;
  totalTokens?: number;
  contextWindow?: number;
  costUsd?: number;
  elapsedSeconds?: number;
  isBusy?: boolean;
}

export class FooterComponent extends Container {
  private data: FooterData;

  constructor(initialData?: Partial<FooterData>) {
    super();
    this.data = {
      workspace: process.cwd(),
      modelName: "default",
      thinkingLevel: "off",
      inputTokens: 0,
      outputTokens: 0,
      totalTokens: 0,
      contextWindow: 128000,
      costUsd: 0,
      ...initialData,
    };
  }

  public update(partial: Partial<FooterData>): void {
    this.data = { ...this.data, ...partial };
  }

  public render(width: number): string[] {
    // 1. 第一行：工作区路径 (~ 折叠) + 分支 + 会话名
    let pwd = this.formatCwd(this.data.workspace);
    if (this.data.gitBranch) {
      pwd += ` (${this.data.gitBranch})`;
    }
    if (this.data.sessionName) {
      pwd += ` • ${this.data.sessionName}`;
    }
    const line1 = truncateToWidth(theme.fg("dim", pwd), width, theme.fg("dim", "..."));

    // 2. 第二行：左侧 Token 与指标
    const statsParts: string[] = [];
    if (this.data.inputTokens && this.data.inputTokens > 0) {
      statsParts.push(`↑${this.formatTokens(this.data.inputTokens)}`);
    }
    if (this.data.outputTokens && this.data.outputTokens > 0) {
      statsParts.push(`↓${this.formatTokens(this.data.outputTokens)}`);
    }
    if (this.data.costUsd && this.data.costUsd > 0) {
      statsParts.push(`$${this.data.costUsd.toFixed(3)}`);
    }

    const percent = ((this.data.totalTokens || 0) / (this.data.contextWindow || 128000)) * 100;
    const percentStr = `${percent.toFixed(1)}%/${this.formatTokens(this.data.contextWindow || 128000)}`;
    const contextColor = percent > 90 ? "error" : percent > 70 ? "warning" : "dim";
    statsParts.push(theme.fg(contextColor, percentStr));

    if (this.data.elapsedSeconds && this.data.elapsedSeconds > 0) {
      statsParts.push(theme.fg("dim", `${this.data.elapsedSeconds.toFixed(1)}s`));
    }
    if (this.data.isBusy) {
      statsParts.push(theme.fg("warning", "⠋"));
    }

    const statsLeft = statsParts.join(" ");

    // 3. 第二行：右侧模型与思考深度 (provider) model • thinking
    const prov = this.data.providerName ? `(${this.data.providerName}) ` : "";
    const model = this.data.modelName || "default";
    const thinking = this.data.thinkingLevel && this.data.thinkingLevel !== "off"
      ? ` • ${this.data.thinkingLevel}`
      : "";
    const rightSide = `${prov}${model}${thinking}`;

    // 4. 动态计算填充间距并右对齐
    const leftWidth = visibleWidth(statsLeft);
    const rightWidth = visibleWidth(rightSide);
    const minPadding = 2;

    let line2: string;
    if (leftWidth + minPadding + rightWidth <= width) {
      const padLen = width - leftWidth - rightWidth;
      line2 = theme.fg("dim", statsLeft) + " ".repeat(padLen) + theme.fg("dim", rightSide);
    } else {
      line2 = truncateToWidth(theme.fg("dim", statsLeft), width, "...");
    }

    return [line1, line2];
  }

  private formatCwd(dir: string): string {
    const home = os.homedir();
    const resolved = path.resolve(dir);
    if (resolved === home) return "~";
    if (resolved.startsWith(home)) {
      return "~" + resolved.slice(home.length).replace(/\\/g, "/");
    }
    return resolved.replace(/\\/g, "/");
  }

  private formatTokens(count: number): string {
    if (count < 1000) return String(count);
    if (count < 10000) return `${(count / 1000).toFixed(1)}k`;
    if (count < 1000000) return `${Math.round(count / 1000)}k`;
    return `${(count / 1000000).toFixed(1)}M`;
  }
}
```

---

### 4.2 `HeaderComponent` 极简启动横幅 (`tui/src/components/header.ts`)

```typescript
import { Container, Spacer, Text } from "@earendil-works/pi-tui";
import { theme } from "../theme/theme.js";

export class HeaderComponent extends Container {
  constructor(version = "0.1.0") {
    super();

    this.addChild(new Spacer(1));

    const logo = theme.bold(theme.fg("accent", "my-pi-agent")) + theme.fg("dim", ` v${version}`);
    const hints = [
      theme.fg("dim", "Esc") + theme.fg("muted", " interrupt"),
      theme.fg("dim", "Ctrl+C") + theme.fg("muted", " clear/exit"),
      theme.fg("dim", "/") + theme.fg("muted", " commands"),
      theme.fg("dim", "!") + theme.fg("muted", " bash"),
      theme.fg("dim", "Ctrl+O") + theme.fg("muted", " expand"),
    ].join(theme.fg("muted", " · "));

    const onboarding = theme.fg("dim", "欢迎使用 my-pi-agent！输入需求或按 / 开启命令菜单。");

    const content = `${logo}\n${hints}\n\n${onboarding}`;
    this.addChild(new Text(content, 1, 0));
    this.addChild(new Spacer(1));
  }
}
```

---

### 4.3 `AgentApp` 容器挂载拓扑纠偏 (`tui/src/app.ts`)

```typescript
// 严格对齐 Pi 原厂视口层叠顺序：
this.header = new HeaderComponent();
this.chatContainer = new Container();
this.editor = new Editor(this.tui, editorTheme);
this.footer = new FooterComponent({
  workspace: options.workspace || process.cwd(),
  modelName: options.model || "default",
});

// 挂载顺序（关键纠偏！）：
this.tui.addChild(this.header);        // 1. 顶部极简横幅
this.tui.addChild(this.chatContainer);  // 2. 中间消息与卡片流动区
this.tui.addChild(this.editor);         // 3. 底部输入框 (自带上下水平边框)
this.tui.addChild(this.footer);         // 4. 最底端常驻状态栏 (无上边框，以输入框下边为分界)
```

---

### 4.4 `ToolExecutionComponent` 卡片背景与计时微调

- 将外框标题 Emoji 清除，统一采用 Pi 原厂样式：
  - 正在执行：`theme.fg("warning", "⠋")` + `read src/app.ts` + `Elapsed 1.2s`；
  - 执行成功：`theme.fg("success", "✓")` + `read src/app.ts (0.1s)`；
  - 执行失败：`theme.fg("error", "✗")` + `read src/app.ts (失败)`。
- 卡片背景色严格遵循 `toolPendingBg` (`#282832`) / `toolSuccessBg` (`#283228`) / `toolErrorBg` (`#3c2828`)。

---

## 五、实施与验证计划 (Implementation & Verification)

1. **Step 1**: 创建 `tui/src/components/header.ts`，导出 `HeaderComponent`；
2. **Step 2**: 重构 `tui/src/components/footer.ts`，彻底消灭 Emoji，实现双行左右分栏与 ANSI 染色保护；
3. **Step 3**: 调整 `tui/src/app.ts` 的子组件添加顺序，将 Footer 移至 Editor 下方，在顶部接入 Header；
4. **Step 4**: 优化 `tui/src/components/tool-execution.ts` 卡片指示符；
5. **Step 5**: 运行 `npm run build --prefix tui && npm test`，验证所有 TUI 测试 100% 绿灯；
6. **Step 6**: 运行全库 `uv run python -m pytest`，确保后端与 RPC 完全兼容无回归。
