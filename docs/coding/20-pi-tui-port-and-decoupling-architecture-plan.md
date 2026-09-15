# Pi 原厂交互层 (TUI) 移植与架构解耦二次开发实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按照 `docs/coding/19-pi-tui-port-and-decoupling-architecture-design.md` 规范，彻底重构前端架构，完整移植 Pi 原厂成熟的 `modes/interactive` 交互层（包含全套 components、`chat-viewport`、`tui-renderer`、`theme`），构建轻量 `KernelBridge` 驱动层桥接 Python JSON-RPC 2.0 后端，废除 1800 行手写单体 `app.ts`，达到 100% 原厂交互质感与零体验 Bug。

**Architecture:**

- **桥梁层 (`tui/src/bridge/`)**：由 `EventTranslator`（流式增量装配与标准化）、`KernelBridge`（轻量 Session 代理契约）和 `PythonKernelClient`（子进程与 stdio 通信）构成。
- **原厂交互层 (`tui/src/interactive/`)**：100% 移植原厂成熟组件（Thinking 折叠、流式 Markdown 高亮、动态工具加载圈、全套交互式 Selectors）与双缓冲视口管线（`chat-viewport` + `tui-renderer`）。
- **启动引导层 (`tui/src/index.ts`)**：CLI 参数解析、桥接装配与初始化入口。

**Tech Stack:** TypeScript 5.8+, Node.js 22+, `@earendil-works/pi-tui` 0.85+, Python 3.11+, JSON-RPC 2.0 stdio 通信。

**Spec:** `docs/coding/19-pi-tui-port-and-decoupling-architecture-design.md`

## Global Constraints

- 前端代码保持高内聚低耦合，严禁在 `interactive/` 组件层直接引用 Python 专属逻辑；
- 所有 UI 状态映射由 `bridge/` 统一收拢，遵循 Never-Throw Guarantee；
- 保持对既有命令（`/model`, `/session`, `/tree`, `/thinking`, `/login`, `/logout`, `/clear`）的 100% 行为对齐；
- 遵循 TDD 流程，每个任务必须包含可验证的自动化单元测试。

---

## 实施任务总览表 (Overview)

| Task # | 核心任务 | 交付文件 / 模块 | 预估测试 |
| :--- | :--- | :--- | :--- |
| **Task 1** | 事件转译器 `EventTranslator` 实现与流式装配 | `tui/src/bridge/event-translator.ts`<br>`tui/test/bridge/event-translator.test.js` | 6 项单测 |
| **Task 2** | 内核桥接层 `KernelBridge` 实现与会话代理 | `tui/src/bridge/kernel-bridge.ts`<br>`tui/test/bridge/kernel-bridge.test.js` | 6 项单测 |
| **Task 3** | 原厂核心基础组件、工具库与视口管线就绪 | `tui/src/interactive/components/*`<br>`tui/src/interactive/chat-viewport.ts`<br>`tui/src/interactive/tui-renderer.ts` | 编译检查 & 单元测试 |
| **Task 4** | 原厂主交互控制器 `InteractiveMode` 桥接改造 | `tui/src/interactive/interactive-mode.ts` | 集成测试 |
| **Task 5** | 入口模块改造与废弃单体 `app.ts` | `tui/src/index.ts`<br>`tui/bin/my-agent.js` | 端到端启动测试 |
| **Task 6** | 全量自动化测试套件适配与回归 | `tui/test/*.test.js` 全套套件更新 | 45+ TS & 575 Python |
| **Task 7** | 真实终端 5 大人工验收门禁走查 | 交互实操验收 | 5 项人工交互门禁 |

---

## 任务执行细节 (Detailed Tasks)

### Task 1: 事件转译器 `EventTranslator` 实现与流式装配

**Files:**

- Create: `tui/src/bridge/event-translator.ts`
- Create: `tui/test/bridge/event-translator.test.js`

**Interfaces:**

- Consumes: Python JSON-RPC notifications: `agent_start`, `message_start`, `message_update`, `tool_execution_*`, `agent_end`
- Produces: `EventTranslator.translate(rpcNotification)` -> `AgentSessionEvent | null`，以及 `currentMessage` 状态缓存。

- [ ] **Step 1: 编写 `tui/test/bridge/event-translator.test.js` 失败测试**

```javascript
import { test } from "node:test";
import assert from "node:assert/strict";
import { EventTranslator } from "../../dist/bridge/event-translator.js";

test("EventTranslator translates message_update deltas into assistant message blocks", () => {
  const translator = new EventTranslator();
  
  translator.translate({ type: "message_start", message: { role: "assistant", content: "" } });
  
  const ev1 = translator.translate({
    type: "message_update",
    message: { role: "assistant", content: "" },
    reasoning_delta: "Thinking step 1...",
  });
  assert.equal(ev1.type, "message_update");
  assert.equal(ev1.message.content[0].type, "thinking");
  assert.equal(ev1.message.content[0].thinking, "Thinking step 1...");

  const ev2 = translator.translate({
    type: "message_update",
    message: { role: "assistant", content: "" },
    delta: "Hello world!",
  });
  assert.equal(ev2.message.content[1].type, "text");
  assert.equal(ev2.message.content[1].text, "Hello world!");
});
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd tui && node --test test/bridge/event-translator.test.js
```

预期：FAIL (模块未找到)。

- [ ] **Step 3: 实现 `tui/src/bridge/event-translator.ts`**

实现包含思考累加、正文累加、工具生命周期维护（start/update/end）的标准事件组装机。

- [ ] **Step 4: 编译并验证测试通过**

```bash
cd tui && npm run build && node --test test/bridge/event-translator.test.js
```

预期：PASS。

- [ ] **Step 5: 提交代码**

```bash
git add tui/src/bridge/event-translator.ts tui/test/bridge/event-translator.test.js
git commit -m "feat(bridge): 实现 EventTranslator 增量事件转译器"
```

---

### Task 2: 内核桥接层 `KernelBridge` 实现与会话代理

**Files:**

- Create: `tui/src/bridge/kernel-bridge.ts`
- Create: `tui/test/bridge/kernel-bridge.test.js`

**Interfaces:**

- Consumes: `PythonKernelClient`, `EventTranslator`
- Produces: `KernelBridge` 具备 `prompt()`, `abort()`, `steer()`, `listModels()`, `switchModel()`, `listSessions()`, `resumeSession()`, `getTree()`, `setThinking()`, `subscribe()` 方法。

- [ ] **Step 1: 编写 `tui/test/bridge/kernel-bridge.test.js` 失败测试**

```javascript
import { test } from "node:test";
import assert from "node:assert/strict";
import { KernelBridge } from "../../dist/bridge/kernel-bridge.js";

test("KernelBridge proxies prompt and abort requests to PythonKernelClient", async () => {
  const mockCalls = [];
  const fakeClient = {
    request: async (method, params) => {
      mockCalls.push({ method, params });
      return { status: "ok" };
    },
    on: () => {},
  };
  const bridge = new KernelBridge(fakeClient);

  await bridge.prompt("hello test");
  assert.equal(mockCalls[0].method, "prompt");
  assert.equal(mockCalls[0].params.text, "hello test");

  await bridge.abort();
  assert.equal(mockCalls[1].method, "abort");
});
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd tui && node --test test/bridge/kernel-bridge.test.js
```

预期：FAIL。

- [ ] **Step 3: 实现 `tui/src/bridge/kernel-bridge.ts`**

将 Python RPC 的全部能力（`prompt`, `models_list`, `model_switch`, `session_list`, `session_resume`, `session_tree`, `thinking_set` 等）统一封装为符合 Pi 交互规范的统一 Promise 接口。

- [ ] **Step 4: 编译并验证测试通过**

```bash
cd tui && npm run build && node --test test/bridge/kernel-bridge.test.js
```

预期：PASS。

- [ ] **Step 5: 提交代码**

```bash
git add tui/src/bridge/kernel-bridge.ts tui/test/bridge/kernel-bridge.test.js
git commit -m "feat(bridge): 实现轻量 Session 代理桥接器 KernelBridge"
```

---

### Task 3: 原厂核心基础组件、工具库与视口管线就绪

**Files:**

- Create: `tui/src/interactive/chat-viewport.ts`
- Create: `tui/src/interactive/tui-renderer.ts`
- Create: `tui/src/interactive/components/*`
- Create: `tui/src/interactive/theme/*`
- Create: `tui/src/utils/*`

- [ ] **Step 1: 引入 Pi 原厂成熟代码并放入对应目录**

提取并整理原厂核心 UI 代码：

- `chat-viewport.ts`: 视口滚动管理；
- `tui-renderer.ts`: 终端双缓冲渲染器；
- `components/`: `assistant-message.ts`, `tool-execution.ts`, `user-message.ts`, `footer.ts`, `dynamic-border.ts`, 各类选择器等；
- `theme/`: 官方深色主题与高亮器；
- `utils/`: ANSI 长度计算、终端工具等。

- [ ] **Step 2: 验证 TypeScript 编译与类型完备性**

```bash
cd tui && npm run build
```

预期：编译通过，无未解决的模块导入或类型缺失。

- [ ] **Step 3: 提交代码**

```bash
git add tui/src/interactive/ tui/src/utils/
git commit -m "feat(interactive): 引入 Pi 原厂 components、viewport、renderer 与主题支持"
```

---

### Task 4: 原厂主交互控制器 `InteractiveMode` 桥接改造

**Files:**

- Create: `tui/src/interactive/interactive-mode.ts`

- [ ] **Step 1: 改造 `interactive-mode.ts`**

将原本直接调用本地 TypeScript `AgentSession` 的数据源挂载点，无缝重定向为调用 `KernelBridge`：

- `this.bridge.prompt(text)` 代替 `this.session.prompt`；
- `this.bridge.abort()` 代替 `this.session.abort`；
- `this.bridge.subscribe()` 接收标准事件流；
- 弹窗选择器（`showSelector`）的数据加载方法接入 `this.bridge.listModels()` / `this.bridge.listSessions()` 等。

- [ ] **Step 2: 编译并验证无报错**

```bash
cd tui && npm run build
```

预期：PASS。

- [ ] **Step 3: 提交代码**

```bash
git add tui/src/interactive/interactive-mode.ts
git commit -m "feat(interactive): 适配 InteractiveMode 主控制器对接 KernelBridge"
```

---

### Task 5: 入口模块改造与废弃单体 `app.ts`

**Files:**

- Modify: `tui/src/index.ts`
- Modify: `tui/bin/my-agent.js`
- Delete: `tui/src/app.ts` (正式删除 1800 行手写单体)

- [ ] **Step 1: 更新 `tui/src/index.ts`**

以极简清晰的装配逻辑初始化应用：

```typescript
const client = new PythonKernelClient(options);
const bridge = new KernelBridge(client);
const interactiveMode = new InteractiveMode(bridge, options);
await interactiveMode.init();
```

- [ ] **Step 2: 删除原 `tui/src/app.ts` 及其无用手写 components**
- [ ] **Step 3: 编译并启动冒烟验证**

```bash
cd tui && npm run build
```

预期：PASS。

- [ ] **Step 4: 提交代码**

```bash
git add tui/src/index.ts tui/bin/my-agent.js
git rm tui/src/app.ts
git commit -m "refactor(tui): 切换入口至 InteractiveMode 并安全移除旧版单体 app.ts"
```

---

### Task 6: 全量自动化测试套件适配与回归

**Files:**

- Modify: `tui/test/*.test.js`
- Test: 全库运行

- [ ] **Step 1: 更新 `tui/test/` 下各测试用例，适配新架构引用**
- [ ] **Step 2: 运行前端全量单元与集成测试**

```bash
cd tui && npm test
```

预期：所有测试全部通过（45+ 项测试）。

- [ ] **Step 3: 运行 Python 内核全量测试确保零破坏**

```bash
uv run python -m pytest
```

预期：575+ 项 Python 测试全部通过。

- [ ] **Step 4: 提交代码**

```bash
git add tui/test/
git commit -m "test(tui): 适配重构后的全量测试套件并确保回归绿灯"
```

---

### Task 7: 真实终端 5 大人工验收门禁走查

- [ ] **门禁 1: 启动与零闪烁排版** (`npm start` 启动，验证 Header、Logo、动态边框与 Footer 渲染)
- [ ] **门禁 2: 流式打字与思维链折叠** (触发模型输出，测试 `Ctrl+O` 展开/折叠，Markdown 代码高亮)
- [ ] **门禁 3: 工具动效与耗时统计** (触发 `read` 工具，观察 Spinner 动态旋转与结果截断)
- [ ] **门禁 4: 交互选择器与快捷键** (测试 `/model` (Ctrl+M)、`/session` (Ctrl+R)、`/thinking`)
- [ ] **门禁 5: 中断与缩放自适应** (流式中按 `Esc` 快速中断，拉伸窗口自适应排版)
- [ ] **最终提交并更新文档**
