# Route B: Pi 原厂交互层源码全量移植与 Python Agent 适配实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按照用户选定的路线 B（Route B），将 `D:\code\python\agent-program\pi\packages\coding-agent\src\modes\interactive\` 的全部原生 TypeScript 源码（包括全部 30+ components、`theme/`、`chat-viewport.ts`、`tui-renderer.ts` 与 `interactive-mode.ts`）直接移植入当前工程的 `tui/src/interactive/`，在源码层与已建成的 `KernelBridge`（Python JSON-RPC 2.0 桥接层）无缝对接，使当前项目拥有 100% 原厂前端源代码的完全掌控权。

**Architecture:**

- **源码宿主层 (`tui/src/interactive/`)**：
  - `components/`：直接容纳 Pi 原厂的 30+ 个 `.ts` 组件源码（思维链折叠、工具执行动态卡片、全套选择器等）；
  - `theme/`：原厂 TrueColor 主题与代码着色体系；
  - `chat-viewport.ts` & `tui-renderer.ts`：原厂视口引擎与终端双缓冲渲染管线；
  - `interactive-mode.ts`：原厂交互主控制器，经由 `KernelBridge` 驱动。
- **桥梁层 (`tui/src/bridge/`)**：维持 `KernelBridge` + `EventTranslator` + `PythonKernelClient` 稳定通信。
- **门面入口 (`tui/src/app.ts` & `tui/src/index.ts`)**：轻量启动装配。

**Tech Stack:** TypeScript 5.8+, Node.js 22+, `@earendil-works/pi-tui` 0.85+, `@earendil-works/pi-coding-agent`, Python 3.11+.

---

## 实施任务总览表 (Overview)

| Task # | 核心任务 | 交付目标 | 预估验证 |
| :--- | :--- | :--- | :--- |
| **Task 1** | 复制原厂全套 Components 源码并平滑依赖 | `tui/src/interactive/components/*` (30+ .ts files) | `tsc` 编译检查 |
| **Task 2** | 复制原厂 Theme、Viewport 与 Renderer 源码 | `tui/src/interactive/theme/*`<br>`tui/src/interactive/chat-viewport.ts`<br>`tui/src/interactive/tui-renderer.ts` | `tsc` 编译检查 |
| **Task 3** | 适配 InteractiveMode 源码与 KernelBridge 绑定 | `tui/src/interactive/interactive-mode.ts` | 单元测试 & 集成测试 |
| **Task 4** | 全量编译、全套前端自动化测试与 Python 测试回归 | `npm test` & `pytest` | 47 TS & 655 Python |
| **Task 5** | 真机交互验证与功能走查 (npm start) | 终端交互走查 | 键盘输入、选择器、打断 |

---

## 任务执行细节 (Detailed Tasks)

### Task 1: 复制原厂全套 Components 源码并平滑依赖

**Files:**

- Source: `D:\code\python\agent-program\pi\packages\coding-agent\src\modes\interactive\components\*`
- Target: `tui/src/interactive/components/*`

- [ ] **Step 1: 复制原厂 `components/` 源码至 `tui/src/interactive/components/`**
- [ ] **Step 2: 调整相对核心依赖（将 `../../../core/...` 重定向为 `@earendil-works/pi-coding-agent`）**
- [ ] **Step 3: 运行 `npm run build` 确保 components 编译无报错**

---

### Task 2: 复制原厂 Theme、Viewport 与 Renderer 源码

**Files:**

- Source: `D:\code\python\agent-program\pi\packages\coding-agent\src\modes\interactive\theme\*`
- Source: `D:\code\python\agent-program\pi\packages\coding-agent\src\modes\interactive\chat-viewport.ts`
- Source: `D:\code\python\agent-program\pi\packages\coding-agent\src\modes\interactive\tui-renderer.ts`
- Target: `tui/src/interactive/`

- [ ] **Step 1: 复制原厂 `theme/` 目录到 `tui/src/interactive/theme/`**
- [ ] **Step 2: 复制原厂 `chat-viewport.ts` 与 `tui-renderer.ts` 源码**
- [ ] **Step 3: 调整工具函数依赖并执行 `npm run build` 编译验证**

---

### Task 3: 适配 InteractiveMode 源码与 KernelBridge 绑定

**Files:**

- Source: `D:\code\python\agent-program\pi\packages\coding-agent\src\modes\interactive\interactive-mode.ts`
- Target: `tui/src/interactive/interactive-mode.ts`

- [ ] **Step 1: 引入原厂 `interactive-mode.ts` 结构**
- [ ] **Step 2: 绑定 `KernelBridge` 数据管道与键盘监听（确保 `this.ui.start()`）**
- [ ] **Step 3: 验证选择器（/model, /session, /tree, /thinking 等）与 Python RPC 对齐**

---

### Task 4: 全量编译、全套前端自动化测试与 Python 测试回归

- [ ] **Step 1: 执行 TypeScript 全量编译 (`npm run build`)**
- [ ] **Step 2: 执行前端全部 47 项测试 (`npm test`)**
- [ ] **Step 3: 执行 Python 655 项全量测试 (`uv run python -m pytest tests/`)**

---

### Task 5: 真机交互验证与功能走查 (npm start)

- [ ] **Step 1: 终端启动 `npm start` 冒烟走查**
- [ ] **Step 2: 测试用户输入回车提交、Ctrl+C/Esc 中断**
- [ ] **Step 3: 测试 `/model` 与 `/session` 选择器交互**
