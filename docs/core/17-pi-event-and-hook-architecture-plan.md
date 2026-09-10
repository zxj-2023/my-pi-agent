# Pi 风格事件流与五大决策拦截点正交重塑实施计划 (Phase 19 Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 依据 `docs/core/16-pi-event-and-hook-architecture-design.md`，彻底重塑 `my-agent-core` 的事件与微内核体系：将事件（只读事实流）与决策点（强拦截门禁）正交解耦，重构 `loop.py` 为清晰的子生成器分治结构（550行 ➔ 110行），升级 `ExtensionAPI` 支持强类型分流，重写相关单测彻底去除历史兼容包袱，确保全仓库所有离线测试 100% 绿灯全通。

**Architecture Alignment & Guidelines:**
- **彻底正交原则**：纯只读事实事件（`Event`）只管单向广播，绝无返回值与 `Interceptable` 混入；五大决策点（`UserInputDecision`、`AgentStartDecision`、`BeforeModelCallDecision`、`ToolCallDecision`、`ToolResultDecision`）专职控制流拦截；
- **拒绝冗余兼容原则**：旧单测直接重写对齐新接口，绝不在生产代码中引入过渡补丁与双轨逻辑；
- **Pi 时序契约原则**：`ToolExecutionStart` 在 Preflight 阶段率先广播（TUI 渲染运行态），`before_tool_call` 审批改参，并发执行后调用 `after_tool_call` 改写结果并广播 `ToolExecutionEnd`；
- **自愈闭环原则**：中途取消时，未执行的工具 100% 合成 `Tool call interrupted by user`，并严格发射配对的 `TurnEnd`。

---

## 实施任务总览表 (Overview)

| Task # | 核心目标 | 交付文件 | 预估测试数 |
| :--- | :--- | :--- | :--- |
| **Task 1** | 事件体系与决策点模型彻底正交解耦 (events.py) | `src/.../events.py`<br>`tests/test_events.py` | 19 tests |
| **Task 2** | `loop.py` 辅助流式生成器与子生成器提炼 | `src/.../loop.py`<br>`tests/test_agent_loop_pure.py` | 12 tests |
| **Task 3** | `loop.py` 主微内核状态机收敛与断头自愈闭环 | `src/.../loop.py`<br>`tests/test_agent_loop_pure.py` | 15 tests |
| **Task 4** | `ExtensionAPI` 强类型分流与 `Agent` 门面重构 | `src/.../extensions/core.py`<br>`src/.../agent.py` | 现有集成通过 |
| **Task 5** | 全量老单测重写（彻底消灭旧兼容包袱） | `tests/test_agent.py`<br>`tests/test_extensions.py` 等 | 370+ tests |
| **Task 6** | 全 Monorepo 回归验证与全套文档同步提交 | `README.md`<br>`PROGRESS.md`<br>`docs/...` | 378 tests (100% 绿灯) |

---

## 任务执行细节 (Detailed Tasks)

### Task 1: 事件体系与决策点模型彻底正交解耦 (`events.py`)

**Files:**
- Modify: `packages/my-agent-core/src/my_agent_core/events.py`
- Modify: `packages/my-agent-core/tests/test_events.py`
- Export: `packages/my-agent-core/src/my_agent_core/__init__.py`

**Interfaces:**
- Produces:
  - 纯只读事实事件：`Event(timestamp)`, `AgentStart(system_prompt, user_input)`, `AgentEnd(messages, final_text, iterations, stop_reason)`, `TurnStart(iteration)`, `TurnEnd(message, tool_results)`, `MessageStart(message)`, `MessageUpdate(message, chunk)`, `MessageEnd(message)`, `ToolExecutionStart(tool_call_id, tool_name, args)`, `ToolExecutionUpdate(tool_call_id, tool_name, args, partial_result)`, `ToolExecutionEnd(tool_call_id, tool_name, result, is_error)`, `ContextCompacted(...)`
  - 彻底删除 `Interceptable` 混入类定义。
  - 独立五大决策点：`UserInputDecision(input_text)`, `AgentStartDecision(system_prompt)`, `BeforeModelCallDecision(messages, iteration)`, `ToolCallDecision(tool_call_id, tool_name, args)`, `ToolResultDecision(tool_call_id, tool_name, result, is_error)`
  - 统一拦截结果：`HookResult(block, reason, updated_input, updated_system_prompt, updated_messages, updated_args, updated_result)`

- [ ] **Step 1: 编写 `test_events.py` 测试用例（TDD 先行）**
  - 测试所有只读事件继承自 `Event`，不可变且无 `Interceptable` 痕迹；
  - 测试 `TurnEnd` 允许 `message=None`（在启动被拦截时的优雅闭合）；
  - 测试 5 大独立决策点 dataclass 及其强类型属性；
  - 测试 `HookResult` 统一干预模型字段。

- [ ] **Step 2: 运行测试并观察失败**
  - 运行 `uv run python -m pytest tests/test_events.py -q`，确认新契约测试红灯。

- [ ] **Step 3: 重写 `events.py` 与顶层导出**
  - 严格按照规范落地数据模型，移除 `Interceptable`；
  - 在 `my_agent_core/__init__.py` 中更新导出清单。

- [ ] **Step 4: 运行 `test_events.py` 并保证绿灯**
  - 运行 `uv run python -m pytest tests/test_events.py -q`，确认 19 项测试全部通过。

- [ ] **Step 5: Git 提交**
  - 提交：`feat(events): 事件只读事实流与五大决策拦截点彻底正交解耦`

---

### Task 2: `loop.py` 辅助流式适配器与专职子生成器提炼

**Files:**
- Modify: `packages/my-agent-core/src/my_agent_core/loop.py`
- Modify: `packages/my-agent-core/tests/test_agent_loop_pure.py`

**Interfaces:**
- Produces:
  - `_stream_llm(llm, messages, tool_schemas, model)`: 统一归一化 `achat_stream` / `achat` / `chat`；
  - `_assistant_turn(...) -> AsyncIterator[AgentEvent]`: 专职模型推理车间，负责累加 Token、发射 `MessageUpdate`，并在末尾发射 `MessageStart/End(assistant)`；
  - `_synthesize_interrupted_tool_calls(tool_calls)`: 集中式断头合成辅助函数；
  - `_execute_tools_turn(...) -> AsyncIterator[AgentEvent]`: 专职工具执行车间，Preflight 发射 `ToolExecutionStart` ➔ `before_tool_call` 审批 ➔ 并发执行 ➔ `after_tool_call` 改写 ➔ 广播 `ToolExecutionEnd` ➔ 发射 `tool` 消息。

- [ ] **Step 1: 在 `test_agent_loop_pure.py` 中编写子生成器单元测试（TDD 先行）**
  - 验证 `_stream_llm` 对各种假 LLM 对象的统一归一化产出；
  - 验证 `_execute_tools_turn` 严格遵守 Pi 时序契约：率先广播 `ToolExecutionStart`，再调用 `before_tool_call`；执行完调用 `after_tool_call`，再广播 `ToolExecutionEnd`；
  - 验证 `_execute_tools_turn` 在收到 `signal.is_cancelled()` 时自动合成中断结果。

- [ ] **Step 2: 运行测试并观察失败**
  - 运行 `uv run python -m pytest tests/test_agent_loop_pure.py -k test_sub_generators -q`，确认失败。

- [ ] **Step 3: 在 `loop.py` 中实现 `_stream_llm`、`_assistant_turn` 与 `_execute_tools_turn`**
  - 实现专职子生成器，消除重复样板代码。

- [ ] **Step 4: 运行单测并验证绿灯**
  - 运行 `uv run python -m pytest tests/test_agent_loop_pure.py -q`，确认子生成器测试全部绿灯。

- [ ] **Step 5: Git 提交**
  - 提交：`refactor(loop): 提炼 _stream_llm 统一适配器与 _assistant_turn / _execute_tools_turn 子生成器`

---

### Task 3: `loop.py` 主微内核状态机收敛与断头自愈闭环

**Files:**
- Modify: `packages/my-agent-core/src/my_agent_core/loop.py`
- Modify: `packages/my-agent-core/tests/test_agent_loop_pure.py`

**Interfaces:**
- Produces:
  - `run_agent_loop(...)`: 主调度循环瘦身至约 110 行；
  - 决策点接缝显式化：`before_model_call`, `before_tool_call`, `after_tool_call`；
  - 状态机闭环：`max_turns` 截断、`TurnStart/End` 严格配对、中途取消断头自愈合成。

- [ ] **Step 1: 在 `test_agent_loop_pure.py` 中增加微内核闭环行为测试（TDD 先行）**
  - 验证 `before_model_call` 返回 `block=True` 时，严格发射 `TurnEnd` 与 `AgentEnd(stop_reason="blocked")`；
  - 验证模型流式输出期间触发取消时，若带 `tool_calls` 立即自愈合成中断条目并闭环 `TurnEnd`；
  - 验证 `prompts` 多条注入与两层循环（steering 与 follow_up）正确轮转。

- [ ] **Step 2: 运行测试并观察失败**
  - 运行 `uv run python -m pytest tests/test_agent_loop_pure.py -q`，观察因主循环重写产生的红灯。

- [ ] **Step 3: 重构 `run_agent_loop` 主状态机**
  - 组合使用 `_assistant_turn` 和 `_execute_tools_turn`；
  - 消除冗余的 30 处双通道事件广播，主状态机只负责 `yield event`。

- [ ] **Step 4: 运行测试并保证通过**
  - 运行 `uv run python -m pytest tests/test_agent_loop_pure.py -q`，确认全部纯微内核测试通过。

- [ ] **Step 5: Git 提交**
  - 提交：`refactor(loop): run_agent_loop 瘦身为主微内核状态机并实现严密时序与自愈闭环`

---

### Task 4: `ExtensionAPI` 强类型分流与 `Agent` 门面重构

**Files:**
- Modify: `packages/my-agent-core/src/my_agent_core/extensions/core.py`
- Modify: `packages/my-agent-core/src/my_agent_core/agent.py`
- Test: `packages/my-agent-core/tests/test_extensions.py`

**Interfaces:**
- Produces:
  - `ExtensionAPI.on(target, handler)`: 自动判断 `issubclass(target, Event)` 分流至只读观察者或决策拦截器；
  - `Agent.register_decision(decision_cls, handler)`: 注册五大专职拦截器；
  - `Agent.subscribe_event(event_cls, handler)`: 注册纯只读事件订阅；
  - `Agent.prompt_stream`: 消费 `run_agent_loop` 生成器并将只读事件分发给订阅者。

- [ ] **Step 1: 编写 ExtensionAPI 分流测试用例（TDD 先行）**
  - 测试通过 `@api.on(ToolCallDecision)` 注册拦截器并成功阻断工具调用；
  - 测试通过 `@api.on(TurnStart)` 注册只读观察者并成功捕获事件通知。

- [ ] **Step 2: 运行测试并观察失败**
  - 运行 `uv run python -m pytest tests/test_extensions.py -k test_extension_decision_points_end_to_end -q`，观察失败。

- [ ] **Step 3: 重构 `ExtensionAPI` 与 `Agent`**
  - 在 `ExtensionAPI` 中建立类型分流逻辑；
  - 在 `Agent` 中清晰划分 `_decisions`（拦截）与 `_event_subscribers`（只读）；
  - `Agent.prompt_stream` 将微内核 `yield` 的事件单向推送给订阅者，彻底消除双重发射。

- [ ] **Step 4: 运行扩展与代理基础单测**
  - 运行 `uv run python -m pytest tests/test_extensions.py -q` 保证通过。

- [ ] **Step 5: Git 提交**
  - 提交：`feat(extensions,agent): ExtensionAPI 强类型分流与 Agent 纯净门面装配`

---

### Task 5: 全量老单测重写（彻底消灭旧兼容包袱）

**Files:**
- Rewrite/Clean: `packages/my-agent-core/tests/test_agent.py`
- Rewrite/Clean: `packages/my-agent-core/tests/test_agent_nudge.py`
- Rewrite/Clean: `packages/my-agent-core/tests/test_extensions.py`
- Check: 其他所有 `tests/test_*.py`

**Principles:**
- 绝不保留 `Interceptable` 兼容；
- 旧测试若传入旧的 `hooks=[(UserInput, ...)]` 或旧的 `(ToolExecutionStart, ...)` 拦截写法，全部重写为符合新架构的五大独立 Decision 类或重写为针对新微内核的断言。

- [ ] **Step 1: 运行全量核心包测试定位陈旧用例**
  - 运行 `uv run python -m pytest packages/my-agent-core/tests/ -q`，收集所有失败的陈旧单测。

- [ ] **Step 2: 重写 `test_agent.py` 中的决策点测试**
  - 更新 UserInput 拦截阻断与改写测试；
  - 更新 AgentStart 拦截与 system_prompt 改写测试；
  - 更新 BeforeModelCall 拦截与临时视图注入测试；
  - 更新 ToolExecutionStart/End 拦截与改参改结果测试。

- [ ] **Step 3: 重写 `test_extensions.py` 与 `test_agent_nudge.py`**
  - 更新插件决策拦截与任务守卫测试。

- [ ] **Step 4: 运行核心包全量测试**
  - 运行 `cd packages/my-agent-core && uv run python -m pytest -q`，确保核心包全绿。

- [ ] **Step 5: Git 提交**
  - 提交：`test(core): 重写陈旧单测对齐新版正交事件与决策点架构，彻底移除兼容包袱`

---

### Task 6: 全 Monorepo 回归验证与全套文档同步提交

**Files:**
- Modify: `README.md`
- Modify: `PROGRESS.md`
- Modify: `packages/my-agent-core/README.md`
- Modify: `docs/core/02-event-hooks.md`
- Modify: `docs/core/03-agent-loop.md`

- [ ] **Step 1: 全 Monorepo 三包全量离线回归测试**
  - 运行：
    ```powershell
    cd packages/my-agent-core && uv run python -m pytest -q
    cd ../my-agent-llm && uv run python -m pytest -q
    cd ../my-coding-agent && uv run python -m pytest -q
    ```
  - 验证全部测试通过（无 skip, 无 xfail）。

- [ ] **Step 2: 运行代码静态检查与类型诊断**
  - 运行 `git status` 与 `ruff check` / `lsp_diagnostics`，确保零警告、零未处理异常。

- [ ] **Step 3: 同步全套文档体系**
  - 在 `PROGRESS.md` 中记录阶段 19 的重构里程碑与提交复盘；
  - 在 `README.md` 与 `packages/my-agent-core/README.md` 中更新事件与五大决策拦截点最新用法与接口说明；
  - 更新 `docs/core/02-event-hooks.md` 与 `docs/core/03-agent-loop.md` 对齐新架构。

- [ ] **Step 4: 最终 Git 提交**
  - 提交：`docs: 同步更新阶段19事件正交化与微内核分治架构文档与进度记录`

---

## 计划自审确认 (Self-Review Against Guidelines)

1. **是否有清晰的端到端用户价值？** 是，消灭双通道发射冗余，微内核从 550 行瘦身至 110 行，事件与决策点 100% 正交且具备强类型 IDE 补全；
2. **是否符合 TDD 规范？** 是，每个 Task 均标明了“Step 1: 编写失败测试 ➔ Step 2: 观察红灯 ➔ Step 3: 编写实现 ➔ Step 4: 验证绿灯 ➔ Step 5: 原子提交”；
3. **是否坚决贯彻了拒绝冗余兼容？** 是，在 Task 1、Task 5 中明确标明彻底删除 `Interceptable` 并重写陈旧单测，生产代码零妥协垫片；
4. **命令与文件路径是否完全具体？** 是，全量路径具体到文件、具体测试函数与执行命令，无任何通配模糊指引。
