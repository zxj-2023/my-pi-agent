# my-pi-agent 基于 Pi 原厂高保真终端视觉体系实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 依据 `docs/coding/13-pi-tui-visual-alignment-architecture-design.md`，对 `tui/` 前端表现层进行像素级视觉重构，彻底消除导致终端乱码的彩色 Emoji，对齐 Pi 原厂的容器自顶向下挂载拓扑（Header ➔ Chat ➔ Editor ➔ Footer），实现双行左右自适应分栏状态栏、极简启动横幅以及无缝的卡片暗色视觉系统。

**Architecture:**

- **横幅组件 (`tui/src/components/header.ts`)**：实现 `HeaderComponent`，在屏幕顶部渲染 Pi 标志性的极简 Logo、版本号与热键提示。
- **状态底栏 (`tui/src/components/footer.ts`)**：彻底剔除 Emoji，第 1 行输出 `pwd (branch) • sessionName`，第 2 行输出左侧紧凑指标（`↑`, `↓`, `R`, `W`, `$`, `context%`）与右侧贴边对齐的 `(provider) model • thinking`，采用 ANSI Reset 独立染色保护。
- **工具卡片 (`tui/src/components/tool-execution.ts`)**：剔除 `⚙️` 等宽字符 Emoji，统一采用 Pi 原厂的 `⠋` 动态 Spinner 与 `✓` / `✗` 紧凑符号。
- **容器拓扑纠偏 (`tui/src/app.ts`)**：将原先倒置的 `footer` 调整到 `editor` 正下方（屏幕最底端），并在顶部接入 `header`。

**Tech Stack:** TypeScript, Node.js, `@earendil-works/pi-tui`, ANSI escape sequences.

**Spec:** `docs/coding/13-pi-tui-visual-alignment-architecture-design.md`

## Global Constraints

- **零彩色 Emoji 污染**：状态栏与工具卡片禁止使用跨平台宽度不稳定的宽字符 Emoji，严格采用 ASCII-safe 字符或成熟的 Unicode 紧凑符号（`~`, `(main)`, `↑`, `↓`, `⠋`, `✓`, `✗`）。
- **像素级层级对齐**：Editor 必须位于 Footer 上方，Footer 处于终端视口最底行。
- **Never-Break 测试保证**：现有 13 项前端测试与 643 项 Python 核心测试必须保持 100% 绿灯。

---

## 实施任务总览表 (Overview)

| Task # | 核心任务 | 交付文件 / 模块 | 预估测试 |
| :--- | :--- | :--- | :--- |
| **Task 1** | 极简启动横幅 HeaderComponent 实现 | `tui/src/components/header.ts`<br>`tui/test/header.test.js` | 3 项单测 (新建) |
| **Task 2** | FooterComponent 彻底消灭 Emoji 与双行左右分栏重构 | `tui/src/components/footer.ts`<br>`tui/test/footer.test.js` | 6 项单测 (更新/新建) |
| **Task 3** | ToolExecutionComponent 卡片指示符与样式净化 | `tui/src/components/tool-execution.ts`<br>`tui/test/app.test.js` | 5 项单测 (更新) |
| **Task 4** | AgentApp 容器拓扑纠偏与组件装配集成 | `tui/src/app.ts`<br>`tui/test/app.test.js` | 13 项端到端单测 |
| **Task 5** | 全库编译、前端测试扩充与终极全量回归 | `tui/dist/`<br>`npm test`<br>`uv run python -m pytest` | 全库 650+ 项测试 |

---

## 任务执行细节 (Detailed Tasks)

### Task 1: 极简启动横幅 HeaderComponent 实现

**Files:**

- Create: `tui/src/components/header.ts`
- Create: `tui/test/header.test.js`

**Interfaces:**

- Consumes: `theme` from `../theme/theme.js`, `@earendil-works/pi-tui`
- Produces:

  ```typescript
  export class HeaderComponent extends Container {
    constructor(version?: string);
  }
  ```

- [ ] **Step 1: 编写 `tui/test/header.test.js` 失败测试**

```javascript
import test from "node:test";
import assert from "node:assert/strict";
import { HeaderComponent } from "../dist/components/header.js";

test("HeaderComponent renders app logo and keybinding hints", () => {
  const header = new HeaderComponent("0.1.0");
  assert.ok(header);
  const lines = header.render(80);
  assert.ok(lines.length >= 3, "Header must render at least 3 lines");
  const text = lines.join("\n");
  assert.ok(text.includes("my-pi-agent"));
  assert.ok(text.includes("v0.1.0"));
  assert.ok(text.includes("Esc"));
  assert.ok(text.includes("/"));
});
```

- [ ] **Step 2: 运行测试验证失败**

Run: `node --test tui/test/header.test.js`
Expected: FAIL (`Cannot find module '../dist/components/header.js'`)

- [ ] **Step 3: 实现 `tui/src/components/header.ts`**

```typescript
import { Container, Spacer, Text } from "@earendil-works/pi-tui";
import { theme } from "../theme/theme.js";

export class HeaderComponent extends Container {
  constructor(version = "0.1.0") {
    super();

    this.addChild(new Spacer(1));

    const logo =
      theme.bold(theme.fg("accent", "my-pi-agent")) +
      theme.fg("dim", ` v${version}`);

    const hints = [
      theme.fg("dim", "Esc") + theme.fg("muted", " interrupt"),
      theme.fg("dim", "Ctrl+C") + theme.fg("muted", " clear/exit"),
      theme.fg("dim", "/") + theme.fg("muted", " commands"),
      theme.fg("dim", "!") + theme.fg("muted", " bash"),
      theme.fg("dim", "Ctrl+O") + theme.fg("muted", " expand"),
    ].join(theme.fg("muted", " · "));

    const onboarding = theme.fg(
      "dim",
      "欢迎使用 my-pi-agent！输入需求或按 / 开启命令菜单。",
    );

    const content = `${logo}\n${hints}\n\n${onboarding}`;
    this.addChild(new Text(content, 1, 0));
    this.addChild(new Spacer(1));
  }
}
```

- [ ] **Step 4: 编译并运行测试验证通过**

Run:

```bash
npm run build --prefix tui
node --test tui/test/header.test.js
```

Expected: PASS (100% 绿灯).

---

### Task 2: FooterComponent 彻底消灭 Emoji 与双行左右分栏重构

**Files:**

- Modify: `tui/src/components/footer.ts`
- Create: `tui/test/footer.test.js`

**Interfaces:**

- Consumes: `theme`, `@earendil-works/pi-tui`
- Produces:

  ```typescript
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
    constructor(initialData?: Partial<FooterData>);
    public update(partial: Partial<FooterData>): void;
    public render(width: number): string[];
  }
  ```

- [ ] **Step 1: 编写 `tui/test/footer.test.js` 失败测试**

```javascript
import test from "node:test";
import assert from "node:assert/strict";
import { FooterComponent } from "../dist/components/footer.js";

test("FooterComponent renders dual lines without emoji clutter", () => {
  const footer = new FooterComponent({
    workspace: "D:/code/my-project",
    gitBranch: "main",
    sessionName: "refactor-auth",
    modelName: "deepseek-flash",
    providerName: "openai",
    thinkingLevel: "off",
    totalTokens: 12500,
    contextWindow: 128000,
  });

  const lines = footer.render(100);
  assert.equal(lines.length, 2, "Footer must render exactly 2 lines");

  // Line 1: 路径与分支
  assert.ok(lines[0].includes("my-project"));
  assert.ok(lines[0].includes("(main)"));
  assert.ok(lines[0].includes("refactor-auth"));
  // 严禁包含破损 emoji
  assert.ok(!lines[0].includes("\u{1f4c1}"));
  assert.ok(!lines[0].includes("\u{1f33f}"));

  // Line 2: 左侧统计 + 右侧模型右对齐
  assert.ok(lines[1].includes("128k"));
  assert.ok(lines[1].includes("deepseek-flash"));
  assert.ok(!lines[1].includes("\u{1f916}"));
  assert.ok(!lines[1].includes("\u{1f4ca}"));
});
```

- [ ] **Step 2: 运行测试验证失败**

Run: `node --test tui/test/footer.test.js`
Expected: FAIL (输出包含旧版 Emoji 或行数不匹配)

- [ ] **Step 3: 重构 `tui/src/components/footer.ts`**

实现双行自适应排版、ANSI 独立染色保护、`~` 折叠路径以及紧凑指标（`↑`, `↓`, `$`, `context%`），详见设计规范 §4.1。

- [ ] **Step 4: 编译并运行测试验证通过**

Run:

```bash
npm run build --prefix tui
node --test tui/test/footer.test.js
```

Expected: PASS (100% 绿灯).

---

### Task 3: ToolExecutionComponent 卡片指示符与样式净化

**Files:**

- Modify: `tui/src/components/tool-execution.ts`
- Modify: `tui/test/app.test.js`

**Interfaces:**

- Consumes: `theme`, `@earendil-works/pi-tui`
- Produces: 无 Emoji 污染的极简工具卡片 (`⠋`, `✓`, `✗`)

- [ ] **Step 1: 修改 `tui/src/components/tool-execution.ts`**

- 彻底移除 `⚙️` 和 `\u2699`；
- 执行中状态使用 `theme.fg("warning", "⠋")` + `toolName args` + `Elapsed X.Xs`；
- 执行成功使用 `theme.fg("success", "✓")` + `toolName args (X.Xs)`；
- 执行失败使用 `theme.fg("error", "✗")` + `toolName args (失败)`；
- 保持 `Box(1, 1, bgFn)` 动态背景（`toolPendingBg` / `toolSuccessBg` / `toolErrorBg`）。

- [ ] **Step 2: 运行现有测试验证兼容性**

Run: `npm test`
Expected: 13 passed (全绿).

---

### Task 4: AgentApp 容器拓扑纠偏与组件装配集成

**Files:**

- Modify: `tui/src/app.ts`
- Modify: `tui/test/app.test.js`

**Interfaces:**

- Consumes: `HeaderComponent`, `FooterComponent`, `Editor`, `TuiMainScreen`
- Produces: 纠偏后的四层线性视口结构

- [ ] **Step 1: 调整 `tui/src/app.ts` 容器挂载顺序**

```typescript
// 严格对齐 Pi 原厂挂载次序：
this.header = new HeaderComponent();
this.chatContainer = new Container();
this.editor = new Editor(this.tui, editorTheme);
this.footer = new FooterComponent({
  workspace: options.workspace || process.cwd(),
  modelName: options.model || "default",
});

this.tui.addChild(this.header);        // 1. 顶部极简横幅
this.tui.addChild(this.chatContainer);  // 2. 中间消息滚动区
this.tui.addChild(this.editor);         // 3. 底部输入框 (自带水平边框)
this.tui.addChild(this.footer);         // 4. 最底端常驻状态栏 (无上边框，以输入框底线为分界)
```

- [ ] **Step 2: 在 `AgentApp` 中同步状态至新版 Footer**

在 `handleAgentEvent` 与 `handleUserSubmit` 中更新 Token 消耗明细（`inputTokens`, `outputTokens`, `totalTokens`, `isBusy`）并传递给 `this.footer.update(...)`。

- [ ] **Step 3: 运行前端自动化测试**

Run: `npm test`
Expected: 14 passed (100% 绿灯).

---

### Task 5: 全库编译、前端测试扩充与终极全量回归

**Files:**

- Build: `tui/dist/`
- Verify: 全量 Python 与 TypeScript 测试套件

- [ ] **Step 1: 编译 TUI TypeScript**

Run: `npm run build --prefix tui`
Expected: 0 errors.

- [ ] **Step 2: 执行全量前端测试套件**

Run: `npm test`
Expected: 14/14 passed (100% 绿灯).

- [ ] **Step 3: 执行全库 Python 离线测试套件**

Run: `uv run python -m pytest`
Expected: 643/643 passed (100% 绿灯).

- [ ] **Step 4: 静态类型分析检查**

Run: `npx pyright`
Expected: 0 errors, 0 warnings, 0 informations.

---

## 计划自审对照表 (Self-Review Checklist)

1. **视觉规范全量覆盖**：零 Emoji、双行分栏 Footer、极简 Header 横幅、容器层叠纠偏均已纳入具体 Task。
2. **测试驱动 (TDD)**：所有新增组件均配有独立的 `.test.js` 单元测试，先红后绿。
3. **零退化承诺**：既有 643 项后端 Python 自动化测试与 RPC 协议保持 100% 兼容。
