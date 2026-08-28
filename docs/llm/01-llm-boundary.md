# 模型边界层设计规范 (`my-agent-llm`)

- **定位**：独立 SDK 包 (`packages/my-agent-llm`)
- **核心类**：`LLM`, `Config`, `Message`, `Response`, `StreamChunk`
- **主要实现**：`client.py`, `models.py`, `config.py`, `providers/`

---

## 一、架构设计与定位

`my-agent-llm` 是整个 Agent 框架的底层模型边界层，承担以下三大职责：

1. **多供应商协议标准化**：抹平 OpenAI、DeepSeek、Anthropic 等不同模型 API 在消息结构、工具调用、思考过程上的语法差异；
2. **纯原生异步流式驱动**：提供统一的 `chat`、`stream`、`achat`、`achat_stream` 四组接口；
3. **流式 Tool Calls 增量拼接**：在模型层内部自动聚合流式分片返回的工具参数，向上层输出完整可执行的 `tool_calls`。

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
   (基准协议翻译)  (提取推理思维链) (Block 双向翻译)
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

### 2. 统一消息与响应数据结构

- **`Message(role, content, metadata)`**：通用消息载体，`role` 支持 `system`、`user`、`assistant`、`tool`；
- **`Response(content, model, usage, tool_calls, finish_reason)`**：非流式统一响应对象；
- **`StreamChunk(content, tool_calls, usage, finish_reason)`**：流式增量切片，支持逐字打字机渲染。

---

## 三、关键机制与技术实现

### 1. 流式 Tool Calls 增量拼接（Incremental Tool Call Assembly）

不同大模型在流式输出工具调用时，通常把参数拆分成多个微小 Chunk（例如第 1 个 chunk 给 `index=0, name="read"`, 后续 chunks 给 `arguments` 片段）。
`OpenAIProvider` 与 `DeepSeekProvider` 内部维护局部累加器，在流式生成中逐 chunk 拼接参数，并在末块组装出完整的 `tool_calls` 列表。

### 2. DeepSeek 推理链支持（`reasoning_content`）

针对 DeepSeek R1 / V3 等带有显式推理过程的模型，`DeepSeekProvider` 继承自 `OpenAIProvider`，在解析响应时额外提取 `reasoning_content`，注入 `StreamChunk.metadata` 或 `Response.metadata`。

### 3. Usage 强制锚定（Token Usage Anchoring）

无论是非流式还是流式模式，模型层的最后一个响应必须尽可能捕获并透传官方 API 返回的真实 `usage: {prompt_tokens, completion_tokens, total_tokens}`，为框架层的上下文压缩估算提供最权威的校准锚点。

---

## 四、异常处理与防御

- **Provider 参数透传隔离**：调用方传入的自定义 `kwargs`（如 `temperature`, `top_p`）只透传给对应 SDK，不污染基类配置；
- **离线 Fake 测试缝隙**：`LLM` 构造函数接收可选的 `client=` 参数，单测通过注入 Mock SDK 客户端实现 **100% 离线确定性测试**。
