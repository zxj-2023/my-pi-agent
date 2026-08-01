# 设计文档：my_agent_core context 管理 —— 估算、摘要式压缩、追问与轮次

- **日期**：2026-08-01
- **状态**：待实现
- **位置**：`my_agent_core/`，依赖框架文档（`Agent` / `llm_call` 缝隙 / 事件）；
  与 session 文档正交（恢复后从完整历史重建压缩视图）
- **设计参考**：`D:/code/python/pi/packages/agent/src/harness/compaction/`、
  `packages/ai/src/utils/estimate.ts`、`packages/agent/src/harness/utils/truncate.ts`

## 1. 背景与目标

用户需求清单（原文归纳）：

1. 最大轮次限制；
2. 用户持续对话，能记住之前的状态；
3. 支持追问——纯对话追问、带工具的追问；
4. 判断哪些信息该进 context（用户输入、工具结果、思考过程等）；
5. context 过长要有**基础**压缩（复杂压缩不做）。

调查结论（pi 的 context 管理五道防线，详见本系列调研记录）：
工具级截断（源头拦大输出）→ token 估算（provider 实测 + chars/4 启发式）→
摘要式 compaction（切点对齐 + 结构化摘要 prompt + 迭代再摘要）→
checkpoint 自动触发 → `transformContext` 每请求变换缝隙。
**pi 没有最大轮次硬计数**，防失控靠优雅停止钩子 + 压缩。

### 1.1 需求 → 设计映射（多数已被既有设计覆盖）

| 需求 | 结论 |
|---|---|
| 最大轮次限制 | **已覆盖**：框架文档的 `max_iterations`（每次 `run` 的护栏）。pi 无计数、靠钩子；`shouldStopAfterTurn` 式优雅停止入本文档 §9 |
| 记住之前状态 | **已覆盖**：`Agent.messages`（进程内）+ session 文档（跨进程） |
| 纯对话追问 | **天然支持**：再调 `run(text)` 即可——每轮全量历史重发，无需新机制 |
| 带工具的追问 | **天然支持**：同一个 `run()`，模型基于完整历史自行决定是否调工具（循环每轮都带全量 `tools` schema）；跨进程追问 = session 恢复 + `run()`/`resume_run()` |
| 塞什么进 context | 判断表见 §2.2 |
| 基础压缩 | 本文档主体：摘要式压缩（用户拍板：pi 风格，非滑动窗口） |

pi 的 steering/followUp 队列（运行中注入消息）是 async/TUI 场景的机制，
同步框架的追问 = 下一次 `run()`，v1 不引入。

### 1.2 已确认的需求（澄清记录）

| 问题 | 决定 |
|---|---|
| 压缩策略 | 摘要式（pi 风格：独立 LLM 调用生成结构化摘要 + 保留近期尾部），不用纯滑动窗口 |
| token 预算 | `context_budget` 默认 `None` = 不启用上下文管理（框架不知道用户的模型与窗口，不猜）；启用时显式传 token 数 |

### 1.3 非目标（YAGNI）

- provider usage 锚定的精确估算（pi `estimate.ts` 的精髓）——入 §9 路线图
- 压缩状态持久化为 session entry（session 文档 §9 typed entries 阶段再做；
  v1 压缩是内存视图，文件保持完整历史）
- split-turn 二次摘要（pi 的 `TURN_PREFIX_SUMMARIZATION_PROMPT`）
- `shouldStopAfterTurn` 式优雅停止钩子
- 工具级截断内建进循环（v1 给中间件 recipe，见 §4.4）

## 2. 架构

一个新模块，挂在既有的 LLM 缝隙上；循环与 transcript 均不知情、不受影响：

```
Agent._llm_call(messages, schemas)            ← 框架文档已定的缝隙绑定处
  │
  ├─ view = context_manager.prepare(messages) ← 新增：压缩视图（非破坏性）
  │      估算 → 未超阈 → 原样返回
  │      超阈 → 切点对齐 → 摘要调用（经 llm_call 缝隙，tools=[]）→ 缓存
  │      返回 [system?] + [摘要消息] + 尾部
  │
  └─ openai_chat(client, model, view, schemas)
```

### 2.1 与 pi 的角色对应

| my_agent_core | pi | 取舍说明 |
|---|---|---|
| `context.py` 的 `estimate_tokens` | `estimate.ts`（`CHARS_PER_TOKEN=4`） | 只取启发式；pi 的"最近 usage 实测 + 尾部估算"锚定法入路线图（需先在 wire dict 保留 usage） |
| `ContextManager.prepare` | `transformContext` 钩子（agent-loop.ts:289） | 同位置：LLM 边界、非破坏性、循环不知情。异：pi 是纯外部钩子，本项目为内建默认策略 + `transform_context` 钩子组合（见可扩展性文档） |
| 切点"对齐到 user 边界" | `findCutPoint` + 合法切点 + split-turn 处理 | 精简版：只保证"绝不切开 tool_calls 配对"这一条硬规则；不做 split-turn 二次摘要 |
| 摘要 prompt | `SUMMARIZATION_SYSTEM_PROMPT` + 结构化格式（compaction.ts:446-476） | 借鉴其结构与"不要续聊、只输出摘要"的约束措辞 |
| 内存压缩缓存（summary + covered_until） | `compaction` entry 持久化 + 上下文投影 | **刻意不同**：pi 的 session 是唯一事实源、上下文是投影；本项目文件已是完整 append-only 日志，压缩视图无需写回——恢复时从完整历史重建即可 |
| `truncate_result` recipe（经 `after_tool`） | `truncate.ts` 工具级截断（2000 行 / 50KB） | 同哲学（源头拦大输出），借现有中间件落地，零框架改动 |

### 2.2 哪些信息进 context（判断表，需求 4 的回答）

| 信息 | 进 context？ | 理由 |
|---|---|---|
| system prompt | ✓ 永远在首 | 人设与规则；压缩永不动它 |
| user 消息 | ✓ | 对话主线 |
| assistant 文本 content | ✓ | 模型自己的承诺与回答，追问连贯性靠它 |
| assistant 的 `tool_calls` + 配对的 tool 结果 | ✓ 要留整对 | 协议配对不变式；压缩切点必须对齐 user 边界正是为此 |
| `reasoning_content`（思考过程） | ✗ | 框架文档决策 7：提取保留在 transcript（可观察），发送前剥离（兼容性）。**压缩输入也不含它**——摘要器看对话不看思考 |
| 超大工具结果 | △ 源头截断 | recipe：`after_tool` 挂 `truncate_result`（§4.4），不进 transcript 才是第一防线 |
| 被压缩的旧历史 | → 换成摘要消息 | 一条 user 角色消息，带明确前缀标识 |
| 工具 schemas | ✓ 每轮全发 | 不算"历史"，不参与压缩；估算时计入预算 |

## 3. 文件格式 / 状态

无新文件格式。**状态两处**：

- transcript（`agent.messages` + session 文件）：永远完整，压缩不碰；
- 压缩缓存（`ContextManager` 内存）：`(summary: str, covered_until: int)`——
  "messages[1:covered_until] 已被此摘要覆盖"。`reset()` 清空。
  进程重启后缓存为空，`prepare()` 按需从完整历史重建。

## 4. 组件接口

### 4.1 `context.py`（新增，~150 行）

```python
def estimate_tokens(messages: list[dict]) -> int:
    """启发式：JSON 序列化总字符数 / 4（pi 的 CHARS_PER_TOKEN=4）。
    粗估，宁高勿低；精确化（usage 锚定）见 §9。"""

SUMMARIZATION_SYSTEM_PROMPT: str
    # 借鉴 pi："You are a context summarization assistant... Do NOT continue
    # the conversation. Do NOT respond to any questions. ONLY output the summary."

SUMMARIZATION_PROMPT_TEMPLATE: str
    # 借鉴 pi 的结构化格式：## Goal / ## Constraints & Preferences /
    # ## Progress（Done / In Progress / Blocked）/ ## Key Decisions / ## Next Steps
    # 再摘要时模板先附上"上一次摘要"（迭代式，pi 的 previousSummary 机制）

SUMMARY_MESSAGE_PREFIX = "[Context summary — earlier conversation compacted]\n\n"

class ContextManager:
    def __init__(self, budget: int, llm_call: Callable[[list[dict], list[dict]], dict],
                 keep_recent_tokens: int | None = None,
                 summarizer: Callable[[list[dict]], str] | None = None):
        """keep_recent_tokens 默认 budget // 4（pi 默认约 20k/128k ≈ 1/6，取 1/4 更保守）。
        summarizer：压缩策略注入点（可扩展性文档 §3.3）——待摘要消息列表 → 摘要文本；
        None = 内建 pi 风格结构化摘要（经 llm_call 的独立调用）。"""

    def prepare(self, messages: list[dict]) -> list[dict]:
        """返回本轮该发给模型的视图（可能是原列表，也可能是压缩视图）。
        非破坏性：绝不修改传入的 messages。
        算法：
          1. estimate_tokens(messages) <= budget * 0.8 → 原样返回（有缓存也不动）
          2. 定尾部：从尾向前累积 token ≥ keep_recent_tokens 得初始切点，
             向前对齐到最近的 role=='user' 消息（硬规则：尾部绝不以
             assistant(tool_calls)/tool 开头 → 配对不变式永远成立）。
             对齐后找不到 user 边界（整段是一个巨型 turn）→ 不压缩，原样返回
          3. 摘要范围 = messages[1:cut]（跳过 system）；若缓存覆盖部分范围，
             输入 = 旧摘要文本 + 新增部分（迭代再摘要）
          4. 摘要：summarizer(messages[1:cut]) —— 默认实现内部经 llm_call
             做结构化摘要调用（tools=[] 独立调用，见下方说明）；
             注入实现则完全替换（自定义模型/prompt/非 LLM 提取皆可）
          5. 更新缓存 (summary, covered_until=cut)，返回
             [system?] + [{"role":"user","content": PREFIX + summary}] + messages[cut:]
        """
```

摘要调用形态：`llm_call([{"role":"system","content": SUMMARIZATION_SYSTEM_PROMPT},
{"role":"user","content": 模板填充(对话序列化[, 旧摘要])}], [])`。
对话序列化 = 逐条 `role: content/tool_calls 摘要` 的纯文本（不直接塞 JSON，
省 token、摘要器更好读——对应 pi 的 `serializeConversation`）。

### 4.2 `Agent` 新增参数（agent.py 修改）

```python
class Agent:
    def __init__(self, ...,
                 context_budget: int | None = None,       # ← 新增：token 预算；None = 不启用
                 keep_recent_tokens: int | None = None,   # ← 新增：压缩后保留的近期 token（默认 budget//4）
                 transform_context: Callable[[list[dict]], list[dict]] | None = None,
                 compaction_summarizer: Callable[[list[dict]], str] | None = None):
        """context_budget 非 None 时创建 ContextManager（summarizer=compaction_summarizer）；
        _llm_call 变为管线：
            view = self._ctx.prepare(messages)             # 内建压缩（若启用）
            if transform_context: view = transform_context(view)   # 用户钩子，最终决定权
            return openai_chat(client, model, view, schemas)
        transform_context 契约（可扩展性文档 §2.2-4）：纯函数、非破坏性
        （不改传入 list）、异常向上抛（fail-loud，与内建摘要失败的降级宽容不同）。
        reset() 同时清空压缩缓存。其余契约全部不变。"""
```

### 4.3 新事件（框架文档事件集 6 → 7；现为 8，见可扩展性文档）

```python
@dataclass(frozen=True)
class ContextCompacted:    tokens_before: int; tokens_after: int; summarized_count: int
```

`prepare()` 每完成一次实际压缩，经 `on_event` 发射（复用框架文档的单一回调；
未压缩的 prepare 不发）。框架文档 §4.3/§4.6 与 README 随本文档同步修订。

### 4.4 大工具结果截断 recipe（非框架内建）

```python
# context.py 提供工具函数，用户经 after_tool 中间件挂上（框架文档已有机制）：
def truncate_result(text: str, max_chars: int = 8000, keep: int = 2000) -> str:
    """超限 → 保留头尾各 keep 字符，中间替换为 '\n[...truncated N chars...]\n'。
    未超限 → 原样返回。"""

agent = Agent(..., after_tool=lambda name, args, result, is_error: truncate_result(result))
```

对应 pi 的工具级截断哲学（大输出在源头拦住），但零框架改动。

## 5. 数据流（压缩发生的一次 run）

```
messages（完整 transcript，17 条，估算 95k tokens；budget=100k，阈值 80k）
        │
        ▼  prepare()
估算 95k > 80k → 触发
定尾部：从尾累积 ≥ 25k（keep_recent）→ 初始切点 i=9；
        messages[9] 是 tool 消息 → 向前对齐到 i=7（user 消息）
摘要范围 messages[1:7]（6 条）→ llm_call 独立调用（tools=[]）
        → FakeLLM/真模型返回结构化摘要文本
缓存 (summary, covered_until=7)
        │
        ▼  返回视图（9 条，估算 ~31k）
[system, {user: "[Context summary — ...]\n\n## Goal ..."}, messages[7:]]
        │
        ▼  openai_chat(client, model, 视图, schemas)
模型应答（它看到的：目标摘要 + 最近 7 条完整消息 + 全部工具）
        │
emit ContextCompacted(tokens_before=95k, tokens_after=31k, summarized_count=6)
        │
        ▼  transcript 不变（17 条），session 文件不变
下一轮 prepare()：估算未超阈 → 原样返回（不再调摘要，缓存待命）
```

## 6. 错误处理

| 故障 | 位置 | 处理 |
|---|---|---|
| 摘要 LLM 调用失败（API 错误） | `prepare()` 步骤 4 | **降级**：本次不压缩，返回原视图（压缩是可选优化，失败不应毁掉主 turn——与主流程 fail-loud 刻意不同；若随后 API 因超长报错，错误照常上抛） |
| 找不到 user 切点（单个巨型 turn） | `prepare()` 步骤 2 | 不压缩，原样返回；真超窗时 API 报错上抛，调用方处理 |
| 摘要返回空 content | 步骤 4 | 视同失败，降级 |
| 估算严重偏离真实 | 启发式固有 | 宁高勿低；真正的护栏是 API 自身报错（上抛）；usage 锚定估算在 §9 |

## 7. 测试与验收标准

### 7.1 离线测试（`tests/test_context.py`，FakeLLM 驱动，无网络）

| # | 测试 | 验证点 |
|---|---|---|
| 1 | `estimate_tokens` | 随消息增长单调递增；空列表为 0 |
| 2 | 未启用 | `context_budget=None` → `_llm_call` 请求的 messages 与 transcript 全等（现有测试不受影响） |
| 3 | 阈值下不触发 | 估算 < 0.8·budget → FakeLLM 只收到对话请求，无摘要请求 |
| 4 | 触发压缩 | 超阈 → 请求视图 = [system, 摘要消息, 尾部]；**原 messages 列表未被修改**（长度与内容不变） |
| 5 | 切点对齐 | 构造朴素切点落在 tool 配对中间的历史 → 视图尾部以 user 消息开头，无孤儿 tool 消息、无未配对 tool_calls |
| 6 | 摘要调用形态 | FakeLLM 收到的摘要请求：tools=[]、system 含"不要续聊"约束、user 含结构化格式要求与对话文本；返回的摘要文本出现在后续视图里 |
| 7 | 缓存复用 | 连续多次 `prepare` 无新增 → 摘要调用仅 1 次（FakeLLM 请求计数） |
| 8 | 迭代再摘要 | 压缩后继续增长再超阈 → 第二次摘要请求的 user 文本含第一次的摘要内容 |
| 9 | 摘要失败降级 | 摘要调用抛异常 → `prepare` 返回原视图，主请求照常进行 |
| 10 | Agent 集成 + 事件 | 完整 run 触发压缩 → `ContextCompacted` 事件恰发射一次、字段合理；`reset()` 后缓存清空（再触发会重新摘要） |
| 11 | `truncate_result` | 超限 → 头尾保留 + 截断标记；未超限 → 原样；边界值 |

### 7.2 验收标准（步骤 → 验证方式）

```
实现 context.py          → #1、#5（切点纯逻辑）、#11 通过
ContextManager + 缓存    → #3、#4、#6、#7、#8、#9 通过
Agent 集成 + 事件        → #2、#10 通过；框架文档与 session 文档既有测试全绿
全量                     → uv run pytest -q 全绿
真实验证（需 .env）      → 设一个小 budget（如 4000）跑多轮工具对话 →
                          控制台/事件可见 ContextCompacted，后续轮次仍能引用早期信息（摘要生效）
```

## 8. 与其他设计文档的联动

- **框架文档**（同步修订）：§4.3 事件集加 `ContextCompacted`（6→7）、§4.6 公共
  API 事件数、§8 路线图第 6 项"上下文压缩"指向本文档；修订记录 +1。
- **session 文档**：无改动。交互关系：session 文件存完整历史，压缩缓存不持久化；
  恢复 = 加载完整历史 → `prepare()` 按需重建视图（§3 已述）。
- **README**（同步修订）：TODO 新增「context 管理」块；事件项 6→7；
  路线图"上下文压缩"替换为进阶项。

## 9. 演进路线（pi 对应物）

1. **usage 锚定估算**（pi `estimate.ts` 精髓）：`openai_chat` 在 wire dict 保留
   `response.usage`（如 `_usage` 键，发送前剥离），估算改为"最近实测 + 尾部启发式"。
2. **压缩状态持久化**：session 文档 §9 typed entries 阶段，摘要作为
   `{"type":"summary",...}` 行，恢复时不必重算（对应 pi `compaction` entry）。
3. **优雅停止钩子**：上下文将满且无法再压时，本轮结束后停止
   （对应 pi `shouldStopAfterTurn`）；也是"最大轮次"的 pi 式补充。
4. **split-turn 二次摘要**（pi `TURN_PREFIX_SUMMARIZATION_PROMPT`）：
   巨型单 turn 不再"压不动"，前缀单独摘要。
5. **工具级截断内建**：若 recipe 用得普遍，升级为 `Agent(max_tool_result_chars=...)`。

## 10. 修订记录

- 2026-08-01：初版。用户决定：摘要式压缩（pi 风格）；`context_budget` 默认
  `None` 不启用。需求映射：轮次限制/状态记忆/追问均由既有设计覆盖，
  本文档新增估算 + 压缩 + 源头截断 recipe；事件集 6→7（`ContextCompacted`）。
- 2026-08-01：内建策略可注入化（`2026-08-01-my-agent-extensibility-design.md`）：
  `ContextManager` 增 `summarizer` 参数、`prepare` 步骤 4 改调 summarizer（§4.1）；
  `Agent` 增 `transform_context` / `compaction_summarizer` 参数与管线契约
  （§4.2：内建压缩先、用户钩子后、钩子 fail-loud）。测试 #8–#12 见可扩展性文档 §7.2。
