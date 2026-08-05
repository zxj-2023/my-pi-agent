# 项目进度记录

学习项目：从零搭一个最小 agent 框架（参考 pi / pig-mono）。**透明度优先于通用性，不奔生产。**
本文件记录每个阶段做了什么、改了哪些文件、验证方式，方便复盘。

## 当前结构（2026-08）

```
my-pi-agent/
├── packages/
│   ├── my-agent-core/     # 框架层（src 布局，Python 包 my_agent_core）
│   │   ├── tools.py       # Tool 类 + ToolResult + tool() 装饰器
│   │   ├── registry.py    # ToolRegistry（注册表）
│   │   ├── agent.py       # run_agent（ReAct 循环）
│   │   └── main.py        # demo
│   └── my-agent-llm/      # 模型边界层（src 布局，Python 包 my_agent_llm）
│       ├── client.py      # LLM 门面（chat/stream/achat/achat_stream）
│       ├── config.py      # Config
│       ├── models.py      # Message / Response / StreamChunk
│       └── providers/     # openai / deepseek / anthropic
└── docs/superpowers/      # 本地设计文档 + 计划（不进 git）
```

---

## 已完成阶段

### 阶段 1：工具层 pydantic 化（2026-08-03）

**目标**：手写 `TYPE_MAP`（只支持 int/float/str/bool 四种标量）→ pydantic 动态建模。

- 规格：`docs/superpowers/specs/2026-08-03-pydantic-tool-schema-design.md`
- 提交：`f14f330` `19f40ba` `6666f0c` `964236e` `8638a33`
- **改了什么**：
  - 删除 `TYPE_MAP`；`@tool` 改用 `pydantic.create_model` 从函数签名动态建模
  - `Tool` 新增 `model` 字段——schema 生成与参数校验共用同一个 pydantic 模型
  - `call_tool` 执行前用 `model_validate` 校验 + 类型强转（`"37"` → 37）
  - 参数类型支持 pydantic 全集（list/dict/Optional/嵌套/默认值）
  - 新增 `tests/test_tools.py`（tests/ 首个文件）
- **过程中的关键教训**：规格假设「pydantic v2 默认严格区分 bool/int」被实测证伪（lax 模式接受 bool→int），补了 `BeforeValidator` 守卫。
- **验证**：21 个离线测试全绿，demo 真实运行通过（703 / 时间 / 天气）。

### 阶段 2：删 bool 守卫（2026-08-03）

**目标**：用户决定宽松——不拦 bool→int 强转，换更少代码。

- 提交：`3b83cd1` `bf6c263`
- **改了什么**：删 `_reject_bool_*` / `_NUMERIC_GUARDS`；`true` 传给 int 参数被强转成 1。
- **验证**：测试 21 → 20（删 `bool_not_accepted_as_int`）。

### 阶段 3：工具层类化重构（2026-08-03）

**目标**：`dataclass Tool + 自由函数` → `Tool 类 + ToolResult + ToolRegistry`（对齐 pig-mono 旧版形态）。

- 规格：`docs/superpowers/specs/2026-08-03-tool-class-design.md`
- 提交：`926d88c` `d7b8c57` `3c26139` `57ad571`
- **改了什么**：
  - `Tool` 改为类：`to_openai_schema()` / `execute()` / `__call__`，支持 `name`/`description`/`params_model` 覆盖
  - 新增 `ToolResult`（ok/data/error + serialize，永不抛）
  - 新增 `registry.py`：`ToolRegistry`（register/unregister/get/get_schemas/execute(tool_call)）
  - `agent.py` 改用 registry；删除 `schemas_for` / `call_tool` 自由函数
  - `tool()` 改为工厂装饰器（支持 `@tool` 与 `@tool(name=...)`）
- **过程中的关键教训**：最终评审抓到一个真实回归——Task 2 删 `call_tool` 时 `agent.py` 签名的 `list[Tool]` 注解悬空引用，`get_type_hints` 会 NameError（补回 import 修复）。
- **验证**：29 个离线测试全绿（test_tools 18 + test_registry 11）。

### 阶段 4：删翻译函数（2026-08-03）

**目标**：用户决定去掉 `_clean_schema` / `_format_validation_error` 两个翻译层，schema 与错误消息直接用 pydantic 原始输出。

- 提交：`6df40fc`
- **改了什么**：`to_openai_schema()` 直接返回 pydantic 原始 schema（带 title）；`execute` 校验失败直接 `str(exc)`。
- **验证**：测试相应调整后全绿（schema 断言改逐字段、错误断言匹配 pydantic 原文）。

### 阶段 5：目录重组（2026-08-03）

**目标**：`my_agent_core/` 移入 `packages/my-agent-core`（src 布局，独立 uv 项目），对齐 pig-mono 的 monorepo 结构。

- 提交：`603380f` `0e8bb4b`
- **改了什么**：
  - 包移入 `packages/my-agent-core/`，src 布局 + hatchling 构建
  - pyproject name 改为 `my-agent-core`
  - **过程中解决的坑**：加 `[build-system]` 后 `dependencies` 一度被 Edit 错放进 `[tool.hatch.build.targets.wheel]` 段导致依赖装不上（修正归位）
  - `.gitignore` 加入 `CLAUDE.md` 与 `docs/superpowers/`（本地私有文档，不上传远程 GitHub）
- **验证**：29 个测试全绿，demo 运行链通（429 配额限制除外）。

### 阶段 6：模型边界层 `my-agent-llm`（2026-08-03）

**目标**：独立「模型边界层」包——统一 `LLM` 类屏蔽 provider 差异，三 provider（openai/deepseek/anthropic）。

- 规格：`docs/superpowers/specs/2026-08-03-my-agent-llm-design.md`
- 提交：`2e8d53c` `d41b272` `2b1d4ef` `5b5ae4b` `dfe3ef0` `822517a` `3ca1356`
- **改了什么**：
  - `LLM` 门面：`chat`/`stream`/`achat`/`achat_stream` + 按 provider 路由 + kwargs 透传（只透传不碰 SDK）
  - `Config`（pydantic frozen）；`Message`/`Response`/`StreamChunk` 数据模型（tool_calls 统一 OpenAI 形状）
  - `OpenAIProvider`（基准翻译）→ `DeepSeekProvider`（继承 + reasoning_content 提取）→ `AnthropicProvider`（block 双向翻译 + web_search 增强）
  - 假 SDK 注入测试缝隙（`client=` 参数），全部离线测试
- **过程中的关键教训**：
  - 最终评审抓到 **Critical：`achat_stream` 异步生成器契约**——基类声明协程语义、provider 实现异步生成器，内部矛盾（裁定统一为异步生成器）
  - 修复波次又引入 **回归：`LLM.chat` 注入 `max_tokens=None` 废掉 anthropic 4096 回落**（复审抓到，第二轮修复为源头不注入）
- **验证**：33 个离线测试全绿，无 warning。

---

## 进行中

### 阶段 7：agent 层接入 `my-agent-llm`（进行中）

**目标**：`run_agent` 从裸 `openai.OpenAI` 改为用统一 `LLM` 类。

- 已确认决策：agent 内部统一用 `Message` 对象（对齐 pig-mono，wire dict 是 OpenAI 专属形状，`Message` 才是跨 provider 的统一契约）；`run_agent` 收 `llm` 对象。
- 待定：`registry.execute` 收 tool_call 的形状（dict vs 属性对象；参考 pig-mono——它从 `Response.tool_calls` dict 拆 name+args 后喂 `execute_sync(name, args)`）。

---

## 未来路线（v1 路线图，见 `packages/my-agent-core/README.md`）

- 阶段 1：`llm.py` 缝隙 + 事件类（已部分被 my-agent-llm 覆盖）
- 阶段 2：`loop.py` 无状态循环 + 中间件
- 阶段 3：`Agent` 类（有状态外壳）
- 阶段 4-7：session / context / skills / 动态工具
- coding agent 层（`my_coding_agent`）——框架层完成后
