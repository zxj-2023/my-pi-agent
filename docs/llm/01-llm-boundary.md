# 模型边界层设计规范 (`my-agent-llm`)

- **定位**：独立轻量 SDK 包 (`packages/my-agent-llm`)
- **核心类**：`LLM`, `Config`, `Message`, `Response`, `StreamChunk`, `ToolCall`, `TurnOutcome`
- **主要实现**：`client.py`, `models.py`, `config.py`, `providers/`

---

## 一、架构设计与定位

`my-agent-llm` 是整个 Agent 框架的底层模型边界层，承担以下四大核心职责：

1. **多供应商协议标准化**：抹平 OpenAI、DeepSeek、Anthropic 等不同模型 API 在消息结构、工具调用、思考过程上的方言差异；
2. **结构化 ToolCall 第一公民生产**：参数在模型边界层内直接反序列化为 Python 字典（`args: dict`），Anthropic 原生采用 `block.input`，**彻底消灭 4 重 JSON 编解码（4x JSON Ping-Pong）**；
3. **中立化终止状态机（`TurnOutcome`）**：对标 `pig-llm`，将各大厂商私有的退出原因统一映射为中立枚举；
4. **纯原生异步流式驱动与终态直接封装**：在流式生成末块直接交付组装完毕的 `Response` 实体，并提供 `to_message()` 一键转换，彻底消除上层调度微内核的手工拼装负担。

```text
               Agent 核心层 (my-agent-core)
                         │
                         ▼
        ┌──────────────────────────────────┐
        │            LLM 统一门面          │  (client.py)
        │  chat / stream / achat / achat_stream
        └────────────────┬─────────────────┘
                         │
         ┌───────────────┼───────────────┐
         ▼               ▼               ▼
   OpenAIProvider  DeepSeekProvider AnthropicProvider
   (基准协议翻译)  (提取推理思维链) (原生 dict Block 互转)
```

---

## 二、核心类与数据模型

### 1. 不可变配置：`Config`

```python
class Config(BaseModel):
    provider: Literal["openai", "deepseek", "anthropic"] = "openai"
    model: str = "gpt-4o"
    api_key: str | None = None
    base_url: str | None = None
    timeout: float = 60.0
    model_config = ConfigDict(frozen=True)  # 不可变保障
```

### 2. 统一结构化 `ToolCall` 实体（一等公民）

```python
class ToolCall(BaseModel):
    id: str
    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None

    def to_wire_dict(self) -> dict[str, Any]:
        """兼容 OpenAI wire 形状导出。"""
        ...
```

- **参数在模型层就地解析**：OpenAI/DeepSeek 的 Accumulator 在 `finish()` 时反序列化 JSON 字符串；Anthropic 直接使用 SDK 原生返回的 `block.input` 字典，避免冗余的 `json.dumps` ➔ `json.loads`；
- **Never-Throw 参数错误标记**：当大模型输出畸形非法的 JSON 时，模型层不抛异常，而是标记 `error=...`，由核心层转化为结构化错误反馈给大模型自我修正。

### 3. 中立化单轮终止原因：`TurnOutcome`

```python
class TurnOutcome(str, Enum):
    COMPLETED = "completed"        # 正常生成结束 ("stop", "end_turn")
    TOOL_CALLS = "tool_calls"      # 发起工具调用 ("tool_calls", "tool_use")
    LENGTH = "length"              # 达到最大 Token 长度限制
    CONTENT_FILTER = "content_filter" # 命中安全或合规审查
    ABORTED = "aborted"            # 用户主动中断取消
    PROVIDER_ERROR = "provider_error" # 服务商报错
    UNKNOWN = "unknown"
```

通过 `normalize_finish_reason(reason, has_tool_calls)` 函数将所有供应商方言归一化为上述枚举。

### 4. 统一响应与终态转换：`Response`

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

    def to_message(self, role="assistant", stop_reason=None) -> Message:
        """模型层将完整响应一键转为核心 Message，彻底消灭核心层拼装工人代码。"""
        ...
```

### 5. 流式增量切片：`StreamChunk`

```python
class StreamChunk(BaseModel):
    content: str
    finish_reason: str | None = None
    tool_calls: list[ToolCall] | None = None
    usage: dict[str, int] | None = None
    metadata: dict[str, Any] | None = None
    response: Response | None = None  # 末块直接携带终态 Response 实体
```

---

## 三、关键机制与技术实现

### 1. 流式终态直接封装（Terminal Response Assembly）

流式生成的最后一个 Chunk 会在内部组装好完整的 `response: Response` 实体并交付。核心层的 `_assistant_turn` 接收到末块后，无需手动遍历增量 Chunk 进行字符串累加，直接调用 `chunk.response.to_message()` 即可得到合法的 `AssistantMessage`。

### 2. DeepSeek 推理链支持（`reasoning_content`）

针对 DeepSeek R1 / V3 等带有显式推理过程的模型，`DeepSeekProvider` 继承自 `OpenAIProvider`，在解析响应时额外提取 `reasoning_content`，注入 `StreamChunk.metadata` 或 `Response.metadata`，支持终端界面独立展示思维过程。

### 3. Usage 强制锚定（Token Usage Anchoring）

无论是非流式还是流式模式，模型层的最后一个响应必须尽可能捕获并透传官方 API 返回的真实 `usage: {prompt_tokens, completion_tokens, total_tokens}`，为框架层的上下文压缩估算提供最权威的校准锚点。

---

## 四、异常处理与防御

- **Provider 参数透传隔离**：调用方传入的自定义 `kwargs`（如 `temperature`, `top_p`）只透传给对应 SDK，不污染基类配置；
- **离线 Fake 测试缝隙**：`LLM` 构造函数接收可选的 `client=` 参数，单测通过注入 Mock SDK 客户端实现 **100% 离线确定性测试**。
