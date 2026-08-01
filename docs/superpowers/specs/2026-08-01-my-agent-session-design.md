# 设计文档：my_agent_core session 管理 —— 单文件持久化、跨进程续聊、多会话

- **日期**：2026-08-01
- **状态**：待实现
- **位置**：`my_agent_core/`，依赖《my_agent_core 框架层设计》（`2026-08-01-my-agent-framework-design.md`）的 `Agent` / 事件机制
- **设计参考**：`D:/code/python/pi/packages/agent/src/harness/session/`（pi 的 session 层，约 1560 行）

## 1. 背景与目标

框架层设计（下称"框架文档"）的 §8 路线图第 5 项原为"JSONL 会话持久化"。
用户决定将其提前，并明确三点需求：

1. **单文件持久化**：一个会话 = 一个 JSONL 文件，运行中实时落盘；
2. **跨进程重启续聊**：进程退出后，新进程能从文件恢复完整历史继续对话；
3. **多会话管理，互不冲突**：能创建、列出、按 id 打开、删除多个会话；两个会话之间零共享状态。

**参考对象**：pi 的 session 层——append-only entry 树 + JSONL 存储 +
SessionStore 仓库层 + 事件驱动落盘。本项目取其中最实用的两层
（单文件存储、仓库），砍掉树/分支/typed 配置/操作日志。

### 1.1 已确认的需求（澄清记录）

| 问题 | 决定 |
|---|---|
| 持久化粒度 | 单文件：一个会话一个 `.jsonl` |
| 恢复语义 | 跨进程重启续聊（不是崩溃恢复；crash 最多丢一个未完成的 turn，见 §6） |
| 多会话 | 仓库层：create / list / open / delete；会话间结构性隔离（独立文件） |
| rewind（Claude Code 式回退） | 明确排后，进本文档 §9 路线图首位；但 v1 文件格式为它预留（§3） |
| 并发写同一会话 | 单写者规则（与 pi 一致），v1 不做 OS 文件锁（见 §6） |

### 1.2 非目标（YAGNI）

- entry 树与分支（pi 的 `parentId` 链 + `moveTo`）
- typed 配置 entries（model_change / active_tools_change 等）——v1 只有一种
  entry 类型 `message`；格式上已分型（§3），加类型是未来的事
- compaction 摘要 entry、搜索索引（pi 的 `SessionSearch`）
- 操作日志级崩溃恢复（pi harness-v2 的 lanes / operation log）
- OS 文件锁（flock / lockfile）
- 会话间共享的任何状态

## 2. 架构

新增两个模块 + `Agent` 一个参数；循环（`run_loop`）完全不碰持久化：

```
SessionStore (store.py) —— 会话仓库
  root 目录下 create/list/open/delete，返回 SessionMeta
        │ 给出文件路径
Agent(..., session=<path>) —— 持久化外壳
  初始化：文件存在 → 恢复；不存在 → 创建（system_prompt 落为首条消息）
  run()：追加 user 行 → run_loop → turn 结束后单次批量追加本轮新消息
  resume_run()：transcript 尾部是 user/tool 时，不追加新 user 直接续跑
        │ 调用
session.py —— 文件格式与读写
  create_session / load_session / append_messages（单次 append 调用）
  加载宽容规则：坏尾行丢弃、未配对尾部 tool_calls 丢弃（§6）
```

### 2.1 与 pi session 层的角色对应

| my_agent_core | pi harness/session | 取舍说明 |
|---|---|---|
| `session.py` 读写函数 | `jsonl-storage.ts`（`JsonlSessionStorage`） | 同：header 行 + JSONL 追加、加载校验。异：pi 是树（entry 带 `parentId`/`id`，叶指针），本项目是纯消息序列——无分支需求时树是负担 |
| `{"type":"message","message":{...}}` 行 | `MessageEntry`（types.ts 11 种 entry 之一） | 行已分型，v1 只有 `message` 一种；未来 rewind 标记、摘要都是新 type，格式不用迁移 |
| `load_session` | `buildSessionContext` 的 reduce | pi 要 reduce（折叠 compaction/change entries、投影成消息）；本项目无其他 entry 类型，reduce 退化为"剥信封"恒等投影 |
| `store.py` 的 `SessionStore` | `jsonl-repo.ts`（`JsonlSessionStore`） | 同：create/list/open/delete、list 只读 header 行、id 带时间戳可排序。异：pi 按 cwd 分子目录（`--encoded-cwd--`），v1 平铺一个目录 |
| Agent turn 边界批量写入 | `agent-harness.ts` 的 `message_end` 逐条落盘 + `turn_end` 刷写 | **刻意不同**：pi 逐条落盘 + 操作日志保证中途崩溃也不丢不残；本项目无操作日志，逐条落盘会留下未配对 `tool_calls`（违反框架文档核心不变式），故选 turn 边界批量写（§6） |
| （无） | `MemorySessionStorage`、搜索索引、lanes | 不做 |

### 2.2 关键设计决策

1. **typed 行格式，但只实现一种类型**。每行 `{"type": ..., ...}` 而非裸消息
   dict。理由：rewind 已被用户明确排入下一优先级，rewind 标记、未来的摘要
   都是"新 entry 类型"；现在多一层信封（成本 ~0），将来加类型零迁移。
   这是从 pi 借的最小一课：日志分型，状态是日志的投影。
2. **turn 边界批量写入，而不是事件逐条写入**。框架文档的 `on_event` 完全
   可以做"逐条 message 落盘"（pi 的方式），但崩溃在 assistant（带 tool_calls）
   已落盘、tool 结果未落盘时，恢复出的 transcript 尾部未配对，下一次 API
   调用直接被拒——pi 用操作日志解决，我们没有。turn 边界单次批量追加
   （一次 `append` 调用写多行）保证**任何持久化时刻 transcript 都满足配对
   不变式**。代价：turn 中途崩溃丢整个 turn（已计费的 LLM 调用会重跑），
   可接受（§6）。事件逐条写 + 加载修复留在 §9，配操作日志才有意义。
3. **恢复时文件为准**。文件已存在（恢复模式）时，构造函数的 `system_prompt`
   参数被忽略——transcript 自包含（system 消息就在文件里）。避免恢复后
   出现两条 system 消息。
4. **id = 时间戳 + 8 位随机十六进制**（`20260801-153012-a1b2c3d4`），
   文件名 `<id>.jsonl`——时间戳前缀使目录列表天然按创建时间排序
   （pi 的 `时间戳_sessionId.jsonl` 同款思路）；创建时碰撞则重试。
5. **`reset()` 是唯一破坏性操作**：清空内存 transcript，并把文件重写为
   header（+ system 消息，若有）。append-only 是循环/写入路径的不变式，
   不是用户 API 的不变式；显式 reset 允许重写。

## 3. 文件格式

一个会话一个文件，UTF-8，每行一个 JSON 对象：

```jsonl
{"type":"session","version":1,"id":"20260801-153012-a1b2c3d4","created_at":"2026-08-01T15:30:12","cwd":"D:/code/python/ReAct"}
{"type":"message","message":{"role":"system","content":"You are a helpful assistant."}}
{"type":"message","message":{"role":"user","content":"Calculate 37 times 19."}}
{"type":"message","message":{"role":"assistant","content":null,"tool_calls":[{"id":"call_1","type":"function","function":{"name":"multiply","arguments":"{\"a\": 37, \"b\": 19}"}}],"reasoning_content":"..."}}
{"type":"message","message":{"role":"tool","tool_call_id":"call_1","content":"703"}}
{"type":"message","message":{"role":"assistant","content":"The answer is 703."}}
```

- **header 行**（首行，必有）：`version: 1`、`id`、`created_at`（ISO 日期）、
  `cwd`（创建时工作目录，元信息）。不带 system_prompt——它在 transcript 里。
- **message 行**：`message` 字段就是 wire dict 原样（含 `tool_calls`、
  `reasoning_content` 等键）。`reasoning_content` 照常落盘（框架文档决策 7：
  提取但不回传——落盘属于"提取保留"，发送前剥离属于"不回传"，两者不矛盾）。
- 未来类型（预告，v1 不实现）：`{"type":"rewind",...}`、`{"type":"summary",...}`。

## 4. 组件接口

### 4.1 `session.py`（新增，~120 行）

```python
@dataclass(frozen=True)
class SessionMeta:
    id: str
    path: Path
    created_at: str
    cwd: str

def create_session(path: str | Path, *, session_id: str, cwd: str | None = None,
                   system_prompt: str | None = None) -> SessionMeta:
    """创建新会话文件：写 header 行；给了 system_prompt 则再写一条 system message 行。
    文件已存在 → 抛 FileExistsError（创建语义，不是 upsert）。"""

def load_session(path: str | Path) -> tuple[SessionMeta, list[dict]]:
    """读回 (meta, messages)。校验与宽容规则见 §6：
    - header 缺失/非法 / 非尾行非法 / version 不支持 → 抛 ValueError（带行号）
    - 尾行 JSON 损坏（写中断的撕裂行）→ 丢弃该行
    - 尾部 assistant 带未配对 tool_calls → 丢弃该条（恢复后重跑该 turn）
    v1 只认 type=="message" 行；未知 type 的非尾行 → 抛错，尾行 → 丢弃。"""

def append_messages(path: str | Path, messages: list[dict]) -> None:
    """把一批消息包成 message 行，拼成一个字符串，单次 append 写文件。
    单次调用 = 撕裂只可能发生在行边界，加载规则可兜住。"""
```

### 4.2 `store.py`（新增，~90 行）

```python
class SessionStore:
    def __init__(self, root: str | Path = ".my_agent_core/sessions"):
        """会话仓库：root 不存在时首次 create 才建（惰性）。"""

    def create(self) -> SessionMeta:
        """新会话：id = 时间戳-8位随机hex（碰撞重试），写 <root>/<id>.jsonl。"""

    def list(self) -> list[SessionMeta]:
        """扫 root 下 *.jsonl，每个只读首行 header（pi 同款），按创建时间倒序。"""

    def open(self, id_or_prefix: str) -> SessionMeta:
        """全 id 或唯一前缀匹配；未找到 / 前缀歧义 → 抛 ValueError（列出候选）。"""

    def delete(self, id_or_prefix: str) -> None:
        """删文件。解析规则同 open。"""
```

### 4.3 `Agent` 的 session 参数（agent.py 修改）

```python
class Agent:
    def __init__(self, *, client, model, tools=(), system_prompt=None,
                 max_iterations=None, on_event=None, before_tool=None, after_tool=None,
                 session: str | Path | None = None):       # ← 新增
        """session=None → 纯内存（向后兼容，现有测试不受影响）。
        session=路径 → 文件存在则 load_session 恢复（system_prompt 参数被忽略，
        文件为准）；不存在则 create_session（system_prompt 落为首条消息）。"""

    session_path: Path | None        # 公开可读

    def run(self, user_input: str) -> str | None:
        """有 session 时：先 append_messages([user 消息])，再 run_loop，
        结束后 append_messages(本轮新增消息)（两次单次调用）。
        run_loop 抛异常时：user 消息已持久化、本轮未落盘 → 恢复后见 §4.4。"""

    def resume_run(self) -> str | None:
        """不追加新 user，直接跑 run_loop。仅当 transcript 尾消息是
        user 或 tool 时合法（对应 pi 的 agentLoopContinue）；尾部是
        assistant → 抛 ValueError。用途：上次进程崩溃/退出后接着干。"""

    def reset(self) -> None:
        """清空 transcript；有 session 时把文件重写为 header（+ system 消息）。
        唯一破坏性操作（决策 5）。"""
```

### 4.4 崩溃后的恢复路径（说明，非接口）

turn 中途崩溃 → 文件尾部是本次 `run()` 追加的 user 消息。新进程：

```python
agent = Agent(..., session="chat.jsonl")   # 恢复，尾部是未应答的 user
agent.resume_run()                          # 不追加新输入，直接让模型应答它
```

若用户不想要那次未完成的输入，正常 `run("新问题")` 也可以——连续两条
user 消息对 OpenAI API 合法，模型按最新一条处理。

## 5. 数据流

两个独立进程，同一个会话文件：

```
── 进程 1 ────────────────────────────────────────────
store = SessionStore(); meta = store.create()        → 20260801-153012-a1b2c3d4.jsonl（仅 header）
agent = Agent(..., system_prompt="...", session=meta.path)
                                                     → 文件 += system 行
agent.run("Calculate 37 times 19.")
  ① 追加 user 行                                     → 文件 += user
  ② run_loop：模型发 multiply → 执行 → 最终回答
  ③ 批量追加 [assistant(tool_calls), tool(703), assistant(最终)]
                                                     → 文件 += 3 行（单次 append）
进程退出。文件：header + 5 条消息，尾部是完整配对的 turn。

── 进程 2（重启后）──────────────────────────────────
meta = SessionStore().open("20260801-153012")        # 前缀匹配
agent = Agent(..., session=meta.path)                # 恢复 5 条消息
agent.run("And what is that times 2?")               # 模型看得到 703 的来历
```

## 6. 一致性与并发（"两个会话不能冲突"）

**会话之间**：结构性隔离——每个会话独立文件、独立 `Agent` 实例，
仓库层只操作文件元信息，无共享可变状态。两个会话并发运行零交互；
id 生成碰撞（时间戳同秒 + 随机尾相同）由 create 重试兜底。

**同一会话**：**单写者规则**——一个会话文件同一时间只允许一个进程写。
与 pi 立场一致（`JsonlSessionStorage` 无文件锁，靠"单一 writer"纪律）。
两个进程同时写同一文件 = 使用错误，v1 不检测不阻止；OS 锁（lockfile）
列入 §9（真需要时 ~30 行，带 stale pid 检测）。

**崩溃一致性**——三条保证：

1. **append-only**：运行中从不改写已落盘内容（`reset()` 除外，显式用户操作）；
2. **批量单次追加**：一个 turn 的全部消息在一次 `append` 调用里写入，
   撕裂只可能发生在行边界；
3. **加载宽容规则**（`load_session`）：
   - 尾行 JSON 解析失败（撕裂行）→ 丢弃该行；
   - 尾部 assistant 消息带 `tool_calls` 但无配对的 tool 结果 → 丢弃该条；
   - 非尾行损坏、header 非法、version 不支持 → 抛错（带行号），不静默吞。

这三条共同保证：**任何崩溃点之后恢复出的 transcript，都满足框架文档
的"tool_calls 必配对"不变式**，下一次 API 调用永远合法。

## 7. 错误处理

| 故障 | 位置 | 处理 |
|---|---|---|
| 会话文件 header 缺失 / 非法 / version 不支持 | `load_session` | 抛 `ValueError`（指明文件与行） |
| 非尾行 JSON 损坏 | `load_session` | 抛 `ValueError`（带行号）——中段损坏不静默 |
| 尾行撕裂 / 尾部未配对 tool_calls | `load_session` | 丢弃该行/该条（崩溃恢复语义） |
| `create` 时文件已存在 | `create_session` | 抛 `FileExistsError`（创建不是 upsert） |
| `open` / `delete` 未找到或前缀歧义 | `SessionStore` | 抛 `ValueError`（歧义时列出候选 id） |
| 恢复模式下传了 `system_prompt` | `Agent.__init__` | 忽略（文件为准，决策 3） |
| `resume_run` 时尾部是 assistant | `Agent.resume_run` | 抛 `ValueError`（无可续内容） |
| 两个进程写同一文件 | —— | 未定义行为（单写者规则，§6） |

## 8. 测试与验收标准

### 8.1 离线测试（`tests/test_session.py`，不需要 API key）

| # | 测试 | 验证点 |
|---|---|---|
| 1 | 格式创建 | `create_session` → 首行 header 字段齐全；带 system_prompt → 第二行 system 消息；文件已存在 → `FileExistsError` |
| 2 | 往返 | `append_messages` 两批 → `load_session` 回读消息与写入全等 |
| 3 | 撕裂尾行 | 文件尾部追加半行 JSON → load 丢弃该行、其余完好 |
| 4 | 未配对尾部 | 尾部 assistant 带 tool_calls 无 tool 结果 → load 丢弃该条 |
| 5 | 中段损坏 | 非尾行写入乱码 → 抛错且错误含行号 |
| 6 | Agent 持久化 | `FakeLLM` + session 路径跑一轮工具调用 → 文件行序：header, user, assistant(tool_calls), tool, assistant |
| 7 | 跨"进程"恢复 | 第一个 Agent 跑完；第二个 Agent 同路径构造 → 首次 `FakeLLM` 请求的 messages 含上一轮全部历史 |
| 8 | `resume_run` | 手工写一个尾部为 user 的文件 → `resume_run()` 不追加 user、模型请求以该 user 结尾 |
| 9 | `reset` | 持久化 Agent reset → 内存清空、文件重写为 header（+ system） |
| 10 | 仓库 | create/list（倒序）/open 全 id/open 唯一前缀/歧义前缀报错/delete；连续两次 create → 两个不同 id |
| 11 | 恢复忽略 system_prompt | 带 system 的文件 + 构造时另传 system_prompt → transcript 中只有一条 system（文件里的） |

### 8.2 验收标准（步骤 → 验证方式）

```
实现 session.py          → #1-#5 通过
实现 store.py            → #10 通过
Agent 集成               → #6、#7、#9、#11 通过；框架文档既有测试全绿（session=None 路径不变）
resume_run               → #8 通过
全量                     → uv run pytest -q 全绿
真实跨进程演示（需 .env） → 进程 1：store.create() + 问一个问题；进程退出
                          进程 2：store.open(前缀) + 问引用上一轮答案的问题 → 模型答得上
```

## 9. 演进路线（用户指定顺序 + pi 对应物）

1. **rewind**（用户指定的下一优先级）：回退到某个 turn 边界。两条路：
   a. 追加 `{"type":"rewind","to":<行号/turn号>}` 标记行，load 时按标记截断
   （append-only 不破，pi 风格）；b. 直接截断文件尾（简单但破坏日志完整性）。
   届时再定；Claude Code 的 `/rewind` 是 a 的 UI 化。
2. **逐条事件写入 + 加载修复**：`on_event` 消费者逐条落盘（pi `message_end`
   方式），获得 turn 中途耐久性；与本文档 §6 加载规则天然配套。
3. **typed entries 扩容**：配置变更、摘要作为新 entry 类型，`load` 开始
   真正做 reduce（对应 pi `buildSessionContext`）——compaction 的前置。
4. **树与分支**：entry 加 `id`/`parentId`、叶指针（pi `moveTo`）；rewind 的
   完全体（回退 = 移动叶，旧分支保留）。
5. **OS 文件锁 / 搜索索引 / 按 cwd 分目录**：按需添加（pi 都有对应物：
   无锁单写者、`SessionSearchIndex`、`encodeCwd` 子目录）。

## 10. 与框架文档的关系

- 框架文档 §8 路线图第 5 项"JSONL 会话持久化"由本文档接管并提前实现；
- 实现顺序建议：先完成框架文档的 v1（`Agent`、事件、管道），再实现本文档
  （依赖 `Agent` 存在）；两份实现计划独立；
- 本文档不改动框架文档已定的任何契约（`run_loop` 签名、事件类型、
  中间件语义），只给 `Agent` 加一个可选参数与两个方法。

## 11. 修订记录

- 2026-08-01：初版。用户需求：单文件持久化 + 跨进程续聊 + 多会话互不冲突；
  rewind 排后。关键决策：typed 行格式（为 rewind 预留）、turn 边界批量写入
  （保住配对不变式，放弃 pi 的逐条事件落盘）、恢复时文件为准、单写者无锁。
