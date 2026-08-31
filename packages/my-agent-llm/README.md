# my-agent-llm

`my-pi-agent` 的模型边界层（独立 uv 项目，Python 包名 `my_agent_llm`）。

定位为**供应商中立的模型调用适配层**，负责将各主流大模型 API（OpenAI、DeepSeek、Anthropic）统一抽象为标准的数据模型与调用接口，屏蔽 SDK 差异，处理流式 Tool Calls 增量拼装与 Token Usage 锚定。

---

## 核心特性

- **统一 `LLM` 门面**：
  - 提供 `chat` / `stream` / `achat` / `achat_stream` 四组统一接口；
  - 自动根据 `provider` 参数路由到底层适配器，外部代码只需面向一套标准 API 编程。
- **三大主流 Provider 原生适配**：
  - **`openai`**：标准 Function Calling 与 Chat Completions 协议基准；
  - **`deepseek`**：继承自 OpenAI Provider，原生支持 `reasoning_content` 思考链提取；
  - **`anthropic`**：Claude 专属 Content Block 双向翻译（文本/工具调用/工具结果），自动过滤 `web_search` 等原生块。
- **流式 Tool Calls 增量拼装与 Usage 锚定**：
  - 在流式迭代（`achat_stream`）中自动聚合碎片化的 `tool_calls` 参数片段；
  - 严格保证最后一个 `StreamChunk` 或 `Response` 携带完整的 `usage` 统计（`input_tokens`, `output_tokens`），为上层 Context 压缩提供精确的锚定基准。
- **不可变配置与强类型数据模型**：
  - `Config`（Pydantic `frozen=True`）：配置集中校验，包含 `provider`, `model`, `api_key`, `base_url`, `temperature`, `max_tokens`, `timeout` 等；
  - `Message`、`Response`、`StreamChunk` 强类型定义。
- **100% 离线确定性单测设计**：
  - 底层 Provider 构造时支持注入假客户端（`client=`），所有 36 项单测不依赖外网与真实 API Key。

---

## 快速上手

### 1. 安装与配置

```powershell
cd packages/my-agent-llm
uv sync
Copy-Item .env.example .env    # 填入 API 密钥（测试无需配置）
```

### 2. 代码示例

```python
import asyncio
from my_agent_llm import LLM, Config, Message

async def main():
    # 1. 声明配置（支持 openai, deepseek, anthropic）
    config = Config(
        provider="deepseek",
        model="deepseek-chat",
        api_key="your-api-key",
    )
    
    llm = LLM(config=config)
    
    # 2. 原生异步流式调用
    messages = [
        Message(role="user", content="请用一句话介绍 Python 异步编程。")
    ]
    
    print("AI 回答: ", end="", flush=True)
    async for chunk in llm.achat_stream(messages):
        if chunk.content:
            print(chunk.content, end="", flush=True)
        if chunk.reasoning_content:
            print(f"\n[思考]: {chunk.reasoning_content}")
    print()

if __name__ == "__main__":
    asyncio.run(main())
```

---

## 运行离线测试套件

```powershell
uv run python -m pytest -q
# 输出: 36 passed in ~8s
```
