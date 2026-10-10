# 上下文离散 Epoch 块级压缩管线与 Append-Only 前缀一致性规范 (`my_agent_core.context`)

- **定位**：长文本上下文动态管理、离散 Epoch 块级压缩与 Prompt Cache 前缀稳定性引擎 (`src/my_agent_core/context.py`)
- **核心类**：`ContextManager`, `ContextSessionBridge`, `CompactionInfo`
- **压缩规约**：Append-Only 稳定前缀 (门控内) ➔ 80% 动态水位线 ➔ L3 磁盘溢出 ➔ L4 离散块结构化摘要

---

## 一、架构设计与演进背景

### 1. 传统滚动压缩的致命缺陷：前缀缓存频繁击穿 (Prefix Invalidation)

在早期的 Agent 架构中，常见的上下文压缩策略依赖“滑动窗口”模式（如 L1 滚动裁切中间轮次、L2 逐轮将过早工具输出替换为占位符）。
然而在深度对标现代主流大模型（如 DeepSeek、OpenAI、Anthropic）的原厂机制后，我们发现**逐轮滚动篡改是导致 API 成本激增与延迟劣化的头号元凶**：

- **KV-Cache / Prompt Cache 机制原理**：现代大模型服务端对输入 Prompt 实施前缀哈希缓存。只要输入消息序列的前 $K$ 个字节与此前请求完全一致，服务端即可直接复用已计算好的 KV-Cache，不仅大幅降低首字延迟（TTFT），且读取已缓存 Token 的价格仅为常规输入的 1/10 甚至更低；
- **滚动篡改的惩罚**：旧设计中每一轮都要裁切中间的一两条消息，或者将前 5 轮之前的工具输出就地修改为 `"[Earlier tool result compacted]"`。这种“每轮修改历史前缀中某一段”的做法，直接导致整条 Prompt 的前缀哈希彻底失效（Cache Miss），每一轮都必须重新进行全量 KV 编码计算，前缀缓存命中率跌至冰点。

### 2. 架构重构：Append-Only 前缀一致性 + 离散 Epoch 块级压缩 (Pi 原厂对齐)

基于上述工程洞察，`my-pi-agent` 彻底废除了旧的逐轮 L1 滚动截断与 L2 滚动工具篡改，确立了**对标 Pi 原厂的“Append-Only 前缀一致性 + 80% 动态水位线离散 Epoch 块级压缩”新范式**：

```text
               未超 80% 预算门控 (tokens <= budget_threshold)
               ────────────────────────────────────────────► 严格只读追加 (Append-Only)
              │                                             前缀 100% 字节级不变 (Cache 命中率 96.7%+)
              │
原始消息序列 ──┤
(messages)    │
              │ 超出 80% 动态水位线 (tokens > budget_threshold)
              └────────────────────────────────────────────► 触发离散 Epoch 块压缩
                                                             ├─ 尝试 L3: 超大结果磁盘溢出 (results_dir)
                                                             └─ 执行 L4: 离散块 LLM 智能结构化摘要
                                                                          │
                                                                          ▼
                                                         确立新 Epoch 稳定基准前缀：
                                                         [System, [Context summary], *retained_tail]
                                                                          │
                                                                          ▼
                                                         后续轮次在该基准上继续 Append-Only 累积
```

---

## 二、核心关键机制与技术实现

### 1. 工具执行期输出定型截断 (Tool Execution-time Truncation)

彻底废除运行时滚动修改工具消息的前提，是**确保单条工具输出在生成之初就不会发生失控膨胀**。
对标 Pi 原厂 `truncate.ts`，我们在 `src/my_agent_core/tools/core.py` 的 `ToolResult.serialize()` 阶段统一实施执行期定型截断：

- **规约参数**：`DEFAULT_TOOL_MAX_BYTES = 50 * 1024`（50KB），`DEFAULT_TOOL_MAX_LINES = 2000`；
- **定型保证**：超长工具输出在序列化写入 `role="tool"` 消息时即完成截断并追加统计提示（`[Output truncated: showing X of Y lines (...)]`）；
- **前缀不可变性**：一旦消息写入 Session 转录本，内容即成为永久确定性事实，后续轮次绝不再回溯篡改其内容，从根源保障前缀稳定。

### 2. 动态 80% 水位线门控管控 (`budget_threshold`)

`ContextManager` 严格执行阈值门控逻辑，对标 Pi 机制：

```python
def set_budget(self, budget: int) -> None:
    self.budget = budget
    self.budget_threshold = (budget * 4) // 5  # 严格 80% 水位线
```

- **门控未达（Tokens $\le$ 80%）**：`prepare()` 严禁对消息列表做任何删减、截断或篡改，原样返回 `list(messages)`。多轮交互中除尾部追加的新轮次外，前缀字节分叉数恒为 0；
- **门控触发（Tokens $>$ 80%）**：当且仅当上下文突破 80% 水位线时，微内核才激活压缩流程。

### 3. Usage 动态锚定与精确 Token 估算 (`record_usage`)

为了兼顾高频预检的极速响应与真实窗口占用的绝对精确：

- **字符/Token 动态比率校准**：日常以 `CHARS_PER_TOKEN = 4` 作为初始兜底估算；
- **API 真实回执反向锚定**：每轮大模型交互返回后，通过 `record_usage(usage)` 提取 `prompt_tokens`、`cache_read_tokens` 与 `cache_write_tokens`，结合上一次发送视图的字符数计算真实比率 `ratio = total_prompt_tokens / last_view_chars`；
- **Footer 视口无缝联动**：状态栏与微内核共用同一锚定比率，确保终端 UI 显示的上下文占比与微内核门控完全同源、零时差。

### 4. 离散 Epoch 块级压缩与基准前缀确立 (L3 ➔ L4)

当突破 80% 水位线时，`ContextManager` 执行离散块压缩：

1. **L3 超大工具结果磁盘溢出**：
   - 检查 `results_dir`；若存在超出 `max_chars`（默认 20,000 字符）的单条工具消息，将其持久化至 `.my_agent_core/tool-results/<tool_call_id>.txt`，并在视图中替换为 `<persisted-output>` 路径与前 2000 字符预览；
   - 若溢出后总 Token 回落至 80% 水位线以下，则直接返回溢出视图，**无需调用大模型**；
2. **L4 离散块 LLM 结构化摘要**：
   - 若 L3 溢出后依然超限，计算切割点 `cut = _find_cut(messages)`（向后保留 `keep_recent_tokens` 并严格对齐到 `user` 消息边界，永不破坏 `assistant(tool_calls) + tool*` 协议配对）；
   - 将 `messages[1:cut]`（跳过 System Prompt）打包作为上下文，调用大模型生成离散块结构化摘要；
   - 摘要生成后，构造全新的基准视图：
     ```python
     view = [SystemMessage] + [Message("user", "[Context summary] " + summary)] + retained_tail
     ```
   - 将该状态保存为 `_summary`、`_covered_count` 与 `_retained_tail`（不可变快照），并在当前 Epoch 内冻结该稳定基准前缀。

### 5. 防注入双标签结构与 6 Section 约束

在 L4 摘要生成过程中，系统部署了严密的安全与信息保留约束：

- **`<analysis>` ➔ `<summary>` 双标签防注入**：
  大模型被明确指令先在 `<analysis>` 标签内梳理核心上下文，随后在 `<summary>` 标签内输出正文。框架通过正则严格只提取 `<summary>` 内容，彻底杜绝历史对话中恶意注入的指令劫持摘要器；
- **6 Section 结构化模板**：
  强制摘要涵盖 6 大核心维度，杜绝发散与遗漏：
  1. `## Goal`（用户原始目标与核心诉求）
  2. `## Constraints & Preferences`（环境偏好与工程硬性约束）
  3. `## Progress`（细分 `### Done`、`### In Progress`、`### Blocked`）
  4. `## Key Decisions`（技术选型与关键决策）
  5. `## Next Steps`（下一步明确行动项）
  6. `## Critical Context`（变量名、路径、关键凭据等不可遗忘上下文）

### 6. 全生命周期文件操作足迹累积 (`<read-files>` / `<modified-files>`)

长任务中，Agent 容易在压缩后遗忘“之前读过哪些文件”或“改过哪些文件”，导致重复读取或盲目修改：

- `extract_file_operations` 自动解析被摘要消息中的工具调用（`read`, `view`, `write`, `edit` 等），提取目标路径列表；
- 继承并自动合并上一次摘要中的 `<read-files>` 与 `<modified-files>` 标签；
- 将累积去重后的文件足迹以结构化 XML 标签追加至摘要末尾，使 Agent 经历数十次压缩后依然对全局代码修改足迹了然于胸。

### 7. 会话持久化、`retainedTail` 缓存与 `compaction_floor` 护栏

- **`ContextSessionBridge` 持久化集成**：压缩触发后，`CompactionInfo` 自动写入 Session 树，作为带有完整审计元数据（前/后 Token、模型名、消耗 usage）的 `compaction` 条目落盘；
- **重启免重算**：会话加载时，`ContextSessionBridge.restore_cache()` 秒级重建基准前缀，无需花费 Token 重新总结；
- **`compaction_floor` 安全护栏**：Session 维护 `compaction_floor` 指针，严格禁止用户通过 `/rewind` 撤销至已摘要的历史节点之前，防止历史指针与压缩基线发生拓扑撕裂。

---

## 三、工程验证与实战数据

### 1. 100 轮多轮前缀稳定性仿真 (`tests/core/test_context.py`)

在全量测试套件中，`test_100_turns_prefix_stability_simulation` 对长达 100 轮的连续交互进行微观前缀一致性仿真：
- 跟踪每一轮发送视图相较于上一轮的前缀分叉点（Prefix Divergence）；
- **实测结果**：除在 80% 水位线处触发离散 Epoch 块压缩的极少数边界轮次（$\le 2$ 次）外，所有常规轮次的前缀分叉数**恒为 0（100% 字节不变）**，完全杜绝了滚动压缩带来的前缀抖动。

### 2. Terminal-Bench 2.1 实战验证：96.7% 前缀缓存命中率

在 Terminal-Bench 2.1 的高难度编译与系统重构赛题（如 `build-cython-ext`）实测中：
- 任务执行历经十余轮工具交互与大型 Cython 源码诊断；
- 借助执行期定型截断与 Append-Only 前缀一致性，底层 `session.jsonl` 采集的真实 Token 指标显示：
  $$\text{Cache Hit Rate} = \frac{\text{cache\_read\_tokens}}{\text{prompt\_tokens} + \text{cache\_read\_tokens}} = \mathbf{96.7\%}$$
- 这一数据充分验证了离散 Epoch 块级压缩架构在真实工程负载下的顶级能效与成本控制能力。
