# 13 - Codemode 模式设计与实现规范

本文档详细定义了 `my-pi-agent` 中 **Codemode（代码模式）** 的系统设计规范、双核进程通信协议、沙箱安全隔离机制与工具编排策略，严格对齐 Pi 原厂（`@earendil-works/pi-codemode`）的工业级标准。

---

## 一、 方案背景与设计目标

### 1. 传统 ReAct 模式的核心瓶颈
在传统的单步工具调用（Function Calling）中，大模型与外部环境交互存在三大固有瓶颈：
1. **多轮网络 RTT 极高**：若任务需要遍历并检索 10 个文件，大模型必须发起 10 轮独立的模型推理与 API 往返，响应迟缓；
2. **上下文严重污染（Context Bloat）**：每个工具的原始输出（例如 50KB 的裸日志、长目录树或数十个搜索结果）无差别注入对话历史，极快耗尽上下文窗口并频繁触发有损压缩；
3. **复杂逻辑编排脆弱**：大模型无法在单轮中表达“如果 A 工具找到结果，则并行读取 B 和 C；否则调用 D 兜底”的条件控制流与数据清洗逻辑。

### 2. Codemode 设计目标
* **代码级即时编排（Code-as-Orchestrator）**：允许大模型直接编写一段 JavaScript 脚本，在安全隔离的沙箱内批量、并发（`Promise.allSettled`）调用底层工具，并在沙箱内存中就地通过数组切片、正则与映射进行数据清洗，**仅将最终浓缩的高价值结论返回给上下文**；
* **100% 对齐 Pi 原厂体验**：完全遵照 Pi 的全局 API 规范（`tools.*`、`text()`、`image()`、`console.log()`、`store()`/`load()`、`exit()`）、首行配置指令（`// @options:`）以及结果排版格式；
* **现有工具生态零侵入**：底层直接复用现有的 `ToolRegistry`、单文件细粒度写锁（`FileMutationQueue`）与 Never-Throw 崩溃免疫保证；
* **跨进程安全隔离**：利用系统原生具备的 Node.js 运行时构建受限的 JavaScript 虚拟机沙箱，彻底剥离系统 I/O 与网络权限，与 Python 核心进程通过管道解耦。

---

## 二、 系统架构与双核拓扑

整个 Codemode 执行流水线分为 **Python 调度层**、**双向 stdio IPC 桥** 与 **Node.js 隔离沙箱**：

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                      大模型 (LLM Inference Engine)                          │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │ tool_call(name="codemode", args={"code": "..."})
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 【Python 调度层】: src/my_agent_core/tools/codemode.py                      │
│                                                                             │
│  1. 校验与解析首行指令: // @options: {"max_output_tokens": 5000, ...}        │
│  2. 提取当前 Session 分支最新的 codemode-store 键值快照                     │
│  3. 异步拉起 / 调度 Node.js 沙箱 Worker 进程                                │
│                                                                             │
│     ┌─────────────────────────────────────────────────────────────────┐     │
│     │ 双向 stdio JSON-RPC 消息循环 (src/my_agent_core/codemode/bridge.py) │     │
│     │   - 监听沙箱工具请求: {"type": "call", "id": 1, "tool": "read", ...}│     │
│     │   - 调度核心执行: await registry.execute_tool("read", args)    │     │
│     │   - 响应工具执行数据: {"type": "res", "id": 1, "ok": true, ...} │     │
│     └─────────────────────────────────────────────────────────────────┘     │
│                                                                             │
│  4. 结果聚合与排版: 组装 text() / console / return 内容，原子落盘 store()   │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │ stdin / stdout JSONL 管道
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 【Node.js 沙箱执行层】: src/my_agent_core/codemode/runner.mjs                │
│                                                                             │
│  1. 权限彻底剥离: 移除 process, fs, child_process, fetch, 网络与计时器      │
│  2. 原型链深层冻结: Object.freeze() 内置类原型，防止原型污染逃逸            │
│  3. 虚拟机上下文 (node:vm Context):                                         │
│     • tools.<name>(args): 代理为向 Python 发起请求的 Promise                │
│     • text(val) / image(data): 写入内存输出缓存                             │
│     • console.log(...): 收集日志到 <console_output> 队列                    │
│     • store(k, v) / load(k): 内存读写并在结束时汇总                         │
│  4. 顶层异步执行包装: (async () => { ... })(); 捕获未处理的 Rejection        │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 三、 跨进程 IPC 协议规范

Python 宿主与 Node.js 沙箱 Worker 之间采用高吞吐、零依赖的 **单行 JSON（JSONL）** 通信协议：

### 1. Python ➔ Node：启动执行任务 (`execute`)
```json
{
  "action": "execute",
  "code": "const files = await tools.find({ pattern: 'test' }); text(files);",
  "store": { "cursor": 10 },
  "timeout_ms": 30000,
  "max_output_tokens": 10000
}
```

### 2. Node ➔ Python：脚本执行中途调用工具 (`tool_call`)
```json
{
  "action": "tool_call",
  "call_id": "c_1",
  "name": "read",
  "args": { "path": "package.json", "limit": 10 }
}
```

### 3. Python ➔ Node：返回工具执行结果 (`tool_result`)
```json
{
  "action": "tool_result",
  "call_id": "c_1",
  "ok": true,
  "result": "{\n  \"name\": \"my-pi-agent\"\n}"
}
```

### 4. Node ➔ Python：脚本执行完毕通知 (`completed`)
```json
{
  "action": "completed",
  "ok": true,
  "wall_time": 0.128,
  "text_items": ["找到 1 个匹配项"],
  "console_lines": ["[info] grep finished"],
  "store_writes": { "cursor": 15 },
  "error": null
}
```

---

## 四、 沙箱安全隔离机制与防御准则

沙箱内运行的大模型生成脚本是**不可信代码**，必须实施全方位的物理级安全防护：

1. **运行时权限完全剥离**：
   * 不注入 `process`、`require`、`import`、`fetch`、`WebSocket`、`XMLHttpRequest`、`Buffer`；
   * 禁用 `setTimeout`、`setInterval`、`setImmediate`（Pi 规范规定沙箱不得使用计时器，无未决 Promise 立即挂起报错）；
2. **原型链防污染（Prototype Lockdown）**：
   * 在启动用户代码前，递归执行 `Object.freeze()` 锁定 `Object.prototype`、`Array.prototype`、`Function.prototype`、`Promise.prototype`，防止脚本篡改基础方法导致沙箱宿主逻辑失常；
3. **内存与资源硬限制**：
   * 启动 Node 进程时显式配置 `--max-old-space-size=256`（256MB 堆内存上限），超出立即抛出内存不足；
4. **协作式打断与双重超时监控**：
   * 优先响应首行 `timeout_ms`；
   * Python 宿主采用 `asyncio.wait_for` 进行硬超时看门狗保护；一旦超时或收到用户 `CancellationToken`（`Esc` 键），直接向 Node 进程发送 `SIGKILL` 强杀子进程并释放句柄。

---

## 五、 全局运行时 API 契约

脚本在沙箱中执行时，可直接访问如下标准全局对象：

| 全局对象 / 函数 | 签名与行为 | 失败与异常表现 |
| :--- | :--- | :--- |
| `tools.<name>(args)` | 调用已注册的任意底层工具（如 `read`, `bash`, `grep`）。 | 底层失败或校验不通过时，Promise 直接 **`reject(new Error(err))`**。推荐使用 `try/catch` 或 `Promise.allSettled`。 |
| `text(value)` | 将结果追加至最终输出。字符串直接输出，非字符串自动 `JSON.stringify`。 | 产生多个 text 时，最终展示自动排版为 `==> text N/M <==` 块。 |
| `image(data)` | 支持传入 Base64 字典块 `{ type: "image", data, mimeType }`。 | 自动写入临时文件并在最终输出中打印保存路径。 |
| `console.log(...)` | 收集调试日志。支持多参数空格拼接。 | 最终统一汇聚在 `<console_output>...</console_output>` 块中。 |
| `store(key, value)` | 存入当前会话的持久化键值对（单值 $\le$ 256KB，总和 $\le$ 1MB）。 | 仅当脚本成功执行（`ok=True`）时落盘；传 `undefined` 为删除。 |
| `load(key)` | 读取当前会话的持久化键值。 | 键不存在时返回 `undefined`。 |
| `return value` | 顶级 return。 | 行为等价于 `text(value)` 并退出脚本。 |
| `exit()` | 立即正常终止脚本。 | 提前结束执行并提交已有输出。 |
| `ALL_TOOLS` | 获取当前所有已注册工具的极简元数据列表。 | `[{ name, description }]`，用于动态遍历发现工具。 |

---

## 六、 首行指令解析规范 (`// @options:`)

为兼顾灵活性与严格语法，支持可选的首行选项声明：

```javascript
// @options: {"max_output_tokens": 5000, "timeout_ms": 30000}
const files = await tools.find({ pattern: "test" });
...
```

* **语法规则**：
  * **必须严格位于第 1 行**（允许前导空格），位于其他行直接抛出 `CodemodeSourceError` 语法拦截；
  * 内容必须是合法的 JSON 对象，仅允许 `max_output_tokens`（非负整数）与 `timeout_ms`（正整数）两个字段。

---

## 七、 工具描述 TypeScript 动态渲染与预算门控

为了向模型提供最高信噪比的提示，同时保护上下文窗口，`declarations.py` 动态把 Python Pydantic Schema 转换为 TypeScript 紧凑类型：

### 1. 渲染示例
```typescript
declare const tools: {
  /** Read file contents. Supports text and images. */
  read(args: { path: string; offset?: number; limit?: number }): Promise<string>;

  /** Execute bash commands in workspace. */
  bash(args: { command: string; timeout?: number }): Promise<{ output: string; exit_code: number }>;

  /** Search file contents using regex or literal text. */
  grep(args: { pattern: string; path?: string; limit?: number }): Promise<string>;
};
```

### 2. 预算门控机制（3000 Tokens Inline Budget）
* 默认预算为 **3000 Tokens**；
* 优先为工作区核心工具（`read`, `write`, `edit`, `bash`, `grep`, `find`, `ls`）生成完整 TypeScript 签名；
* 若引入大量动态 MCP 工具导致超出预算，超出部分仅保留工具名称，并在 Description 中引导模型通过 `ALL_TOOLS` 动态遍历。

### 3. 工作模式切换 (`codemode.mode`)
* **`on`（混合共存模式，默认）**：普通工具与 `codemode` 并存，模型自由选择单步直接调用或脚本化批量调用；
* **`only`（独占模式）**：向模型隐藏所有常规工具，**仅暴露 `codemode` 单一工具**，强制大模型通过编写 JavaScript 完成全部交互，实现极致的 Token 节约与工作流确定性。

---

## 八、 会话持久化与状态存储集成 (`codemode-store`)

`store(key, value)` 和 `load(key)` 与 `SessionTree` 紧密集成：
1. **状态快照投影**：在执行前，Python 遍历当前会话路径（Path from Root to Leaf），按时序折叠所有 `codemode-store` 自定义条目，获得最新的字典视图并传入沙箱；
2. **原子条件提交**：
   * 若脚本中途崩溃或抛出未捕获异常：**所有 `store()` 写入直接作废，不污染会话状态**；
   * 若脚本正常执行完毕且产生了变更：Python 自动追加一条不可变的 `CustomEntry(custom_type="codemode-store", data=writes)` 到当前会话树节点，原生支持分支（Fork）与历史回退（Rewind）时的状态隔离。

---

## 九、 最终输出格式化规范

不论执行成功或失败，返回给 ReAct 微内核的文本严格排版如下：

### 1. 执行成功且产生多段输出
```text
Script completed (0.18s)
==> text 1/2 <==
找到 2 处配置文件：
- pyproject.toml
- package.json

==> text 2/2 <==
已成功提取核心依赖配置。

<console_output>
[info] matched 2 files
</console_output>
```

### 2. 执行失败（保留失败前的控制台打印与错误堆栈）
```text
Script failed (0.04s)
<console_output>
[debug] scanning workspace...
</console_output>
Script error:
TypeError: Cannot read properties of undefined (reading 'split')
    at <anonymous> (script.js:3:15)
```

---

## 十、 分阶段落地路线图

* **Phase 1（核心沙箱与 IPC 通信骨架）**：
  * 实现 `runner.mjs` 与 `bridge.py`；
  * 单测覆盖：基础算术脚本、`text()`/`console` 输出收集、`tools.<name>` 异步双向回调、超时强杀测试。
* **Phase 2（Pydantic 到 TypeScript 声明生成器）**：
  * 实现 `declarations.py`；
  * 单测覆盖：基本类型映射、可选字段识别、枚举联合体渲染、3000 Token 预算控制截断。
* **Phase 3（CodemodeTool 门面与 Session 存储对接）**：
  * 实现 `src/my_agent_core/tools/codemode.py`；
  * 实现 `Session` 中 `codemode-store` CustomEntry 状态折叠与写入；
  * 单测覆盖：跨回合 `store/load` 状态记忆测试、脚本失败时不落盘测试。
* **Phase 4（产品层装配与端到端实测）**：
  * 在 `CodingAgent` 中集成 `codemode`，在 `settings.json` 中支持模式切换；
  * 使用 Herdr 在真机终端中进行真实模型编写 JS 脚本执行批量工具调用的端到端验证。
