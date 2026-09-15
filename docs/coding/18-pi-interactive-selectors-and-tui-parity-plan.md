# my-pi-agent 对齐 Pi 原厂交互选择器体系实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 依据 `docs/coding/17-pi-interactive-selectors-and-tui-parity-design.md`，彻底消灭当前输入 `/resume`、`/model`、`/thinking` 时在聊天区刷屏打印静态纯文本的落后交互，完整实现基于 `editorContainer` 插槽的 `showSelector` 动态视口抽换机制，以及三大交互式选择器（`SessionSelector`、`ModelSelector`、`ThinkingSelector`），实现 100% 像素级对标 Pi 原厂的键盘全交互体验。

**Architecture:**

- **动态横向边界线 (`tui/src/components/dynamic-border.ts`)**：自适应终端宽度的水平线组件。
- **思考深度选择器 (`tui/src/components/thinking-selector.ts`)**：7 级思考深度交互列表、Token 估算说明与当前等级标记。
- **模型目录选择器 (`tui/src/components/model-selector.ts`)**：多 Token 模糊搜索、Provider 徽章、上下文窗口大小展示。
- **历史会话选择器 (`tui/src/components/session-selector.ts`)**：会话搜索、本目录/全局会话切换（Tab）、路径显示切换（Ctrl+P）、Enter 瞬间恢复。
- **插槽抽换容器 (`tui/src/app.ts`)**：`editorContainer` 动态挂载、防竞态 `token` 保护、退出时恢复焦点。

---

## 实施任务总览表 (Overview)

| Task # | 核心任务 | 交付文件 / 模块 | 预估测试 |
| :--- | :--- | :--- | :--- |
| **Task 1** | DynamicBorder 宽度自适应边界线组件 | `tui/src/components/dynamic-border.ts`<br>`tui/test/dynamic-border.test.js` | 2 项单测 |
| **Task 2** | ThinkingSelectorComponent 思考等级选择器 | `tui/src/components/thinking-selector.ts`<br>`tui/test/thinking-selector.test.js` | 4 项单测 |
| **Task 3** | ModelSelectorComponent 模型目录模糊搜索选择器 | `tui/src/components/model-selector.ts`<br>`tui/test/model-selector.test.js` | 4 项单测 |
| **Task 4** | SessionSelectorComponent 会话交互管理器 | `tui/src/components/session-selector.ts`<br>`tui/test/session-selector.test.js` | 4 项单测 |
| **Task 5** | AgentApp showSelector 视口抽换与命令接入 | `tui/src/app.ts`<br>`tui/test/app.test.js` | 15 项集成测试 |
| **Task 6** | 全库编译、前端测试扩充与全量回归 | 全库验证 | 651+ Python & 35+ TS |

---

## 任务执行细节 (Detailed Tasks)

### Task 1: DynamicBorder 宽度自适应边界线组件

**Files:**

- Create: `tui/src/components/dynamic-border.ts`
- Create: `tui/test/dynamic-border.test.js`

- [ ] **Step 1: 编写 `tui/test/dynamic-border.test.js` 失败测试**
- [ ] **Step 2: 运行测试验证失败**
- [ ] **Step 3: 实现 `tui/src/components/dynamic-border.ts`**
- [ ] **Step 4: 编译并验证测试通过**

---

### Task 2: ThinkingSelectorComponent 思考等级选择器

**Files:**

- Create: `tui/src/components/thinking-selector.ts`
- Create: `tui/test/thinking-selector.test.js`

- [ ] **Step 1: 编写 `tui/test/thinking-selector.test.js` 失败测试**
- [ ] **Step 2: 运行测试验证失败**
- [ ] **Step 3: 实现 `tui/src/components/thinking-selector.ts`**
- [ ] **Step 4: 编译并验证测试通过**

---

### Task 3: ModelSelectorComponent 模型目录模糊搜索选择器

**Files:**

- Create: `tui/src/components/model-selector.ts`
- Create: `tui/test/model-selector.test.js`

- [ ] **Step 1: 编写 `tui/test/model-selector.test.js` 失败测试**
- [ ] **Step 2: 运行测试验证失败**
- [ ] **Step 3: 实现 `tui/src/components/model-selector.ts`**
- [ ] **Step 4: 编译并验证测试通过**

---

### Task 4: SessionSelectorComponent 会话交互管理器

**Files:**

- Create: `tui/src/components/session-selector.ts`
- Create: `tui/test/session-selector.test.js`

- [ ] **Step 1: 编写 `tui/test/session-selector.test.js` 失败测试**
- [ ] **Step 2: 运行测试验证失败**
- [ ] **Step 3: 实现 `tui/src/components/session-selector.ts`**
- [ ] **Step 4: 编译并验证测试通过**

---

### Task 5: AgentApp showSelector 视口抽换与命令接入

**Files:**

- Modify: `tui/src/app.ts`
- Modify: `tui/test/app.test.js`

- [ ] **Step 1: 在 `tui/src/app.ts` 引入 `editorContainer` 与 `showSelector` 机制**
- [ ] **Step 2: 将 `/thinking`、`/model`、`/resume` 无参命令从纯文本改造为调用选择器**
- [ ] **Step 3: 运行测试验证通过**

---

### Task 6: 全库编译与全量回归测试

- [ ] **Step 1: 编译前端 TypeScript (`npm run build --prefix tui`)**
- [ ] **Step 2: 运行所有前端测试 (`npm test`)**
- [ ] **Step 3: 运行 Python 全量测试 (`uv run python -m pytest`)**
- [ ] **Step 4: 静态类型检查 (`npx pyright`)**
