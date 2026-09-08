# Tau 对齐与核心框架深度重构实施计划 (Tau Alignment & Deep Module Architecture Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 全面引入 Tau（`tau_agent`）的深度模块化设计，将 `my-agent-core` 演进为工业级高韧性微内核架构：实现 `tool_history.py` 对话转录本三阶段自愈、解耦 `session/` 子包（9 种多态条目、纯内存树、`SessionState` 不可变投影、纯内存存储）、提炼 `run_agent_loop` 纯函数生成器微内核并瘦身 `Agent` 上帝类，全程保持向后兼容与 100% 离线测试绿灯。

**Architecture:** 采用分层深度模块设计（Codebase Design 原则）：微内核层由无状态纯异步生成器 `run_agent_loop` 驱动；边界层由 `_provider_context` 与 `tool_history.py` 提供断头自愈防线；数据层由 `session/` 提供纯追加不可变日志与无锁内存状态折叠投影；外壳层由瘦身后的 `Agent` 提供极窄操作面并暴露原生事件流。

**Tech Stack:** Python 3.11+, `pydantic v2`, `asyncio`, `pytest`

**Spec:** `docs/core/13-tau-alignment-architecture-redesign.md`

---

## Global Constraints

- **Never-Throw Guarantee**：工具执行与历史修复算法永不上抛未捕获异常导致 Agent 崩溃；
- **Append-Only Invariant**：彻底废除破坏性重写历史逻辑，所有状态演进（分支切换、模型调整、压缩）皆为追加不可变实体；
- **100% Backward Compatibility**：`from my_agent_core.session import Session, SessionTree, SessionEntry` 与 `await agent.run("...")` 签名与行为完全保留；
- **Zero-Network Offline Tests**：所有单元测试必须基于 FakeLLM 与纯内存模拟，不依赖任何外部网络或真实文件锁竞争；
- **TDD (Test-Driven Development)**：每个任务均遵循“先写失败测试 ➔ 编写最小实现 ➔ 验证通过 ➔ 重构”的红-绿重构节奏。

---

### Task 1: 建立基线与验证 `tool_history.py` 自愈模块 (Milestone 1 Baseline)

**Files:**

- Production: `packages/my-agent-core/src/my_agent_core/tool_history.py`
- Test: `packages/my-agent-core/tests/test_tool_history.py`
- Integration: `packages/my-agent-core/src/my_agent_core/agent.py`

**Interfaces:**

- Produces:
  - `ToolHistoryRepair(messages: tuple[Message, ...], changed: bool, synthesized_results: int, dropped_orphan_results: int, dropped_duplicate_results: int, reordered_results: int)`
  - `repair_tool_history(messages: Sequence[Message]) -> ToolHistoryRepair`
  - `_INTERRUPTED_TOOL_RESULT = "Tool call interrupted by user"`

- [x] **Step 1: 编写 `test_tool_history.py` 8 项测试**
  - 覆盖正常历史不变、悬空中断合成、多并发中断保序补齐、孤儿结果剔除、错位重排、同名 ID 跨轮次隔离、诊断数据生成与 Agent Abort 自愈恢复。
- [x] **Step 2: 交付 `tool_history.py` 三阶段确定性状态机**
  - Phase 1 就近预留 ➔ Phase 2 贪心匹配/合成中断 ➔ Phase 2.5 真实反超 ➔ Phase 3 重构与孤儿丢弃。
- [x] **Step 3: 接入 `agent.py` 执行前置与 Abort 取消边界**
  - 恢复消息时前置自愈，Abort 退出时即刻合成补齐断头调用并落盘。
- [x] **Step 4: 运行全量测试验证基线**
  - 命令：`cd packages/my-agent-core && uv run python -m pytest -q`
  - 验证：254 项测试全部通过，全仓库 312 项测试全绿（Commit `580f98f`）。

---

### Task 2: 会话实体多态化 (`session/entries.py`) 与纯内存树算法 (`session/tree.py`) (Milestone 2.1)

**Files:**

- Create: `packages/my-agent-core/src/my_agent_core/session/entries.py`
- Create: `packages/my-agent-core/src/my_agent_core/session/tree.py`
- Test: `packages/my-agent-core/tests/test_session_tree_modular.py`

**Interfaces:**

- Produces:
  - `BaseSessionEntry(id: str, parent_id: str | None, timestamp: float)`
  - 9 种多态判别实体：`SessionInfoEntry`, `MessageEntry`, `ModelChangeEntry`, `ThinkingLevelChangeEntry`, `CompactionEntry`, `BranchSummaryEntry`, `LabelEntry`, `LeafEntry`, `CustomEntry`
  - `SessionEntry = Annotated[Union[...], Field(discriminator="type")]`
  - `entries_by_id(entries: Sequence[SessionEntry]) -> dict[str, SessionEntry]` (带重复 ID 防御)
  - `path_to_entry(entries: Sequence[SessionEntry], leaf_id: str) -> list[SessionEntry]` (带 `seen` 集合环路检测)

- [ ] **Step 1: 编写 `test_session_tree_modular.py` 失败测试**
  - 测试 9 种 `SessionEntry` 类型的 Pydantic v2 判别联合体序列化与反序列化；
  - 测试 `entries_by_id` 遇到重复 ID 抛出 `SessionTreeError`；
  - 测试 `path_to_entry` 正确提取根到叶节点路径，遇到缺失父节点报错，遇到循环死锁引用抛出 `Cycle detected`。
- [ ] **Step 2: 运行测试并确认失败 (RED)**
  - 命令：`uv run python -m pytest tests/test_session_tree_modular.py`
  - 预期失败原因：`ModuleNotFoundError: No module named 'my_agent_core.session.entries'`。
- [ ] **Step 3: 实现 `session/entries.py`**
  - 使用 Pydantic v2 `BaseModel` 定义 `BaseSessionEntry`（`extra="forbid"`，驼峰别名与蛇形互转）；
  - 定义 9 种具体实体，使用 `type: Literal[...]` 作为判别字段；
  - 组装 `SessionEntry` 联合类型。
- [ ] **Step 4: 实现 `session/tree.py`**
  - 定义 `SessionTreeError(ValueError)`；
  - 实现纯内存纯函数 `entries_by_id`（重复 ID 校验）；
  - 实现 `path_to_entry`，采用循环迭代与 `seen: set[str]` 防死锁探测，零 I/O 依赖。
- [ ] **Step 5: 运行单测验证绿灯 (GREEN)**
  - 命令：`uv run python -m pytest tests/test_session_tree_modular.py`
  - 验证全部断言通过。
- [ ] **Step 6: 提交代码**
  - `git add packages/my-agent-core/src/my_agent_core/session/ packages/my-agent-core/tests/test_session_tree_modular.py`
  - `git commit -m "feat(session): 实现 9 种多态判别实体与纯内存防环树算法"`

---

### Task 3: 纯内存状态折叠投影 (`session/memory.py`) 与纯追加存储协议 (`session/storage.py`) (Milestone 2.2)

**Files:**

- Create: `packages/my-agent-core/src/my_agent_core/session/memory.py`
- Create: `packages/my-agent-core/src/my_agent_core/session/storage.py`
- Test: `packages/my-agent-core/tests/test_session_memory_and_storage.py`

**Interfaces:**

- Produces:
  - `SessionState`: 不可变状态快照（`messages`, `model`, `provider`, `thinking_level`, `label`, `active_leaf_id`）
  - `SessionState.from_entries(entries: Sequence[SessionEntry], leaf_id: str | None = None) -> SessionState` (事件溯源纯函数折叠，自动应用 Compaction 覆盖)
  - `SessionStorage(Protocol)`: 异步接口（`append(entry)`, `append_batch(entries)`, `read_all()`）
  - `InMemorySessionStorage`: 纯内存存储驱动，极速单测无磁盘文件

- [ ] **Step 1: 编写 `test_session_memory_and_storage.py` 失败测试**
  - 测试 `SessionState.from_entries` 顺次折叠 `SessionInfoEntry`、`MessageEntry`、`ModelChangeEntry`、`ThinkingLevelChangeEntry`；
  - 测试遇到 `CompactionEntry` 时自动将历史条目折叠为摘要消息；
  - 测试 `InMemorySessionStorage` 的异步 `append`、`append_batch` 与 `read_all` 契约。
- [ ] **Step 2: 运行测试并确认失败 (RED)**
  - 命令：`uv run python -m pytest tests/test_session_memory_and_storage.py`
  - 预期失败：缺少 `memory.py` 与 `storage.py`。
- [ ] **Step 3: 实现 `session/memory.py`**
  - 编写不可变 dataclass `SessionState`；
  - 实现纯函数投影 `from_entries`：提取路径条目，线性模式匹配 `entry.type`；
  - 实现 `_apply_compaction`：将 `replaces_entry_ids` 范围内的消息折叠为一条 `UserMessage("Previous conversation summary:\n...")`。
- [ ] **Step 4: 实现 `session/storage.py`**
  - 定义 `SessionStorage(Protocol)` 异步存储契约（彻底移除 `rewrite_history`）；
  - 实现 `InMemorySessionStorage`，使用内部列表 `self._entries: list[SessionEntry]` 配合 `asyncio.Lock` 实现纯内存高性能读写。
- [ ] **Step 5: 运行单测验证绿灯 (GREEN)**
  - 命令：`uv run python -m pytest tests/test_session_memory_and_storage.py`
  - 验证所有状态折叠与内存存储逻辑通过。
- [ ] **Step 6: 提交代码**
  - `git add packages/my-agent-core/src/my_agent_core/session/ packages/my-agent-core/tests/test_session_memory_and_storage.py`
  - `git commit -m "feat(session): 实现纯函数 SessionState 事件折叠与纯内存存储驱动"`

---

### Task 4: JSONL 持久化驱动 (`session/jsonl.py`) 与向后兼容门面 (`session/__init__.py`) (Milestone 2.3)

**Files:**

- Create: `packages/my-agent-core/src/my_agent_core/session/jsonl.py`
- Modify: `packages/my-agent-core/src/my_agent_core/session/__init__.py`
- Refactor: `packages/my-agent-core/src/my_agent_core/session.py` (桥接与兼容别名)
- Test: `packages/my-agent-core/tests/test_session.py` (现有 17 项测试必须全部通过)

**Interfaces:**

- Produces:
  - `JsonlSessionStorage(path: Path | str)`: 基于文件追加的 `SessionStorage` 实现，支持 `.{name}.lock` 跨进程锁与未完成 `.tmp` 自动自愈清理
  - 向后兼容导出：`Session`, `SessionTree`, `SessionEntry`，确保外部 312 项测试零断裂

- [ ] **Step 1: 编写 `test_session_jsonl_modular.py` 测试**
  - 测试行级 JSONL 追加写入与恢复；
  - 测试残留 `.tmp` 文件在初始化时被安全清理（自愈）；
  - 测试多进程锁竞争时安全排队。
- [ ] **Step 2: 运行测试并确认失败 (RED)**
  - 命令：`uv run python -m pytest tests/test_session_jsonl_modular.py`
- [ ] **Step 3: 实现 `session/jsonl.py`**
  - 实现 `JsonlSessionStorage`，使用追加模式 `a+` 写入每行 JSON；
  - 引入 `_remove_incomplete_temp()` 在持有锁时清理异常中断遗留的临时碎片；
  - 实现 `_migrate_session_entry` 兼容旧版文件头与遗留格式。
- [ ] **Step 4: 装配 `session/__init__.py` 与重构 `session.py` 门面**
  - 将原 `Session` 内部重构为委托给 `SessionStorage` 与 `SessionState`；
  - 保持 `session.add_message`、`session.rewind`、`session.fork` 外部行为 100% 一致。
- [ ] **Step 5: 运行全量会话测试验证 (GREEN)**
  - 命令：`uv run python -m pytest tests/test_session.py tests/test_session_store.py tests/test_session_jsonl_modular.py`
  - 确保现有测试与新模块测试无缝全绿。
- [ ] **Step 6: 提交代码**
  - `git add packages/my-agent-core/src/my_agent_core/session/ packages/my-agent-core/src/my_agent_core/session.py packages/my-agent-core/tests/test_session_jsonl_modular.py`
  - `git commit -m "refactor(session): 拆解 session 单文件为模块化子包并提供向后兼容门面"`

---

### Task 5: 提炼 ReAct 纯函数微内核 (`loop.py`) 与上下文前置清洗 (`_provider_context`) (Milestone 3)

**Files:**

- Create: `packages/my-agent-core/src/my_agent_core/loop.py`
- Test: `packages/my-agent-core/tests/test_agent_loop_pure.py`

**Interfaces:**

- Produces:
  - `_provider_context(messages: list[Message]) -> list[Message]`: 剔除空失败轮次并串联 `repair_tool_history`
  - `run_agent_loop(...) -> AsyncIterator[AgentEvent]`: 纯函数 ReAct 事件流生成器微内核

- [ ] **Step 1: 编写 `test_agent_loop_pure.py` 失败测试**
  - 构造 `FakeLLM`，验证 `run_agent_loop` 独立运行并按序产生 `AgentStart`、`TurnStart`、`MessageUpdate`、`ToolExecutionStart`、`TurnEnd`、`AgentEnd`；
  - 验证 `_provider_context` 能安全剥离 `stop_reason="error"` 且 `content=""` 的中断失败消息；
  - 验证 `get_steering_messages` 与 `get_follow_up_messages` 在微内核内实现双层循环自动收割。
- [ ] **Step 2: 运行测试并确认失败 (RED)**
  - 命令：`uv run python -m pytest tests/test_agent_loop_pure.py`
- [ ] **Step 3: 实现 `packages/my-agent-core/src/my_agent_core/loop.py`**
  - 从 `agent.py:350-575` 剥离双层循环逻辑，提炼为纯无状态异步生成器 `run_agent_loop`；
  - 接入 `_provider_context` 保证送入 `achat_stream` 的消息 100% 合法；
  - 规范成对派发 `TurnEnd` 与 `AgentEnd`。
- [ ] **Step 4: 运行微内核测试验证 (GREEN)**
  - 命令：`uv run python -m pytest tests/test_agent_loop_pure.py`
- [ ] **Step 5: 提交代码**
  - `git add packages/my-agent-core/src/my_agent_core/loop.py packages/my-agent-core/tests/test_agent_loop_pure.py`
  - `git commit -m "feat(core): 提炼纯函数 ReAct 微内核 run_agent_loop 与 _provider_context 清洗"`

---

### Task 6: `Agent` 瘦身为轻量 Harness 并暴露事件流生成器 (Milestone 4 & 全量回归)

**Files:**

- Modify: `packages/my-agent-core/src/my_agent_core/agent.py`
- Test: 全仓库所有现有测试（`tests/`）

**Interfaces:**

- Produces:
  - `Agent.prompt_stream(user_input: str) -> AsyncIterator[Event]`: 原生事件流一等公民接口
  - `Agent.run(user_input: str) -> str | None`: 经典便利接口（内部消费 `prompt_stream`）
  - 核心循环代码彻底委托给 `run_agent_loop`，`agent.py` 减少 200+ 行重复调度逻辑

- [ ] **Step 1: 编写事件流验证测试**
  - 在 `tests/test_agent.py` 中增加 `test_agent_prompt_stream_emits_events`，验证外部可直接 `async for event in agent.prompt_stream(...)`。
- [ ] **Step 2: 重构 `Agent` 内部调度流**
  - `Agent.prompt_stream` 调用 `run_agent_loop`，同时更新内部 `self.messages` 与 `self.session`；
  - `Agent.run` 实现为：

    ```python
    async def run(self, user_input: str) -> str | None:
        final_text = None
        async for event in self.prompt_stream(user_input):
            if isinstance(event, AgentEnd):
                final_text = event.final_text
        return final_text
    ```

- [ ] **Step 3: 全仓库 312+ 测试全量回归验证**
  - 运行：

    ```powershell
    cd packages/my-agent-core && uv run python -m pytest -q
    cd ../my-agent-llm && uv run python -m pytest -q
    cd ../my-coding-agent && uv run python -m pytest -q
    ```

  - 保证每一个测试包 100% 绿灯，绝无任何回归退化。
- [ ] **Step 4: 运行 `lens_diagnostics(mode="all")` 静态代码体检**
  - 确保新增与修改的所有文件零类型报错、零警告。
- [ ] **Step 5: 提交最终重构成果**
  - `git add packages/my-agent-core/src/my_agent_core/agent.py packages/my-agent-core/tests/test_agent.py`
  - `git commit -m "refactor(agent): 将 Agent 瘦身为轻量 Harness，委托 run_agent_loop 并提供 prompt_stream 事件流"`

---

## 检查点与执行确认 (Checkpoints)

1. **Task 1 验收**：`repair_tool_history` 已完成并集成，312 项单测全绿；
2. **Task 2~4 验收**：`session/` 模块化完成，内存驱动使单测提速，老接口兼容无损；
3. **Task 5~6 验收**：微内核纯函数化，提供原生 `prompt_stream` 事件流，架构与 Tau 达到 1:1 镜像级优雅。
