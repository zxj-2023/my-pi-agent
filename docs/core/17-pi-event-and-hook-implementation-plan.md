# Pi-Style Event & Hook Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decouple read-only lifecycle events from decision interception points, decompose the 550-line ReAct loop microkernel into Tau-style focused sub-generators, align tool execution lifecycles with Pi timing, and rewrite obsolete tests to achieve a clean, zero-redundancy architecture.

**Architecture:**

1. Orthogonal separation: `Event` is purely an immutable, read-only data structure broadcast downstream without return values. Control flow intervention is cleanly isolated into five typed `HookPoint` classes (`UserInputHook`, `AgentStartHook`, `BeforeModelCallHook`, `ToolCallHook`, `ToolResultHook`) evaluated via `HookRegistry` returning `HookResult`.
2. Generator decomposition: `loop.py` is decomposed into two dedicated sub-generators (`_assistant_turn` for unified streaming & token aggregation, `_execute_tools_turn` for Pi-aligned Preflight ➔ Execution ➔ Completion lifecycle) and a centralized `_synthesize_interrupted_tool_calls` helper, slimming `run_agent_loop` down to a pure ~110-line state machine.
3. No-compromise test rewriting: Obsolete tests asserting `Interceptable` or legacy hook dual-dispatch are rewritten directly to test the new clean architecture without backwards-compatibility padding.

**Tech Stack:** Python 3.11+, `asyncio`, `dataclasses`, `pydantic` v2, `pytest`, `basedpyright`.

**Spec:** `docs/core/16-pi-event-and-hook-architecture-design.md`

## Global Constraints

- Target Python 3.11+ with 4-space indentation and explicit type annotations.
- 100% offline unit tests using `FakeLLM` / mock SDKs. No network access or API keys.
- Never-Throw guarantee: Tools, sub-generators, and decision hooks must never raise unhandled exceptions to the top caller; exceptions are converted into descriptive error messages.
- Pure native async API: `Agent.prompt_stream(prompt)` yields `Event` stream; `Agent.run(prompt)` returns `str | None`.
- Lifecycle event pairing invariant: Every started turn MUST emit a closing `TurnEnd`, even on early exit, model error, cancellation, or security block.
- Zero dangling tool calls: If execution is interrupted during tool calling, unexecuted calls must be synthesized as `is_error=True` tool messages before exit to prevent LLM API 400 errors.
- Pi timing order: `ToolExecutionStart` is emitted in source order during Preflight BEFORE `before_tool_call` and tool execution; `ToolExecutionEnd` is emitted as tools finish; `MessageStart`/`MessageEnd` for tools are emitted in source order.
- Prefix cache invariant: System prompt remains 100% static across turns; dynamic task boards/state stay out of `view[0]`.
- No redundant backwards-compatibility padding: Legacy `Interceptable` mixin is removed. Tests expecting old patterns are rewritten directly.

---

## File Structure

```text
packages/my-agent-core/
├── src/my_agent_core/
│   ├── events.py              # Pure read-only Events, 5 HookPoints, HookResult, HookRegistry
│   ├── loop.py                # _stream_llm, _assistant_turn, _execute_tools_turn, run_agent_loop (~110 lines)
│   ├── extensions/
│   │   └── core.py            # ExtensionAPI.on() dispatching between Event subscription and Decision registration
│   └── agent.py               # Agent Harness wiring HookRegistry, subscribers, and callbacks
└── tests/
    ├── test_events.py         # Rewritten: test pure Event immutability, HookPoints, HookRegistry
    ├── test_loop_subgenerators.py # New: unit tests for _assistant_turn, _execute_tools_turn, _stream_llm
    ├── test_agent_loop_pure.py    # Updated: test pure ~110-line run_agent_loop with new decision callbacks
    ├── test_extensions.py     # Updated: test @api.on(ToolCallHook) and @api.on(TurnStart)
    └── test_agent.py          # Updated: test decision blocking/rewriting via agent.decisions
```

---

### Task 1: Refactor `events.py` & Rewrite `test_events.py`

**Files:**

- Modify: `packages/my-agent-core/src/my_agent_core/events.py`
- Modify: `packages/my-agent-core/tests/test_events.py`

**Interfaces:**

- Produces:
  - `Event`: base immutable dataclass with `timestamp: float`.
  - Read-only events: `AgentStart`, `AgentEnd`, `TurnStart`, `TurnEnd(message: Message | None = None, tool_results: list[Message] = field(default_factory=list))`, `MessageStart`, `MessageUpdate`, `MessageEnd`, `ToolExecutionStart`, `ToolExecutionUpdate`, `ToolExecutionEnd`, `ContextCompacted`, `ToolsChanged`.
  - Five Decision classes: `UserInputHook(input_text: str)`, `AgentStartHook(system_prompt: str)`, `BeforeModelCallHook(messages: list[Message], iteration: int)`, `ToolCallHook(tool_call_id: str, tool_name: str, args: dict[str, Any])`, `ToolResultHook(tool_call_id: str, tool_name: str, result: str, is_error: bool)`.
  - `HookResult`: dataclass with `block`, `reason`, `updated_input`, `updated_system_prompt`, `updated_messages`, `updated_args`, `updated_result`.
  - `HookRegistry`: registers and emits decisions for the 5 decision classes. Supports async and sync handlers with Never-Throw isolation.
  - `HookRegistry`: alias to `HookRegistry` for smooth internal usage.

- [ ] **Step 1: Write the failing test in `test_events.py`**

Rewrite `packages/my-agent-core/tests/test_events.py` to assert:

1. `Event` subclasses are pure frozen dataclasses with `timestamp`.
2. `Interceptable` does NOT exist in `events.py`.
3. The 5 Decision classes exist, are frozen dataclasses, and contain the expected attributes.
4. `TurnEnd` can be initialized with `message=None` and `tool_results=[]`.
5. `HookRegistry` (and alias `HookRegistry`) executes handlers, returns the first non-None `HookResult`, and catches exceptions without raising.

```python
# packages/my-agent-core/tests/test_events.py
import pytest
from my_agent_core.events import (
    Event,
    AgentStart,
    AgentEnd,
    TurnStart,
    TurnEnd,
    MessageStart,
    MessageUpdate,
    MessageEnd,
    ToolExecutionStart,
    ToolExecutionUpdate,
    ToolExecutionEnd,
    ContextCompacted,
    UserInputHook,
    AgentStartHook,
    BeforeModelCallHook,
    ToolCallHook,
    ToolResultHook,
    HookResult,
    HookRegistry,
    HookRegistry,
)
from my_agent_llm import Message

def test_events_are_pure_frozen_dataclasses():
    ev = TurnStart(iteration=1)
    assert isinstance(ev, Event)
    assert hasattr(ev, "timestamp")
    with pytest.raises(Exception):
        ev.iteration = 2  # frozen

def test_turn_end_nullable_message():
    te = TurnEnd(message=None, tool_results=[])
    assert te.message is None
    assert te.tool_results == []

def test_decision_points_attributes():
    uid = UserInputHook(input_text="hello")
    assert uid.input_text == "hello"
    
    tcd = ToolCallHook(tool_call_id="call_1", tool_name="bash", args={"cmd": "ls"})
    assert tcd.tool_call_id == "call_1"
    assert tcd.tool_name == "bash"
    assert tcd.args == {"cmd": "ls"}

@pytest.mark.asyncio
async def test_decision_registry_emit_and_short_circuit():
    reg = HookRegistry()
    calls = []

    async def guard(d: ToolCallHook):
        calls.append(d.tool_name)
        return HookResult(block=True, reason="forbidden")

    async def second_guard(d: ToolCallHook):
        calls.append("should_not_run")
        return None

    reg.register(ToolCallHook, guard)
    reg.register(ToolCallHook, second_guard)

    res = await reg.emit(ToolCallHook(tool_call_id="1", tool_name="rm", args={}))
    assert res is not None
    assert res.block is True
    assert res.reason == "forbidden"
    assert calls == ["rm"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/my-agent-core && uv run python -m pytest tests/test_events.py -v`
Expected: FAIL (missing Decision classes or `TurnEnd` signature mismatch).

- [ ] **Step 3: Implement `events.py`**

Refactor `packages/my-agent-core/src/my_agent_core/events.py` according to the spec:

- Remove `Interceptable`.
- Update `TurnEnd(message: Message | None = None, tool_results: list[Message] = field(default_factory=list))`.
- Define the 5 Decision dataclasses: `UserInputHook`, `AgentStartHook`, `BeforeModelCallHook`, `ToolCallHook`, `ToolResultHook`.
- Implement `HookRegistry` with `register`, `unregister`, and async `emit(decision)` with exception suppression.
- Export `HookRegistry = HookRegistry`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd packages/my-agent-core && uv run python -m pytest tests/test_events.py -v`
Expected: PASS (all tests in `test_events.py` pass).

- [ ] **Step 5: Commit**

```bash
git add packages/my-agent-core/src/my_agent_core/events.py packages/my-agent-core/tests/test_events.py
git commit -m "refactor(core): 正交解耦只读事件流与五大决策拦截点，彻底移除 Interceptable"
```

---

### Task 2: Implement Loop Sub-generators in `loop.py` & Add Unit Tests

**Files:**

- Create: `packages/my-agent-core/tests/test_loop_subgenerators.py`
- Modify: `packages/my-agent-core/src/my_agent_core/loop.py`

**Interfaces:**

- Consumes:
  - `Message`, `StreamChunk` from `my_agent_llm`.
  - `Event`, `MessageStart`, `MessageUpdate`, `MessageEnd`, `ToolExecutionStart`, `ToolExecutionEnd`, `ToolCallHook`, `ToolResultHook`, `HookResult` from `my_agent_core.events`.
  - `ToolRegistry`, `ToolResult` from `my_agent_core.registry`.
- Produces:
  - `async def _stream_llm(llm, messages, tool_schemas, model=None) -> AsyncIterator[StreamChunk]`
  - `async def _assistant_turn(llm, view, tool_schemas, model, signal, context_manager) -> AsyncIterator[AgentEvent]`
  - `def _synthesize_interrupted_tool_calls(tool_calls) -> list[Message]`
  - `async def _execute_tools_turn(tool_calls, registry, before_tool_call, after_tool_call, signal) -> AsyncIterator[AgentEvent]`

- [ ] **Step 1: Write the failing test in `test_loop_subgenerators.py`**

Test the 4 sub-generators in isolation:

1. `_stream_llm` works for both streaming and non-streaming fake LLMs.
2. `_assistant_turn` emits `MessageUpdate` chunks and finishes with `MessageStart` + `MessageEnd`.
3. `_execute_tools_turn` emits `ToolExecutionStart` during Preflight in source order BEFORE calling `before_tool_call`, supports `before_tool_call` blocking and arg rewriting, executes tools concurrently via `registry.execute_batch`, applies `after_tool_call` result rewriting, emits `ToolExecutionEnd`, and finishes with `MessageStart` + `MessageEnd` for role `tool`.
4. `_execute_tools_turn` handles cancellation: when `signal.cancel()` is active, it synthesizes `_INTERRUPTED_TOOL_RESULT` for unexecuted calls with `is_error=True`.

```python
# packages/my-agent-core/tests/test_loop_subgenerators.py
import pytest
from my_agent_core.loop import (
    _stream_llm,
    _assistant_turn,
    _execute_tools_turn,
    _synthesize_interrupted_tool_calls,
)
from my_agent_core.events import (
    ToolExecutionStart,
    ToolExecutionEnd,
    MessageStart,
    MessageEnd,
    ToolCallHook,
    ToolResultHook,
    HookResult,
)
from my_agent_core.registry import ToolRegistry, tool
from my_agent_core.agent import CancellationToken
from my_agent_llm import Message, Response

class FakeStreamLLM:
    async def achat_stream(self, messages, tools=None, model=None):
        from my_agent_llm import StreamChunk
        yield StreamChunk(content="Hello ")
        yield StreamChunk(content="world!")

@pytest.mark.asyncio
async def test_assistant_turn_streaming():
    llm = FakeStreamLLM()
    events = []
    async for ev in _assistant_turn(
        llm=llm,
        view=[Message(role="user", content="hi")],
        tool_schemas=[],
        model=None,
        signal=None,
        context_manager=None,
    ):
        events.append(ev)

    assert len(events) >= 3
    assert isinstance(events[-1], MessageEnd)
    assert events[-1].message.content == "Hello world!"

@pytest.mark.asyncio
async def test_execute_tools_turn_pi_timing_and_blocking():
    reg = ToolRegistry()
    @tool(description="echo")
    def echo(text: str) -> str:
        return f"echo: {text}"
    reg.register(echo)

    tool_calls = [
        {"id": "call_1", "function": {"name": "echo", "arguments": '{"text": "safe"}'}},
        {"id": "call_2", "function": {"name": "echo", "arguments": '{"text": "blocked"}'}},
    ]

    async def guard(decision: ToolCallHook):
        if decision.args.get("text") == "blocked":
            return HookResult(block=True, reason="policy violation")
        return None

    events = []
    async for ev in _execute_tools_turn(
        tool_calls=tool_calls,
        registry=reg,
        before_tool_call=guard,
        after_tool_call=None,
        signal=None,
    ):
        events.append(ev)

    # 1. Preflight starts emitted in source order first
    starts = [e for e in events if isinstance(e, ToolExecutionStart)]
    assert len(starts) == 2
    assert starts[0].tool_call_id == "call_1"
    assert starts[1].tool_call_id == "call_2"

    # 2. Ends emitted
    ends = [e for e in events if isinstance(e, ToolExecutionEnd)]
    assert len(ends) == 2
    assert ends[0].tool_call_id == "call_1" and not ends[0].is_error
    assert ends[1].tool_call_id == "call_2" and ends[1].is_error
    assert "blocked: policy violation" in ends[1].result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/my-agent-core && uv run python -m pytest tests/test_loop_subgenerators.py -v`
Expected: FAIL (functions not yet implemented or imported).

- [ ] **Step 3: Implement sub-generators in `loop.py`**

In `packages/my-agent-core/src/my_agent_core/loop.py`:

- Add `_stream_llm`.
- Add `_assistant_turn`.
- Add `_synthesize_interrupted_tool_calls`.
- Add `_execute_tools_turn` strictly respecting Pi timing (Preflight `ToolExecutionStart` broadcast in source order ➔ `before_tool_call` ➔ batch execution ➔ `after_tool_call` ➔ `ToolExecutionEnd` ➔ `MessageStart/End(tool)` in source order) and cancellation self-healing.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd packages/my-agent-core && uv run python -m pytest tests/test_loop_subgenerators.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/my-agent-core/src/my_agent_core/loop.py packages/my-agent-core/tests/test_loop_subgenerators.py
git commit -m "feat(core): 实现 loop.py 专属子生成器 _stream_llm, _assistant_turn 与 _execute_tools_turn"
```

---

### Task 3: Refactor `run_agent_loop` & Update `test_agent_loop_pure.py`

**Files:**

- Modify: `packages/my-agent-core/src/my_agent_core/loop.py`
- Modify: `packages/my-agent-core/tests/test_agent_loop_pure.py`

**Interfaces:**

- Consumes:
  - `_assistant_turn`, `_execute_tools_turn`, `_synthesize_interrupted_tool_calls`.
  - `BeforeModelCallHook`, `ToolCallHook`, `ToolResultHook`.
- Produces:
  - `run_agent_loop(llm, messages, tools, context_manager, model, system, prompts, max_turns, max_iterations, signal, get_steering_messages, get_follow_up_messages, before_model_call, before_tool_call, after_tool_call) -> AsyncIterator[AgentEvent]`
  - Slim ~110 lines state machine.
  - Zero dual dispatch (`hook_registry` parameter removed).
  - Explicit turn closure: `TurnEnd` paired with every `TurnStart`.
  - Proper `max_turns` / `max_iterations` truncation.
  - Proper steering message injection at turn start.

- [ ] **Step 1: Write/update failing test in `test_agent_loop_pure.py`**

Update `packages/my-agent-core/tests/test_agent_loop_pure.py`:

- Update `test_run_agent_loop_before_model_call_blocking` to use `before_model_call` callback returning `HookResult(block=True)`. Assert `TurnEnd(message=None, tool_results=[])` is emitted paired with `TurnStart`.
- Verify `max_iterations` truncation emits `AgentEnd(stop_reason="max_iterations")`.
- Verify steering injection during inner loop.

```python
# In test_agent_loop_pure.py
@pytest.mark.asyncio
async def test_run_agent_loop_before_model_call_blocking():
    llm = FakeLLM(responses=[Response(content="never called")])
    messages = []
    
    async def block_model_call(decision: BeforeModelCallHook):
        return HookResult(block=True, reason="budget exceeded")

    events = []
    async for ev in run_agent_loop(
        llm=llm,
        messages=messages,
        prompts=["test prompt"],
        before_model_call=block_model_call,
    ):
        events.append(ev)

    event_types = [type(e) for e in events]
    assert TurnStart in event_types
    assert TurnEnd in event_types
    turn_end = [e for e in events if isinstance(e, TurnEnd)][0]
    assert turn_end.message is None
    
    agent_end = [e for e in events if isinstance(e, AgentEnd)][0]
    assert agent_end.stop_reason == "blocked"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/my-agent-core && uv run python -m pytest tests/test_agent_loop_pure.py -v`
Expected: FAIL (argument mismatch or legacy loop behavior).

- [ ] **Step 3: Refactor `run_agent_loop` in `loop.py`**

Refactor `run_agent_loop` in `packages/my-agent-core/src/my_agent_core/loop.py` to the clean ~110-line implementation from the spec:

- Remove legacy `hook_registry` argument.
- Accept explicit typed callbacks: `before_model_call`, `before_tool_call`, `after_tool_call`.
- Handle `pending_messages` steering injection and clearing at the start of each turn.
- Handle `max_turns` / `max_iterations` threshold check.
- Delegate model turns to `_assistant_turn` and tool executions to `_execute_tools_turn`.
- Ensure strictly paired `TurnEnd` on every exit path.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd packages/my-agent-core && uv run python -m pytest tests/test_agent_loop_pure.py -v`
Expected: PASS (all pure loop tests pass).

- [ ] **Step 5: Commit**

```bash
git add packages/my-agent-core/src/my_agent_core/loop.py packages/my-agent-core/tests/test_agent_loop_pure.py
git commit -m "refactor(core): 重塑 run_agent_loop 为 110 行纯粹状态机，消除双通道冗余发射"
```

---

### Task 4: Refactor `ExtensionAPI` & `Agent` Harness Wiring

**Files:**

- Modify: `packages/my-agent-core/src/my_agent_core/extensions/core.py`
- Modify: `packages/my-agent-core/src/my_agent_core/agent.py`
- Modify: `packages/my-agent-core/tests/test_extensions.py`
- Modify: `packages/my-agent-core/tests/test_agent.py`

**Interfaces:**

- Consumes:
  - `HookRegistry`, `Event`, `UserInputHook`, `AgentStartHook`, `BeforeModelCallHook`, `ToolCallHook`, `ToolResultHook` from `my_agent_core.events`.
  - `run_agent_loop` from `my_agent_core.loop`.
- Produces:
  - `ExtensionAPI.on(target, handler)`: dynamically routes to event subscription or decision registration.
  - `Agent.decisions`: instance of `HookRegistry`.
  - `Agent.subscribe(listener)`: pure read-only event stream subscription.
  - `Agent.prompt_stream(user_input)`: passes decision callbacks to `run_agent_loop`.

- [ ] **Step 1: Write failing tests in `test_extensions.py` and `test_agent.py`**

Rewrite obsolete tests in `tests/test_extensions.py` and `tests/test_agent.py`:

- Test `@api.on(ToolCallHook)` allows blocking and arg rewriting.
- Test `@api.on(TurnStart)` receives read-only turn start events.
- Test `agent.decisions.register(UserInputHook, ...)` blocks execution.
- Test `agent.decisions.register(AgentStartHook, ...)` rewrites system prompt.

```python
# In test_extensions.py
@pytest.mark.asyncio
async def test_extension_on_decision_point():
    agent = Agent(llm=FakeLLM())
    api = ExtensionAPI(agent)

    @api.on(ToolCallHook)
    async def block_bash(decision: ToolCallHook, api_ref: ExtensionAPI):
        if decision.tool_name == "bash":
            return HookResult(block=True, reason="bash disabled by extension")
        return None

    res = await agent.decisions.emit(ToolCallHook("1", "bash", {}))
    assert res is not None
    assert res.block is True
    assert res.reason == "bash disabled by extension"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/my-agent-core && uv run python -m pytest tests/test_extensions.py tests/test_agent.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `ExtensionAPI` and `Agent` Harness Wiring**

1. In `packages/my-agent-core/src/my_agent_core/extensions/core.py`:
   - Update `ExtensionAPI.on(target, handler)`:
     - If `issubclass(target, Event)`: registers listener with `self.agent.subscribe(...)` (ignoring return value).
     - Else: registers decision handler with `self.agent.decisions.register(target, wrapped)`.
2. In `packages/my-agent-core/src/my_agent_core/agent.py`:
   - Replace `self.hooks` with `self.decisions = HookRegistry()`.
   - Provide `self.hooks` alias pointing to `self.decisions` if needed for basic registration compatibility.
   - In `prompt_stream()`:
     - Invoke `UserInputHook` through `self.decisions.emit()`.
     - Call `run_agent_loop` with:
       - `before_model_call=self.decisions.emit`
       - `before_tool_call=self.decisions.emit`
       - `after_tool_call=self.decisions.emit`
   - In `AgentStart`, if `AgentStartHook` is registered, invoke it and apply `updated_system_prompt`.
   - Dispatch read-only events directly to `self._subscribers`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd packages/my-agent-core && uv run python -m pytest tests/test_extensions.py tests/test_agent.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/my-agent-core/src/my_agent_core/extensions/core.py packages/my-agent-core/src/my_agent_core/agent.py packages/my-agent-core/tests/test_extensions.py packages/my-agent-core/tests/test_agent.py
git commit -m "refactor(core): 升级 ExtensionAPI 与 Agent Harness 装配，实现决策分流与纯粹事件订阅"
```

---

### Task 5: Full Regression Suite Verification & Static Type Checking

**Files:**

- Modify: `tests/` across packages if any stale references remain
- Verify: all 3 packages (`packages/my-agent-core`, `packages/my-agent-llm`, `packages/my-coding-agent`)

**Interfaces:**

- Consumes: All updated framework components.
- Produces: 100% green test suite (378+ passing offline tests) and 0 static type diagnostics.

- [ ] **Step 1: Run core package tests and fix any stale test references**

Run: `cd packages/my-agent-core && uv run python -m pytest -q`
Expected: All tests pass. If any other test file referenced `Interceptable` or old `hook_registry`, update the test to use the new decision points directly.

- [ ] **Step 2: Run LLM package tests**

Run: `cd packages/my-agent-llm && uv run python -m pytest -q`
Expected: 36/36 passed.

- [ ] **Step 3: Run coding agent package tests**

Run: `cd packages/my-coding-agent && uv run python -m pytest -q`
Expected: 22/22 passed.

- [ ] **Step 4: Run static type check diagnostics**

Check LSP / pyright diagnostics using `lsp_diagnostics` or pyright CLI on `packages/my-agent-core/src/my_agent_core/events.py` and `loop.py` to ensure 0 errors.

- [ ] **Step 5: Commit full verification**

```bash
git commit -am "test(core): 全量 378 项离线测试与类型检查通过，验证 Pi 风格事件与拦截正交重构"
```

---

## Self-Review Checklist

1. **Spec coverage**:
   - `events.py` read-only events + 5 decision points: Covered in Task 1.
   - `_stream_llm`, `_assistant_turn`, `_execute_tools_turn`, `_synthesize_interrupted_tool_calls`: Covered in Task 2.
   - 110-line `run_agent_loop` state machine with `max_turns`, `pending_messages`, paired `TurnEnd`: Covered in Task 3.
   - `ExtensionAPI.on` intelligent routing: Covered in Task 4.
   - No-compromise test rewriting: Addressed in Tasks 1, 3, 4, 5.
2. **Placeholder scan**: No "TODO", "TBD", or vague placeholders. All steps have concrete code blocks and commands.
3. **Type consistency**: Verified `ToolCallHook`, `ToolResultHook`, `BeforeModelCallHook`, `UserInputHook`, `AgentStartHook`, `HookResult`, `HookRegistry` match across all tasks.
