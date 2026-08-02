# my_agent_core

从零实现的最简 ReAct agent。只依赖 `openai` SDK、`pydantic` 与标准库，不依赖任何 agent 框架。

项目方向：pig-mono 式两层结构——本包 = **框架层**（对应 `pig-agent-core`）；
未来用它搭独立的 **coding agent 层**（对应 `pig-coding-agent`）。
详见文末「TODO：v1 实现路线」与设计文档（`docs/superpowers/specs/`）。

## 简介

约 200 行 Python，一个完整的 ReAct（Reason + Act）循环：模型决定是否调用工具，
本项目负责执行工具、把观察结果写回消息历史，循环持续——直到模型认为可以直接
回答为止。工具 schema 生成与参数校验委托 `pydantic`，其余协议细节
（`tool_calls` 解析、调度、错误容错）全部手写，透明可审查。

特性：

- `@tool` 装饰器：从函数名、docstring、类型标注自动生成发给模型的 JSON schema（pydantic 驱动，支持全集类型与默认值）
- ReAct 循环：Reason → Act → Observe → 重复，经典退出条件（`tool_calls` 为空即结束）
- 工具容错：工具异常、非法参数、不存在的工具名全部转成描述性消息回给模型，
  让模型有机会自我纠正
- 客户端依赖注入：生产传 `openai.OpenAI(...)`，测试传假客户端，全循环可离线测试
- 没有 Message 类：消息状态就是 OpenAI wire format 的普通 dict 列表——
  协议格式本身就是状态

## 怎么跑

```powershell
uv sync                        # 安装依赖
Copy-Item .env.example .env    # 然后把真实配置填进 .env（不是 .env.example）
uv run python -m my_agent_core.main # 在项目根目录执行
```

环境变量：

| 变量                | 必需 | 说明                         |
| ------------------- | ---- | ---------------------------- |
| `OPENAI_API_KEY`  | 是   | OpenAI API key               |
| `OPENAI_MODEL`    | 否   | 模型名，默认`gpt-4.1-mini` |
| `OPENAI_BASE_URL` | 否   | 自定义 OpenAI 兼容端点       |

测试（不需要 API key）：

```powershell
uv run pytest -q
```

## 项目结构

```
my_agent_core/
├── tools.py     # @tool 装饰器 + schema 生成 + 工具调用分发
├── agent.py     # ReAct 循环（run_agent）
└── main.py      # demo 入口：三个示例工具 + 三个示例问题
tests/
└── test_my_agent_core.py   # 离线测试（FakeLLM 驱动，按框架文档 §7 从零编写）
```

## 工作原理

```
用户问题 → [model] ──有 tool_calls──→ 执行工具 → 观察结果 ─┐
              ↑                                             │
              └─────────────── 回模型 ◄──────────────────────┘
              │
              └──无 tool_calls──→ 返回最终答案
```

每一轮把完整消息历史 + 工具 schema 发给模型；**是否调用工具由模型自己决定**
（模型厂商 function calling 训练的能力），本项目只负责翻译和调度：

1. **上行翻译**：`@tool` 把 Python 函数翻译成模型看得懂的 JSON schema，
   放进请求的 `tools` 字段
2. **下行调度**：读响应的 `tool_calls`——非空就逐个执行工具，把结果作为
   `role: "tool"` 消息写回 messages（与助手消息的 `tool_call_id` 配对），
   再问一轮；为空则循环结束，返回模型的文本

## 添加新工具

```python
from my_agent_core.tools import tool

@tool
def get_weather(city: str) -> str:
    """Get the weather for a city."""      # docstring 会成为工具描述
    return f"{city}: sunny, 22°C"

@tool
def search_docs(query: str, tags: list[str], limit: int = 5) -> str:
    """Search docs by query and tags."""   # 复杂类型、默认值都可以
    return f"results for {query} (tags={tags}, limit={limit})"

# 然后把它传入 run_agent 的 tools 列表：
run_agent(question, tools=[get_weather, search_docs], client=client, model=model)
```

参数类型支持 pydantic 全集（`list` / `dict` / `Optional` / 嵌套 `BaseModel` 等），
允许默认值；无标注参数与 `*args` / `**kwargs` 在装饰时拒绝。

## 设计取舍

- **库层没有默认系统提示词**：`run_agent` 的 `system_prompt` 默认为 `None`，
  不发送 system 消息；给模型什么人设由应用层决定（`main.py` 的 demo 自行
  传入 `DEMO_SYSTEM_PROMPT`）
- **没有无限循环护栏**：退出完全由模型判断；模型若陷入工具循环会持续消耗
  token，需手动 Ctrl+C 终止。如需护栏请自行添加最大轮数限制
- **同步顺序执行**：模型一轮发起多个 `tool_calls` 时逐个执行

## TODO：v1 实现路线

五份设计文档（**框架层**，对应 pig-mono 的 `pig-agent-core`）的整体实现，
按依赖排序；**coding agent 层**（对应 `pig-coding-agent`，用本框架搭成的
独立包）在这七阶段之后另行设计与实现。pig-mono（`D:/code/python/pig-mono`）
是 pi 的 Python 移植版，为直接参考。

**原则**：阶段 1–2 纯新增（旧代码不动，测试按 §7 清单逐步新建），阶段 3
切换到 `Agent` 类、测试补齐，阶段 4 起逐层叠加。每步带验证方式；
测试编号引自设计文档
（`docs/superpowers/specs/` 下：框架 = `...-framework-design.md`、
会话 = `...-session-design.md`、上下文 = `...-context-design.md`、
技能 = `...-skills-design.md`、可扩展性 = `...-extensibility-design.md`）。

### 阶段 1：LLM 缝隙与事件（纯新增，旧代码不动）

- [ ] 1.1 `llm.py`：`openai_chat` —— SDK 响应 → wire dict（含 `tool_calls`
      与不含两种翻译）；reasoning 三字段探测归一到 `reasoning_content`、
      发送前剥离 → 验证：框架 §7 #14
- [ ] 1.2 `events.py`：`Event` 基类 + 8 个事件 dataclass
      → 验证：可导入可实例化（行为由后续阶段测试覆盖）
- **阶段验证**：`uv run pytest -q` 全绿（#1、#14 先行通过；旧代码未动）

### 阶段 2：循环核心（纯新增，与旧代码并存）

- [ ] 2.1 `loop.py`：`run_loop` 骨架 —— 循环、经典退出条件、`LoopOutcome`、
      事件发射（暂不含中间件）→ 验证：框架 §7 #2–#5、#11（FakeLLM 驱动）
- [ ] 2.2 `loop.py`：执行前参数校验（经 `Tool.model` pydantic 校验 + 强转，
      逐条错误消息复用 tools.py 的 `_format_validation_error`）→ 验证：框架 §7 #6
- [ ] 2.3 `loop.py`：六段管道完成 —— `before_tool` / `after_tool` 中间件、
      `ToolBlocked` 拦截、中间件异常转错误字符串 → 验证：框架 §7 #7–#10
- [ ] 2.4 `loop.py`：`max_iterations`（默认 `None` 不限）
      → 验证：框架 §7 #12
- **阶段验证**：`uv run pytest -q` 全绿（#2–#12 加入测试集）

### 阶段 3：切换（框架 v1 完成）

- [ ] 3.1 `agent.py` 重写为 `Agent` 类：`run()` 多轮累积、`reset()` 保留
      system prompt、`_llm_call` 缝隙绑定 → 验证：框架 §7 #13
- [ ] 3.2 `tools.py` 移除 `call_tool`；`__init__.py` 导出公共 API
      （`Agent` / `tool` / `Tool` / `ToolBlocked` / 事件类型）
- [ ] 3.3 `main.py` demo 改用 `Agent`；同步更新本 README 的「添加新工具」
      示例与「设计取舍」措辞（`run_agent` → `Agent`）
- [ ] 3.4 补齐剩余用例（`tests/test_my_agent_core.py` 按框架 §7 清单）
      → 验证：#15 与其余项全通过
- **阶段验证**：`uv run pytest -q` 全绿（#1–#15，框架 §7.2：框架 v1 完成）；
  真实运行 `uv run python -m my_agent_core.main`，三个问题答案符合预期
  （703 / 当前时间 / 两城市天气）

### 阶段 4：session 管理

- [ ] 4.1 `session.py`：JSONL 格式读写（header + typed message 行）、
      `create_session` / `load_session` / `append_messages`（单次批量追加）、
      加载宽容规则（撕裂尾行、未配对尾部 tool_calls 丢弃；中段损坏带行号报错）
      → 验证：会话 §8 #1–#5
- [ ] 4.2 `store.py`：`SessionStore` —— create / list（倒序）/ open（唯一
      前缀匹配，歧义报错）/ delete；id = 时间戳 + 8 位随机 hex，碰撞重试
      → 验证：会话 §8 #10
- [ ] 4.3 `Agent` 集成：`session=` 参数（不存在即创建 / 存在即恢复 / 恢复时
      文件为准）、turn 边界落盘、`resume_run()` 崩溃续跑、`reset()` 重写文件
      → 验证：会话 §8 #6、#7、#8、#9、#11
- **阶段验证**：`uv run pytest -q` 全绿；真实跨进程演示——进程 1 创建会话 +
  问一个问题后退出；进程 2 `open(前缀)` 恢复 + 追问引用上一轮答案的问题，
  模型答得上

### 阶段 5：context 管理

- [ ] 5.1 `context.py`：`estimate_tokens`（chars/4 启发式）+
      `truncate_result`（头尾保留截断，经 `after_tool` 挂的 recipe）
      → 验证：上下文 §7 #1、#11
- [ ] 5.2 `context.py`：`ContextManager` —— 超 0.8·budget 触发、切点对齐
      user 边界（绝不切 tool 配对）、独立摘要调用（pi 风格结构化 prompt +
      “不要续聊”约束）、缓存复用、迭代再摘要、摘要失败降级不压缩
      → 验证：上下文 §7 #3–#9
- [ ] 5.3 `Agent` 集成：`context_budget=` / `keep_recent_tokens=`（默认
      `None` 不启用）、`transform_context=` / `compaction_summarizer=`
      可注入策略（管线：内建压缩先、用户钩子后、钩子 fail-loud）、
      压缩挂在 `_llm_call` 缝隙（循环与 transcript 不感知）、`reset()`
      清缓存、`ContextCompacted` 事件 → 验证：上下文 §7 #2、#10 +
      可扩展性 §7 #8–#12
- **阶段验证**：`uv run pytest -q` 全绿；真实运行：设一个小 budget
      （如 4000）跑多轮工具对话，事件可见压缩发生，后续轮次仍能引用早期信息

### 阶段 6：skill 机制

- [ ] 6.1 `skills.py`：`Skill` / `SkillDiagnostic` 模型、手写 `parse_frontmatter`
      （不引 PyYAML）、`load_skills` 发现（SKILL.md = skill 根不下钻 / 根级
      `.md` / 递归子目录 / 容错诊断）、规范校验（name / description）
      → 验证：skill §7 #1–#4
- [ ] 6.2 `skills.py`：`format_skills_for_prompt`（agentskills.io XML 清单，
      只含 name + description）+ `read_skill_tool`（按名取正文，未知名字 →
      错误字符串列可用清单）→ 验证：skill §7 #5–#7
- [ ] 6.3 `Agent` 集成：`skill_dirs=` 参数（清单拼 system 尾部、`read_skill`
      置于 tools 首位、诊断公开）、`invoke_skill()` 显式调用（`<skill>` 包装
      跑一轮）→ 验证：skill §7 #8–#11
- **阶段验证**：`uv run pytest -q` 全绿；真实 demo：写两个 SKILL.md
      （其一 `disable-model-invocation`），提一个匹配 description 的问题 →
      模型自主 `read_skill` 后按正文指令作答；`invoke_skill` 显式调用
      隐藏 skill 成功

### 阶段 7：动态工具

- [ ] 7.1 `run_loop` 的 `tools` 参数改 `get_tools`（每 turn 快照重建
      schemas 与分发表）；`Agent.tools` 改为可变注册表（对外只读）
      → 验证：可扩展性 §7 #2、#5
- [ ] 7.2 `Agent.register_tool` / `unregister_tool`（撞名 / 未知名报错）
      + `ToolsChanged` 事件（事件集 7→8）
      → 验证：可扩展性 §7 #1、#3、#4、#6
- [ ] 7.3 agent-as-tool 配方验证（子代理包装成工具，内外双层 FakeLLM）
      → 验证：可扩展性 §7 #7
- **阶段验证**：`uv run pytest -q` 全绿

> 每个阶段需要任务级实现计划（测试先行、review 检查点）时，用
> writing-plans 按阶段生成。

## 未来路线图

按序演进，每项对标 pi 的对应物：

- [ ] rewind：回退到 turn 边界（追加 rewind 标记行，append-only 不破；
      Claude Code `/rewind` 的极简版，用户指定的下一优先级）
- [ ] **coding agent 层**（新主线，独立包 `my_coding_agent`，基于 my_agent_core
      框架，对应 `pig-coding-agent`；待专门设计）：CLI 入口、coding 系统
      提示、权限门控（落点 `before_tool`）、内置工具组装（read / write /
      edit / bash 归属框架层还是本层待定）
- [ ] async 化：只改 `llm_call` 缝隙两侧（对应 pi 的全异步形态）
- [ ] 流式输出：`message_update` 类增量事件（对应 pi 的 `message_start/update/end`）
- [ ] 推理内容回传：去程保留 `reasoning_content`（多轮连续性，DeepSeek 式）
- [ ] 工具结果结构化：`str` → `content`（喂模型）+ `details`（给 UI）
      （对应 pi 的 `AgentToolResult`）
- [ ] context 进阶：usage 锚定估算、压缩状态持久化为 session entry、
      优雅停止钩子、split-turn 二次摘要（对应 pi `estimate.ts` / `compaction/`）
- [ ] session 进阶：逐条事件落盘、typed entries + reduce、树与分支、
      搜索索引（对应 pi `harness/session/` 完整版）
- [ ] skill 进阶：附带文件（正文路径引用）、user/project 分层作用域 +
      ignore 文件、动态刷新、REPL `/skill` 命令（对应 pi 完整 skill 机制）
- [ ] 可靠性：LLM 调用重试/指数退避（只对 429/5xx/连接错误，只改 `llm.py`
      缝隙；对应 pi 的 `RetryPolicy`）
- [ ] usage 保留与成本统计：assistant wire dict 挂 `_usage`（发送前剥离）、
      `Agent.total_usage` 累加；是「context 进阶 · usage 锚定估算」与
      会话级统计的前置
- [ ] `my_agent_core.testing`：FakeLLM 公开化，框架使用者可离线测自己的 agent
      （对应 pi 的 faux provider 测试套件）
- [ ] 动态工具进阶：全量/激活子集、注册表持久化（session typed entries）、
      `addedToolNames` 式延迟加载、MCP 协议加载器（对应 pi harness 完整机制）
- [ ] 可选内置工具（`my_agent_core.tools.builtin`，如 `read_file`）——
      skill 附带文件特性的前置
- [ ] 结构化输出：`run()` 的 JSON schema 强制变体
- [ ] 打包正式化：独立 pyproject、可安装（目前靠仓库根 pythonpath）
- [ ] 交互式多轮 REPL（应用层 demo，`Agent` 已为其铺路）
