# 模型边界层与工具调用结构化重塑设计规范 (Phase 20)

- **创建日期**：2026-09-10
- **作者**：Pi Agent 架构演进组
- **状态**：Draft for Review
- **对标项目**：
  - **Tau (`tau-ai`)**：`tau_ai/stream.py`, `tau_agent/messages.py`, `tau_ai/provider.py`
  - **`pig-llm` (`pig-mono`)**：`pig_llm/models.py`, `pig_llm/client.py`, `pig_llm/providers/`
  - **Pi (`@earendil-works/pi-coding-agent`)**：`@earendil-works/pi-ai`
- **影响范围**：
  - `packages/my-agent-llm`（模型边界层：统一结构化 ToolCall、TurnOutcome 状态中立化、异常翻译）
  - `packages/my-agent-core`（核心框架层：消除 4 重 JSON 编解码死循环，彻底净化 OpenAI Wire 协议泄漏）

---

## 一、现状审查与核心缺陷诊断

在完成了阶段 19（事件流与 Hook 拦截正交重塑）之后，我们深入审查了 `my-agent-core` 与 `my-agent-llm` 的职责划分，发现当前实现存在严重的**“分层职责倒置与协议协议泄漏”**：

### 1. 【核心痛点一】四重 JSON 序列化翻转（The 4x JSON Ping-Pong）

当前工具调用的参数反序列化流向存在极其荒谬的“套娃”操作：

```text
Anthropic 官方 SDK (原生输出已经是 Python dict: block.input)
        │
        ▼ ① 强行转字符串 (my-agent-llm/providers/anthropic.py:50)
json.dumps(block.input) ──► 变成 JSON 字符串
        │
        ▼ ② 核心层被迫解析 (my-agent-core/loop.py:255)
json.loads(raw_args) ──► 变回 Python dict (为了给 ToolCallHook 和 ToolExecutionStart 传参)
        │
        ▼ ③ 核心层为了调用 batch 又拼回字符串 (my-agent-core/loop.py:310)
json.dumps(args) ──► 又变成 JSON 字符串
        │
        ▼ ④ 注册表内部又解析了一遍 (my-agent-core/registry.py:45)
json.loads(raw_args) ──► 又变回 Python dict 最终传给工具函数执行！
```

- **问题本质**：
  整整经历了 **4 次 `json.dumps` 和 `json.loads` 的往返折腾**！
  根因在于：`my-agent-llm` 没有向外交付结构化数据，而是把 OpenAI 传输层特有的底层格式（`{"function": {"arguments": "{\"...\"}"}}` 裸字符串）当成了内部通用模型，把本属于模型层的 JSON 反序列化脏活直接泄露给了核心调度层。

---

### 2. 【核心痛点二】OpenAI 传输层私有协议直接裸奔在核心层

在 `loop.py`、`tool_history.py`、`registry.py` 中，四处充斥着：

```python
func = tc.get("function") or {}
name = func.get("name", "")
raw_args = func.get("arguments", "{}")
```

- **问题本质**：
  `tc["function"]["name"]` 和 `tc["function"]["arguments"]` 纯粹是 **OpenAI API 的网络私有传输格式（Wire Format）**！
  对于一个通用 Agent 框架而言，核心调度微内核（Microkernel）只应该认识通用的结构化对象：
  - `tool_call.id`
  - `tool_call.name`
  - `tool_call.args`（已反序列化完成的类型安全字典）

---

### 3. 【核心痛点三】厂商私有 `finish_reason` 缺乏中立化归一

- **问题本质**：
  - OpenAI 返回 `"stop"`，Anthropic 返回 `"end_turn"`，DeepSeek 返回 `"stop"`，Google 返回 `"STOP"`；
  - 工具调用时，OpenAI 返回 `"tool_calls"`，Anthropic 返回 `"tool_use"`；
  - 长度超限时，OpenAI 返回 `"length"`，Anthropic 返回 `"max_tokens"`。
  当前 `my-agent-llm` 仅仅是将厂商的原生字符串原封不动透传给 `Response.finish_reason`，导致核心层、状态机与外部 UI 逻辑必须硬编码兼容各大厂商的私有方言。

---

## 二、业界标杆（Tau 与 `pig-llm`）技术实现对标

### 1. Tau (`tau-ai` & `tau_agent`) 的解法：模型层交付结构化实体

在 Tau 架构中（`tau_agent/messages.py:115`）：

```python
class ToolCall(WireModel):
    """A tool call content block requested by the assistant."""
    type: Literal["toolCall"] = "toolCall"
    id: str
    name: str
    arguments: dict[str, JSONValue] = Field(default_factory=dict)
```

- **关键设计**：
  Tau 的模型层在将流式分块组装完毕后，**自动在模型层内部完成参数的 `json.loads` 解析**！
  交付给核心微内核 `loop.py` 的 `call: ToolCall`，其 `call.arguments` 直接就是标准的 Python 字典。
- **微内核收益**：
  微内核在广播 `ToolExecutionStart`、执行 `before_tool_call` 审批以及派发工具执行时，**全程零 JSON 字符串解析，直接读取字典**！

---

### 2. `pig-llm` (`pig-mono`) 的解法：中立化终止状态机（`TurnOutcome`）

在 `pig-llm` 中（`pig_llm/models.py:9-60`）：

```python
class TurnOutcome(str, Enum):
    """Provider-neutral reason why an LLM turn stopped producing work."""
    COMPLETED = "completed"
    TOOL_CALLS = "tool_calls"
    LENGTH = "length"
    CONTENT_FILTER = "content_filter"
    ABORTED = "aborted"
    PROVIDER_ERROR = "provider_error"
    INCOMPLETE = "incomplete"
    UNKNOWN = "unknown"
```

- **关键设计**：
  定义标准状态枚举，并通过 `normalize_finish_reason` 函数将所有第三方厂商的私有退出码统一映射为中立枚举。
- **调度层收益**：
  调度状态机与上层应用只需要判断 `if response.outcome == TurnOutcome.TOOL_CALLS`，彻底摆脱对厂商私有字符串的比对。

---

## 三、Phase 20 重构设计规格

### 1. `packages/my-agent-llm/src/my_agent_llm/models.py` 升级

#### (1) 结构化 `ToolCall` 实体（一等公民）

```python
class ToolCall(BaseModel):
    """统一结构化工具调用对象（对标 Tau / Pi）。
    
    参数在模型层完成反序列化，核心层直接消费字典，彻底告别四重 JSON 编解码。
    """
    id: str
    name: str
    args: dict[str, Any] = Field(default_factory=dict)
```

#### (2) 中立化终止原因枚举（`TurnOutcome`）

```python
class TurnOutcome(str, Enum):
    """Provider 中立的单轮终止原因。"""
    COMPLETED = "completed"      # 正常结束 ("stop", "end_turn")
    TOOL_CALLS = "tool_calls"    # 发起工具调用 ("tool_calls", "tool_use")
    LENGTH = "length"            # 长度超限 ("length", "max_tokens")
    CONTENT_FILTER = "content_filter" # 内容审查拦截
    ABORTED = "aborted"          # 用户主动中断
    ERROR = "error"              # 厂商报错
    UNKNOWN = "unknown"
```

#### (3) 完备的 `Response` 与 `StreamChunk`

```python
class Response(BaseModel):
    content: str
    model: str
    tool_calls: list[ToolCall] | None = None
    reasoning_content: str | None = None
    usage: dict[str, int] | None = None
    finish_reason: str | None = None

    @property
    def outcome(self) -> TurnOutcome:
        return normalize_finish_reason(self.finish_reason, bool(self.tool_calls))

    def to_message(self, role: str = "assistant", stop_reason: str | None = None) -> Message:
        """模型层将完整响应一键转为核心 Message，彻底消灭核心层拼装工人代码。"""
        meta: dict[str, Any] = {}
        if self.tool_calls:
            meta["tool_calls"] = [tc.model_dump() for tc in self.tool_calls]
        if self.usage:
            meta["usage"] = self.usage
        if self.reasoning_content:
            meta["reasoning_content"] = self.reasoning_content
        effective_stop = stop_reason or self.outcome.value
        if effective_stop:
            meta["stop_reason"] = effective_stop
        return Message(role=role, content=self.content, metadata=meta if meta else None)
```

---

### 2. `packages/my-agent-core/src/my_agent_core/loop.py` 瘦身

通过模型层的结构化交付，`_execute_tools_turn` 将实现断崖式精简：

```python
# 重构后的 _execute_tools_turn：直接消费已解析的 ToolCall 列表
async def _execute_tools_turn(
    *,
    tool_calls: Sequence[ToolCall],  # 结构化实体，参数已是 dict
    registry: ToolRegistry,
    before_tool_call: Callable[[ToolCallHook], ...],
    after_tool_call: Callable[[ToolResultHook], ...],
    signal: CancellationToken | None = None,
) -> AsyncIterator[Event]:
    # 阶段 A: Preflight 广播与审批
    for tc in tool_calls:
        # 直接使用 tc.id, tc.name, tc.args！0 行 json.loads 代码！
        yield ToolExecutionStart(tool_call_id=tc.id, tool_name=tc.name, args=tc.args)
        ...
```

---

## 四、自审与效益评估

1. **消除冗余开销**：消除每个 Tool Call 过程中的 4 次 JSON 序列化与反序列化，大幅降低高并发工具调用时的 CPU 损耗；
2. **消灭协议泄漏**：OpenAI 私有的 `tc["function"]["arguments"]` 彻底限制在 `my-agent-llm/providers/openai.py` 内部，核心框架代码对具体大模型厂商零感知；
3. **状态机判定干净统一**：通过 `TurnOutcome`，框架判定模型是否在调用工具由 `bool(calls)` 变为强类型 `outcome == TurnOutcome.TOOL_CALLS`，逻辑严密清晰。
