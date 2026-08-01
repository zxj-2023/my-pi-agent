# 设计文档：my_ReAct —— 从零实现最简 ReAct Agent

- **日期**：2026-07-31
- **状态**：已确认，待实现
- **位置**：`my_ReAct/`（本项目内的独立子目录）

## 1. 背景与目标

本项目（ReAct 学习项目）已完成两个框架示例（`langchain_react.py`、`langgraph_react.py`），
并通过 `docs/react-source-walkthrough.md` 逐行学习了 LangChain `create_agent` 的源码：
图的组装（第 4-8 章）、tool calling 的完整链路（第 12 章）。

**本次目标**：不依赖 langchain/langgraph，以最简形式亲手实现一个 ReAct agent，
把学到的机制变成自己写过的代码。这是一个**学习项目**，不是生产代码：
透明度和可理解性优先于通用性。

### 1.1 已确认的需求（澄清记录）

| 问题 | 决定 |
|---|---|
| "不依赖框架"的边界 | 允许使用 `openai` 官方 SDK（厂商 SDK，非 agent 框架）；HTTP/JSON 管道交给 SDK，循环、工具注册、schema 生成、消息状态全部手写 |
| 工具声明方式 | 使用 `@tool` 装饰器（自动生成 JSON schema）；**并且**要学习装饰器原理，写入 README |
| 演示工具集 | 2-3 个零外部依赖的小工具：`multiply`、`get_current_time`、`get_weather`（模拟数据） |
| 运行形态 | 单次演示脚本（`main.py` 跑固定问题，打印循环过程和最终答案） |
| 文件结构 | 方案 B：小模块拆分（tools.py / agent.py / main.py / README.md + tests） |

### 1.2 非目标（明确不做）

- 流式输出（streaming）
- 交互式 REPL / 多会话记忆 / checkpointer
- 异步（async）实现
- 装饰器支持参数默认值、`Optional`、嵌套类型（仅四种基本类型）
- 多 provider 适配（只面向 OpenAI 兼容 API）
- 并行工具调用优化（顺序执行即可；模型一轮发多个 tool_calls 时 for 循环逐个执行）

## 2. 架构

```
my_ReAct/
├── __init__.py          # 空文件，使 my_ReAct 成为包（供 tests import）
├── tools.py             # 上行翻译层：@tool 装饰器 + Tool 类型 + 调用分发（~70 行）
├── agent.py             # ReAct 循环：调 API → 解析 tool_calls → 执行 → 判退出（~80 行）
├── main.py              # demo 入口：加载 .env，跑 3 个问题，打印过程（~40 行）
└── README.md            # 学习笔记：装饰器原理 + 与 langchain 源码的映射
tests/
└── test_my_react.py     # 离线测试（假客户端，无需 API key）
```

与学过的 langchain 源码的角色对应：

| my_ReAct | 对应的 langchain/langgraph 源码 |
|---|---|
| `tools.py` 的 `@tool` + schema 生成 | `langchain_core/tools/convert.py` + `utils/function_calling.py:517`（`convert_to_openai_tool`） |
| `tools.py` 的 `call_tool` | `langgraph/prebuilt/tool_node.py:1014`（`_run_one`）及其错误转消息逻辑（`tool_node.py:1062`） |
| `agent.py` 的循环 | `langchain/agents/factory.py` 的 `model_node` + `model_to_tools` 条件边（退出条件 `factory.py:1867`） |
| 消息状态（dict 列表） | `AIMessage` / `ToolMessage` 类 —— 无框架时**wire format 本身就是状态**，不需要消息类 |
| `main.py` 的环境变量处理 | 项目现有 `build_model()` 的写法（`OPENAI_API_KEY` / `OPENAI_MODEL` / `OPENAI_BASE_URL`） |

### 2.1 关键设计决策

1. **消息状态 = OpenAI wire format 的普通 dict 列表**。不定义 Message 类。
   理由：LangChain 需要消息类是因为要适配几十个 provider；只面向 OpenAI 格式时，
   协议格式本身就是状态，显式 dict 让"线上到底传了什么"一目了然（第 12 章的核心领悟）。
2. **`client` 依赖注入**。`run_agent` 接收 `client` 参数，生产传 `openai.OpenAI(...)`，
   测试传假对象。这是全部循环逻辑可离线测试的前提。
3. **装饰器返回 `Tool` 对象**（携带 `func` 与 `schema`），工具列表显式传入 `run_agent`，
   不做全局注册表。显式优于隐式。
4. **助手消息显式构造 dict** 追加回 messages（`{"role": "assistant", "content": ...,
   "tool_calls": [...]}`），不用 SDK 的响应对象直接回填——保持状态的纯粹性。
   注意：携带 `tool_calls` 的助手消息**必须**追加（即使 content 为空），
   否则 OpenAI 会拒绝后续的 tool 消息（找不到对应的 tool_call_id）。

## 3. 组件接口

### 3.1 `tools.py`

```python
TYPE_MAP = {int: "integer", float: "number", str: "string", bool: "boolean"}
    # Python 类型标注 → JSON Schema 类型的映射表

@dataclass
class Tool:
    name: str          # ← 函数名 func.__name__
    description: str   # ← docstring func.__doc__
    parameters: dict   # ← 由 inspect.signature() + TYPE_MAP 生成的 JSON Schema
    func: Callable

def tool(func: Callable) -> Tool:
    """@tool 装饰器。
    - 遍历签名参数：每个参数必须有 TYPE_MAP 内的类型标注，否则装饰时抛 TypeError
    - 不支持默认值参数：发现默认值直接抛 TypeError（保持最简，明确失败）
    - 零参数合法：parameters == {"type": "object", "properties": {}, "required": []}
    - docstring 缺失时 description 为空串（`inspect.getdoc(func) or ""`）
    """

def schemas_for(tools: list[Tool]) -> list[dict]:
    """返回 API 的 tools 参数：
    [{"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}, ...]
    """

def call_tool(tool_call, tools_by_name: dict[str, Tool]) -> str:
    """执行单个 tool_call（SDK 的 ChatCompletionMessageToolCall 对象或等价 duck type）。
    步骤：
      1. 按 tool_call.function.name 查注册表；未命中 → 返回
         "Unknown tool 'X'. Available: a, b, c"
      2. json.loads(tool_call.function.arguments)；失败 → 返回
         "Invalid JSON arguments: ..."
      3. tool.func(**args)；任何异常 → 返回 f"Error executing tool 'X': {e}"
      4. 成功 → str(result)
    约定：永不抛异常，错误全部转成描述性字符串（模型的"擦屁股"机制）。
    """
```

### 3.2 `agent.py`

```python
def run_agent(
    question: str,
    *,
    tools: list[Tool],
    client: OpenAI,            # 依赖注入
    model: str,
    system_prompt: str | None = None,   # 无默认，对齐 create_agent
) -> str:
    """ReAct 主循环，返回模型的最终文本回答。

    伪代码（这就是全部逻辑）：
        messages = []
        if system_prompt is not None:      # 对齐 create_agent：无默认系统提示词
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": question})
        tools_by_name = {t.name: t for t in tools}
        schemas = schemas_for(tools)
        while True:                          # 无护栏，退出由模型判断
            resp = client.chat.completions.create(
                model=model, messages=messages, tools=schemas)
            msg = resp.choices[0].message
            assistant_msg = {"role": "assistant", "content": msg.content}
            if msg.tool_calls:
                assistant_msg["tool_calls"] = [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.function.name,
                                  "arguments": tc.function.arguments}}
                    for tc in msg.tool_calls
                ]
            messages.append(assistant_msg)
            if not msg.tool_calls:            # ← 经典退出条件（factory.py:1867）
                return msg.content
            for tc in msg.tool_calls:
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": call_tool(tc, tools_by_name),
                })
    """
```

每轮循环用 `print` 打印到 stdout：轮次号、模型决策（"调用工具 X(参数)" 或
"最终回答"）、工具返回内容。测试运行时由 pytest 的输出捕获机制自动收纳，
不会污染测试输出。

### 3.3 `main.py`

```python
QUESTIONS = [
    "Use the multiply tool to calculate 37 times 19.",
    "What time is it now?",
    "What's the weather like in Tokyo and Paris?",
]

# 工具定义（@tool 装饰）
multiply(a: int, b: int) -> int          # 同框架版，答案可对比（703）
get_current_time() -> str                # 零参数工具；返回当前时间字符串（本地时区）
get_weather(city: str) -> str            # 模拟数据，如 f"{city}: sunny, 22°C (simulated)"

def build_client() -> OpenAI:
    """复用项目约定：
    - OPENAI_API_KEY 缺失 → RuntimeError（沿用 build_model 的风格与措辞）
    - OPENAI_BASE_URL 可选（OpenAI 兼容端点）
    """

def main() -> None:
    # load_dotenv() → build_client() → 逐个问题 run_agent(...) → 打印最终答案
```

模型名取 `OPENAI_MODEL`（默认 `gpt-4.1-mini`），与项目现有示例一致。

## 4. 数据流

以"东京和巴黎天气"为例，`messages` 列表的演化：

```
轮次 0  messages = [
  {role: system,  "You are a helpful assistant..."},
  {role: user,    "What's the weather like in Tokyo and Paris?"},
]
        ↓ client.chat.completions.create(messages, tools=[3 个 schema])
        ★ 模型判断（发生在 OpenAI 服务器上）：需要工具，发起两个调用
        ↓ 返回：tool_calls=[get_weather(Tokyo), get_weather(Paris)]
轮次 1  messages += [
  {role: assistant, content: null, tool_calls: [...]},     ← 模型的"判断"落盘
  {role: tool, tool_call_id: call_1, "Tokyo: sunny, 22°C (simulated)"},
  {role: tool, tool_call_id: call_2, "Paris: cloudy, 17°C (simulated)"},
]
        ↓ 再次调 API
        ★ 模型判断：信息够了
        ↓ 返回：content="Tokyo is sunny 22°C; Paris is cloudy 17°C.", tool_calls=[]
轮次 2  tool_calls 为空 → 退出循环，返回 content
```

循环出口只有一个：**模型不再发起 tool_calls**。无无限循环护栏——create_agent
的等价机制是 langgraph 运行时的 `recursion_limit`（默认 10007，超限抛
`GraphRecursionError`），本项目经用户决定有意不保留。

值得在 demo 输出中观察的现象：模型也可能分多轮各调一次（调一个、看结果、再调另一个），
循环天然支持，无需额外代码——因为每轮都带上完整消息历史重新请求。

## 5. 错误处理

原则（与 ToolNode 一致）：**工具层错误转消息回给模型，循环/配置层错误直接抛**。

| 故障 | 位置 | 处理 |
|---|---|---|
| 工具函数抛异常（如参数类型错） | `call_tool` | 捕获 → 返回 `"Error executing tool 'X': {e}"` → 模型可自我纠正 |
| 模型生成的参数 JSON 非法 | `call_tool` | `json.loads` 失败 → 返回 `"Invalid JSON arguments: ..."` |
| 模型幻觉出不存在的工具名 | `call_tool` | 返回 `"Unknown tool 'X'. Available: a, b, c"` |
| 装饰器遇到不支持的类型标注/默认值 | `@tool` | 装饰时（import 阶段）抛 `TypeError`，明确失败 |
| `OPENAI_API_KEY` 缺失 | `build_client` | 启动时 `RuntimeError` + 明确提示 |

## 6. 测试与验收标准

### 6.1 离线测试（`tests/test_my_react.py`，无需 API key）

假客户端技巧：`run_agent` 的 `client` 是注入的，传一个按脚本返回响应的假对象。
agent.py 只访问 `resp.choices[0].message.content` 和 `.tool_calls[].id/.function.name/.function.arguments`，
用 `types.SimpleNamespace`（或 dataclass）duck-type 即可，不需要真实的 SDK 响应对象。

| # | 测试 | 验证点 |
|---|---|---|
| 1 | schema 生成 | `multiply` 的 schema 与期望 dict 完全相等；`get_current_time`（零参数）→ `properties: {}, required: []`；docstring → description |
| 2 | 直接回答路径 | 假模型返回纯 content → `run_agent` 返回该内容；且请求参数带上了 `tools` |
| 3 | 工具调用路径 | 假模型第一轮返回 `multiply(37,19)` 调用、第二轮返回 `"703"` → 函数返回 `"703"`；断言第二次请求的 messages 中存在 content 为 `"703"` 的 tool 消息（证明真实执行了函数） |
| 4 | 未知工具恢复 | 假模型调用 `"divide"` → 下一轮请求的 tool 消息包含可用工具清单；随后假模型给出最终回答 |
| 5 | 工具异常恢复 | 假模型用错误类型参数调 `multiply` → tool 消息含错误文本，循环不崩，最终正常返回 |

### 6.2 验收标准（步骤 → 验证方式）

```
实现 tools.py        → 测试 1 通过（schema 逐字段正确）
实现 agent.py        → 测试 2-5 通过（离线跑通全部分支）
实现 main.py         → uv run pytest -q 全绿（含既有测试不被破坏）
真实验证（需 .env）   → uv run python my_ReAct/main.py
                       问题 1 答案含 703；问题 2 答出当前时间；问题 3 答出两城市天气
学习笔记             → my_ReAct/README.md 含装饰器原理 + 链路映射表
```

### 6.3 依赖变更

- `uv add openai`（新增唯一依赖）
- `python-dotenv`、`pytest` 已存在，复用
- `pyproject.toml` 的 `[tool.pytest.ini_options] pythonpath = ["."]` 已配置，
  `import my_ReAct.tools` 在测试中直接可用

## 7. README 学习笔记结构（`my_ReAct/README.md`）

1. **怎么跑**：`uv run python my_ReAct/main.py`、`uv run pytest -q`、`.env` 变量说明
2. **Python 装饰器原理**：`@tool` 是 `multiply = tool(multiply)` 的语法糖；
   函数是一等对象；装饰器就是"接收函数、返回（包装后的）函数"的函数
3. **`@tool` 逐行拆解**：`__name__` → name、`__doc__` → description、
   `inspect.signature()` 遍历参数 + `TYPE_MAP` 翻译类型标注 → parameters schema；
   与第 12 章实验打印出的 JSON 逐字段对照
4. **映射表**：本项目每个文件/函数 ↔ 它替代的 langchain 源码位置
   （见第 2 节的对应表），并链接 `docs/react-source-walkthrough.md` 的对应章节

## 8. 风险与备注

- **模型行为不确定**：真实运行时模型可能不调工具直接心算 37×19（小概率）。
  system prompt 已要求使用工具；验收以离线测试为主、真实运行为辅。
- **OpenAI SDK 版本**：`chat.completions.create` 的接口在 openai>=1.0 稳定；
  `uv add openai` 让 uv 解析当前稳定版即可，不额外设上限。
- **项目尚未初始化 git**：本设计文档暂不提交版本库；是否 `git init` 由用户决定。

## 9. 修订记录

- 2026-07-31：对齐 `create_agent` 的哲学——`run_agent` 不再有默认系统提示词
  （`system_prompt` 默认 `None`，完全不发送 system 消息）；演示用提示词作为
  应用层选择移至 `main.py`（`DEMO_SYSTEM_PROMPT`）。§3.2 已同步修订。
- 2026-07-31：移除 `verbose` 参数——循环过程始终打印（demo 的核心看点），
  测试输出交给 pytest 捕获机制。§3.2 已同步修订。
- 2026-07-31：移除 `max_iterations` 参数与无限循环护栏，循环改为 `while True`
  （用户决定；create_agent 的等价保护是 langgraph 运行时 `recursion_limit`
  默认 10007，本项目有意不保留）。§3.2/§4/§5/§6 已同步修订；
  对应测试 `test_run_agent_stops_after_max_iterations` 已删除。
