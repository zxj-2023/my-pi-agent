# Pi 风格事件流与五大决策拦截点正交重塑设计规范 (Phase 19)

- **创建日期**：2026-09-09
- **作者**：Pi Agent 架构演进组
- **状态**：Draft（方案 A：子生成器分治 + 事件拦截正交化）
- **影响范围**：
  - `packages/my-agent-core/src/my_agent_core/events.py`（事件与决策点类型模型重构）
  - `packages/my-agent-core/src/my_agent_core/loop.py`（ReAct 微内核子生成器分治，550行 ➔ 100行）
  - `packages/my-agent-core/src/my_agent_core/extensions/core.py`（ExtensionAPI 智能分流与强类型绑定）
  - `packages/my-agent-core/src/my_agent_core/agent.py`（AgentHarness 门面装配与接口对接）
  - 全量离线单元测试套件（378 tests，保持 100% 离线通过）

---

## 一、背景与重构动机

在完成了阶段 17（转录本自愈）与阶段 18（Tau 会话存储 7 模块下沉）后，核心 ReAct 调度循环已被成功提炼为 `loop.py` 中的纯函数异步生成器 `run_agent_loop`。

然而，在对标顶级标杆 **Tau (`tau-ai`)** 与 **Pi (`@earendil-works/pi-coding-agent`)** 时，我们发现当前实现存在明显的结构性缺陷与认知摩擦：

1. **微内核单体膨胀（550+ 行大泥球）**：
   - 相比于 Tau 官方 `run_agent_loop` 仅 110 行的精练状态机，我们的微内核将模型多协议适配、参数解析、Hook 拦截、工具批处理并发、取消断头合成等逻辑全部平铺在同一个长函数中，缩进极深，难以阅读和单独测试；
2. **概念混淆：双通道事件发射（“精神分裂”）**：
   - 当前代码未能清晰划分“单向只读通知”与“双向决策门禁”；
   - 微内核中机械式充斥了整整 **30 处** `yield ev` 与 `if hook_registry is not None: await hook_registry.emit(ev)` 并列双重发射。其中 25 处（如 `TurnStart`, `TurnEnd`, `MessageStart`, `MessageEnd` 等）根本不关心 Hook 返回值，造成严重的视觉噪音；
3. **协议适配冗余（70+ 行重复样板代码）**：
   - 在流式大模型调用阶段，手写了 `if hasattr(llm, "achat_stream"): ... elif hasattr(llm, "achat"): ... else: ...` 三个分支，并在每个分支内部逐字重复累加 Token、构建 `MessageUpdate` 与捕获取消；
4. **断头中断合成逻辑重复手写**：
   - 在流式输出取消（lines 395-415）与工具执行前夕取消（lines 465-485）两处，存在两套完全重复的 20 行断头工具补齐与事件发射代码。

### 本次重塑的核心目标
1. **完全对齐 Tau 架构的子生成器分治法（Sub-Async-Generators）**：
   将 550 行的大泥球拆解为 **1 个主调度大管家（100 行）+ 2 个专职业务子生成器（模型车间 + 工具车间）**；
2. **完全对齐 Pi 架构的“正交解耦”哲学**：
   - **纯只读事件（AgentEvent）**：纯单向事实广播（Stream of Facts），微内核仅负责 `yield`，外部仅负责 `async for`，无返回值；
   - **五大决策拦截点（DecisionPoint）**：专职控制流门禁（Control Gates），仅在 5 个固定命脉卡口由微内核显式调用，具备一票否决权（`block=True`）与参数/上下文改写权；
3. **ExtensionAPI 智能分流与纯 Python 强类型**：
   对外暴露强类型 `api.on(Target, handler)`，内部自动路由至“只读广播队列”或“洋葱拦截流水线”；
4. **保证 100% 零回归**：
   全工作区 378 项离线测试无条件 100% 秒级全绿。

---

## 二、系统总体架构对比

### 1. 当前有缺陷的架构（概念混淆与双通道大泥球）

```text
 ┌─────────────────────────────────────────────────────────────┐
 │ run_agent_loop (550+ 行超大函数)                            │
 │                                                             │
 │   • 混杂 30 处: yield ev + await hook_registry.emit(ev)     │
 │   • 内联 70 行 LLM 三分支适配 (achat_stream/achat/chat)     │
 │   • 内联 140 行工具解析、执行与 Hook 改写                  │
 │   • 内联 2 处重复的断头中断补齐逻辑                         │
 └──────────────────────────────┬──────────────────────────────┘
                                │ 混淆
                                ▼
       Event (兼具通知数据与 HookResult 拦截标记的混合体)
```

### 2. 重构后的理想架构（子生成器分治 + 正交双轨体系）

```text
 ┌─────────────────────────────────────────────────────────────┐
 │ 【主微内核总指挥】 run_agent_loop (约 100 行纯粹状态机)      │
 │                                                             │
 │ while True: (外层 Follow-up 宏观接力)                       │
 │   while has_more_tools or pending: (内层 ReAct 微观迭代)    │
 │     yield TurnStart(iteration)                              │
 │                                                             │
 │     # 1. 决策点 3 审查: on_before_model_call(view)          │
 │     # 2. 委托模型车间: async for ev in _assistant_turn(...)  │
 │     # 3. 委托工具车间: async for ev in _execute_tools_turn(...)│
 │     # 4. 轮次闭环: yield TurnEnd(...)                       │
 │     # 5. 收割 steer 即时转向                                │
 │   # 6. 收割 follow_up 追问                                  │
 │ yield AgentEnd(...)                                         │
 └──────────────┬───────────────────────────────┬──────────────┘
                │ 委托子生成器                  │ 委托子生成器
                ▼                               ▼
 ┌──────────────────────────────┐ ┌────────────────────────────┐
 │ 车间 ①: _assistant_turn      │ │ 车间 ②: _execute_tools_turn│
 │ (~60 行专职异步生成器)       │ │ (~80 行专职异步生成器)     │
 │ • 归一化 LLM 异步流式适配    │ │ • 校验工具入参 JSON 语法   │
 │ • 逐字 yield MessageUpdate   │ │ • 决策点 4: on_tool_call   │
 │ • 监听并处理流式中途取消     │ │ • 并发批量执行工具         │
 │ • 最终产出 AssistantMessage  │ │ • 决策点 5: on_tool_result │
 │                              │ │ • 逐个 yield 工具结果与事件│
 └──────────────────────────────┘ └────────────────────────────┘
                ▲                               ▲
                │ 仅在 5 处命脉卡口检查          │
 ┌──────────────┴───────────────────────────────┴──────────────┐
 │ 【五大决策拦截点 (Decision Points)】                        │
 │ 1. UserInput (input)                                        │
 │ 2. AgentStart (before_agent_start)                          │
 │ 3. BeforeModelCall (context)                                │
 │ 4. ToolCall (tool_call)                                     │
 │ 5. ToolResult (tool_result)                                 │
 └─────────────────────────────────────────────────────────────┘
```

---

## 三、模块详细设计规格

### 1. `events.py`：事件体系与决策点正交解耦

#### (1) 纯只读事件流（`Event`）
所有的生命周期通知实体**彻底剔除 `Interceptable` 标记与返回值期待**。微内核仅负责 `yield`，外部仅负责消费：

```python
# packages/my-agent-core/src/my_agent_core/events.py

from dataclasses import dataclass, field
import time
from typing import Any
from my_agent_llm import Message, StreamChunk

@dataclass(frozen=True)
class Event:
    """生命周期事实事件基类（纯只读广播，不可变）。"""
    timestamp: float = field(default_factory=time.time)

@dataclass(frozen=True)
class AgentStart(Event):
    """Agent 全流程开始通知。"""
    system_prompt: str = ""
    user_input: str = ""

@dataclass(frozen=True)
class AgentEnd(Event):
    """Agent 全流程结束通知。"""
    messages: list[Message]
    final_text: str | None
    iterations: int
    stop_reason: str  # "end_turn" | "max_iterations" | "cancelled" | "blocked"

@dataclass(frozen=True)
class TurnStart(Event):
    """单轮推理迭代开始通知。"""
    iteration: int

@dataclass(frozen=True)
class TurnEnd(Event):
    """单轮推理迭代结束通知（严格保证成对闭合）。"""
    message: Message | None = None
    tool_results: list[Message] = field(default_factory=list)

@dataclass(frozen=True)
class MessageStart(Event):
    """消息加入对话流通知。"""
    message: Message

@dataclass(frozen=True)
class MessageUpdate(Event):
    """流式 Token 增量更新通知（打字机专用）。"""
    message: Message
    chunk: StreamChunk | None = None

@dataclass(frozen=True)
class MessageEnd(Event):
    """消息完整落地通知。"""
    message: Message

@dataclass(frozen=True)
class ToolExecutionStart(Event):
    """工具开始执行通知。"""
    tool_call_id: str
    tool_name: str
    args: dict[str, Any]

@dataclass(frozen=True)
class ToolExecutionUpdate(Event):
    """工具流式进度更新通知。"""
    tool_call_id: str
    tool_name: str
    args: dict[str, Any]
    partial_result: Any

@dataclass(frozen=True)
class ToolExecutionEnd(Event):
    """工具执行完毕通知。"""
    tool_call_id: str
    tool_name: str
    result: str
    is_error: bool

@dataclass(frozen=True)
class ContextCompacted(Event):
    """上下文压缩事件通知。"""
    tokens_before: int
    tokens_after: int
    summarized_count: int

AgentEvent = Event
```

#### (2) 专职决策拦截点契约（`DecisionPoint` 与 `HookResult`）
与 Pi 官方 5 大决策点 100% 严密对齐：

```python
@dataclass(frozen=True)
class HookResult:
    """决策拦截点的统一干预结果。"""
    block: bool = False
    reason: str | None = None
    updated_input: str | None = None
    updated_system_prompt: str | None = None
    updated_messages: list[Message] | None = None
    updated_args: dict[str, Any] | None = None
    updated_result: str | None = None

# 五大类型化决策点（用于强类型静态注册）：
class UserInputDecision:
    """决策点 1 (input): 拦截或改写用户原始输入文本。"""

class AgentStartDecision:
    """决策点 2 (before_agent_start): 拦截启动或动态重写 system_prompt。"""

class BeforeModelCallDecision:
    """决策点 3 (context): 调模型前 1ms 审查或临时改写发送视图。"""

class ToolCallDecision:
    """决策点 4 (tool_call): 工具执行前安全审批、阻断高危命令或改写入参。"""

class ToolResultDecision:
    """决策点 5 (tool_result): 工具执行后改写返回内容或篡改报错状态。"""
```

#### (3) 决策分发管理器（`DecisionRegistry` / 链式中间件）
提供专职的洋葱中间件流水线：
- 支持多插件链式按序处理改写值；
- 遇到 `block=True` 时立即短路阻断；
- 与只读事件广播彻底分离。

---

### 2. `loop.py`：微内核子生成器分治重塑

#### (1) 统一底层流式适配器（`_stream_llm`）
消除原本 70 行的 3 分支重复代码，将所有 LLM 调用归一化为单一的异步生成器：

```python
async def _stream_llm(
    llm: Any,
    messages: list[Message],
    tool_schemas: list[dict[str, Any]],
    model: str | None = None,
) -> AsyncIterator[StreamChunk]:
    """将各类 LLM 门面 (achat_stream / achat / chat) 统一归一化为标准的异步流式 Chunk 生成器。"""
    if hasattr(llm, "achat_stream"):
        async for chunk in llm.achat_stream(messages=messages, tools=tool_schemas, model=model):
            yield chunk
    elif hasattr(llm, "achat"):
        resp = await llm.achat(messages=messages, tools=tool_schemas, model=model)
        yield StreamChunk(content=resp.content or "", tool_calls=resp.tool_calls, usage=resp.usage)
    else:
        # 同步回退：在线程池执行避免事件循环阻塞
        resp = await asyncio.to_thread(llm.chat, messages=messages, tools=tool_schemas, model=model)
        yield StreamChunk(content=resp.content or "", tool_calls=resp.tool_calls, usage=resp.usage)
```

#### (2) 子生成器 1：大模型流式推理车间（`_assistant_turn`）
专注处理 Token 打字机累加、取消信号感知与断头自愈：

```python
async def _assistant_turn(
    *,
    llm: Any,
    view: list[Message],
    tool_schemas: list[dict[str, Any]],
    model: str | None,
    signal: CancellationToken | None,
    context_manager: Any | None,
) -> AsyncIterator[AgentEvent]:
    """专职大模型推理车间：逐字 yield MessageUpdate，产出并在末尾 yield MessageEnd(assistant)。"""
    content_acc = ""
    final_tool_calls: list[dict[str, Any]] | None = None
    last_usage: dict[str, Any] | None = None
    cancelled = False

    try:
        async for chunk in _stream_llm(llm, view, tool_schemas, model):
            if chunk.content:
                content_acc += chunk.content
            if chunk.tool_calls:
                final_tool_calls = chunk.tool_calls
            if chunk.usage:
                last_usage = chunk.usage

            update_ev = MessageUpdate(
                message=Message(role="assistant", content=content_acc),
                chunk=chunk,
            )
            yield update_ev

            if signal is not None and signal.is_cancelled():
                cancelled = True
                break
    except Exception as exc:
        # 异常捕获转为错误 Assistant 消息，Never-Throw
        content_acc = f"(Error during model stream: {exc})"
        cancelled = True

    if last_usage and context_manager and hasattr(context_manager, "record_usage"):
        context_manager.record_usage(last_usage)

    assistant = Message(
        role="assistant",
        content=content_acc,
        metadata={
            **({"tool_calls": final_tool_calls} if final_tool_calls else {}),
            **({"stop_reason": "cancelled"} if cancelled else {}),
        } or None,
    )
    yield MessageStart(assistant)
    yield MessageEnd(assistant)
```

#### (3) 子生成器 2：工具并发执行车间（`_execute_tools_turn`）
专注处理参数反序列化、`tool_call` 拦截审批、并发执行与 `tool_result` 改写：

```python
async def _execute_tools_turn(
    *,
    tool_calls: list[dict[str, Any]],
    registry: ToolRegistry,
    before_tool_call: Callable[[str, str, dict[str, Any]], Awaitable[tuple[bool, str | None, dict[str, Any]]]] | None,
    after_tool_call: Callable[[str, str, str, bool], Awaitable[tuple[str, bool]]] | None,
    signal: CancellationToken | None,
) -> AsyncIterator[AgentEvent]:
    """专职工具执行车间：处理审批、参数改写、并发调度、结果改写并逐一发射事件。"""
    # 1. 参数解析与 before_tool_call 审批
    # 2. 调用 registry.execute_batch 并行执行
    # 3. 触发 after_tool_call 改写
    # 4. 逐个发射 ToolExecutionStart -> ToolExecutionEnd -> MessageStart/End(tool)
    ...
```

#### (4) 集中化断头合成辅助函数
```python
def _synthesize_interrupted_tool_calls(tool_calls: Sequence[dict[str, Any]]) -> list[Message]:
    """统一生成标准的中断工具结果，彻底消除多处代码重复。"""
    return [
        Message(
            role="tool",
            content=_INTERRUPTED_TOOL_RESULT,
            metadata={"tool_call_id": tc["id"], "is_error": True},
        )
        for tc in tool_calls
    ]
```

#### (5) 瘦身后的主微内核 `run_agent_loop`（精简至约 100 行）
主函数完全回归纯粹的状态机调度：
```python
async def run_agent_loop(...) -> AsyncIterator[AgentEvent]:
    # 1. 初始 prompts 注入与前置事件
    yield AgentStart(system_prompt=system, user_input=user_input)

    # 2. 外层宏观任务循环
    while True:
        has_more_tools = True
        # 3. 内层微观 ReAct 循环
        while has_more_tools or pending_messages:
            iteration += 1
            yield TurnStart(iteration)

            # 前置清洗与上下文准备
            clean_messages = _provider_context(messages)
            view = await context_manager.prepare(clean_messages) if context_manager else clean_messages

            # 决策点 3: context 拦截
            if on_before_model_call:
                ctx_hook = await on_before_model_call(view, iteration)
                if ctx_hook.block:
                    # 严密闭合 TurnEnd 并退出
                    yield TurnEnd(message=None, tool_results=[])
                    yield AgentEnd(messages=list(messages), final_text=f"(blocked)", iterations=iteration, stop_reason="blocked")
                    return
                if ctx_hook.updated_messages:
                    view = ctx_hook.updated_messages

            # 委托模型车间
            assistant = None
            async for ev in _assistant_turn(...):
                yield ev
                if isinstance(ev, MessageEnd):
                    assistant = ev.message

            messages.append(assistant)

            # 取消或异常退出检查
            if assistant.metadata and assistant.metadata.get("stop_reason") == "cancelled":
                synth_tools = _synthesize_interrupted_tool_calls(assistant.metadata.get("tool_calls", []))
                for s in synth_tools:
                    messages.append(s)
                    yield MessageStart(s); yield MessageEnd(s)
                yield TurnEnd(message=assistant, tool_results=synth_tools)
                yield AgentEnd(messages=list(messages), final_text=None, iterations=iteration, stop_reason="cancelled")
                return

            # 委托工具车间
            tool_results = []
            calls = assistant.metadata.get("tool_calls") if assistant.metadata else None
            if calls:
                async for ev in _execute_tools_turn(...):
                    yield ev
                    if isinstance(ev, MessageEnd) and ev.message.role == "tool":
                        tool_results.append(ev.message)
                        messages.append(ev.message)
                has_more_tools = True
            else:
                has_more_tools = False

            # 本轮严密闭合
            yield TurnEnd(message=assistant, tool_results=tool_results)

            # 收割即时转向
            if get_steering_messages:
                pending_messages = list(get_steering_messages())

        # 收割宏观追问任务
        if get_follow_up_messages:
            followups = list(get_follow_up_messages())
            if followups:
                pending_messages = followups
                continue
        break

    yield AgentEnd(messages=list(messages), final_text=final_text, iterations=iteration, stop_reason="end_turn")
```

---

### 3. `extensions/core.py`：强类型事件绑定与智能分流

在 `ExtensionAPI` 内部实现分流逻辑：

```python
class ExtensionAPI:
    def on(self, target: type[Any], handler: Callable[..., Any]) -> None:
        """纯 Python 强类型注册接口。
        
        - 若 target 是只读事实事件类 (如 TurnStart, MessageUpdate): 注册进只读观察者队列 (单向推送，忽略返回值)；
        - 若 target 是五大决策点类 (如 ToolCallDecision, BeforeModelCallDecision): 注册进决策拦截中间件流水线 (返回值严格控制流程)。
        """
        if issubclass(target, Event):
            self.agent.subscribe_event(target, handler)
        else:
            self.agent.register_decision(target, handler)
```

---

## 四、单元测试与兼容性迁移验证策略

重构过程严格执行 TDD 规范与回归保护：

1. **现有单测 100% 兼容**：
   - 保持 `TurnStart`, `TurnEnd`, `MessageUpdate`, `ToolExecutionEnd`, `HookResult` 等类的属性与构造签名完全兼容；
   - 确保 `tests/test_agent_loop_pure.py`（11 项微内核单测）、`tests/test_agent_steering.py`（5 项转向单测）、`tests/test_agent.py`（25 项单测）零改动或仅适配正交类型通过；
2. **新增测试用例**：
   - 为子生成器 `_assistant_turn` 增加独立的流式解析与异常捕获单测；
   - 为子生成器 `_execute_tools_turn` 增加独立的参数拦截与并发执行单测；
   - 编写专门的“事件成对性严格校验用例”（断言任何退出路径下，已开轮次必须收到配对的 `TurnEnd`）。

---

## 五、规范自审清单 (Self-Review Checklist)

- [x] **无占位符与模糊表述**：所有接口、签名、字段类型全部明确（无 TODO、TBD）；
- [x] **无内部循环依赖**：`events.py` 位于底层，`loop.py` 仅单向依赖 `events.py` 与 `tool_history.py`；
- [x] **严格遵守 Never-Throw 保证**：模型调用异常、工具执行异常、Hook 异常全部受控转为错误消息，不向上抛出未受检异常；
- [x] **事件成对性与断头保护 100% 覆盖**：不管是正常完成、最大轮次限制、安全门禁阻断还是用户按 Ctrl+C 中途取消，所有生命周期事件严格成对闭合，断头工具调用自动补齐。
