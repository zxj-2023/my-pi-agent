# my-agent-llm

提供模型中立（Provider-Neutral）的统一大语言模型边界层。负责抹平不同模型供应商（OpenAI、DeepSeek、Anthropic 等）的 API 协议与消息格式差异，对外暴露纯净、统一的 LLM 门面。

---

## 核心职责

1. **统一模型门面**：提供统一的 `LLM` 门面类，同时支持同步与异步调用（`chat`、`stream`、`achat`、`achat_stream`）。
2. **多 Provider 标准化适配**：将统一的 `Message` 与 `Tool` 格式转换为各 Provider 专有格式（OpenAI、DeepSeek、Anthropic Messages API），并将原始流式响应标准化为统一的 `StreamChunk`。
3. **流式 Tool Calls 增量聚合**：在流式生成过程中自动累加与拼接多工具调用的 `name` 与 `arguments` JSON 片段。
4. **Token Usage 捕获与锚定**：精准捕获 Provider 返回的真实 `usage` 数据（包括流式末块），为上层上下文预算与压缩管理提供真实的锚定基准。

---

## 模块结构

```text
packages/my-agent-llm/
├── pyproject.toml            # 包名 my-agent-llm，src 布局 + hatchling 构建
├── src/my_agent_llm/
│   ├── client.py             # LLM 门面与统一调用入口
│   ├── config.py             # Config 配置模型（不可变 Pydantic 模型）
│   ├── models.py             # 统一数据模型（Message, Response, StreamChunk, ToolCall 等）
│   └── providers/            # Provider 适配实现与注册表
│       ├── base.py           # Provider 抽象基类
│       ├── registry.py       # PROVIDER_REGISTRY 供应商注册表
│       ├── openai.py         # OpenAIProvider 适配器
│       ├── deepseek.py       # DeepSeekProvider 适配器（含 reasoning_content 处理）
│       └── anthropic.py      # AnthropicProvider 适配器（含 system 消息分离与 XML 兼容）
└── tests/                    # 100% 离线单元测试（36 passed）
```

---

## 安装与测试

```powershell
cd packages/my-agent-llm
uv sync
uv run python -m pytest -q
# 输出: 36 passed in ~4s
```
