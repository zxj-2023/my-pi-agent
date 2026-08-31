# 12. 统一任务系统与后台异步执行 (Task System & Background Execution)

> **定位**：解决复杂多步任务（3~10 步）的目标规划与 DAG 依赖编排，实现全自动的上下文看板投影（`<TASK_BOARD>`），并提供具备孤儿进程防御的非阻塞后台执行引擎（`BackgroundRunner`）。

---

## 一、架构设计背景与痛点

在真实的智能体编程场景中，存在三大痛点：

1. **多步规划易跑偏**：在复杂的长程重构或多文件修改任务中，Agent 容易在连续的工具调用中迷失初始目标；
2. **缺乏 DAG 依赖与死锁防护**：简单的线性清单无法表达“任务 2 依赖任务 1 完成才能开始”的依赖关系，且容易产生环死锁；
3. **慢命令卡死主循环**：耗时几分钟的测试或构建命令（如 `pytest` / `npm build`）同步阻塞主 Agent，无法在后台并发推进。

针对以上问题，`my-pi-agent` 实现了**三位一体的统一任务子系统**：

- **DAG 依赖状态机（`TaskItem` + `TaskStore`）**：对标 Claude Code v2.1.142+ 与 `learn-claude-code` s10；
- **上下文看板自动投影（`Task Board View`）**：对标 Pi `@juicesharp/rpiv-todo` 与 Claude Code v1 s05；
- **后台异步调度与孤儿进程防御（`BackgroundRunner`）**：对标 Pi / Tau 与 `learn-claude-code` s11。

---

## 二、领域模型与命名划分

为避免与 Subagent 委派运行实例（`TaskManager` / `Task`）发生概念冲突，本系统遵循 OpenHands 与 `trpc-agent-python` 的领域分工：

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│ 1. 看板工单实体 (TaskItem & TaskStore)                                       │
│    • 代表【工程规划中的待办卡片】，跨轮次、跨 Session 持久存在在磁盘 tasks.json    │
│    • 状态机: pending -> in_progress -> completed (或 deleted 软删除)         │
│    • 核心属性: id, subject, description, blocked_by, owner, active_form     │
├─────────────────────────────────────────────────────────────────────────────┤
│ 2. 子代理委派实例 (my_agent_core.subagent_tasks)                             │
│    • 代表【一次 Subagent 的运行时执行容器】，存活于一次 task() 工具调用期间   │
│    • 状态机: RUNNING -> COMPLETED -> ERROR                                  │
│    • 核心属性: id, status, result, error, 拥有独立的 subagents/*.jsonl 会话   │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 三、DAG 依赖管理与原子持久化 (`TaskStore`)

`TaskStore` 管理 `<workspace>/.my_agent_core/tasks.json` 的内存状态与崩溃安全原子落盘（`tempfile` + `fsync` + `os.replace`）：

### 核心特性

1. **自增 ID 分配**：服务端自动分配 `task_1`, `task_2` 紧凑标识符；
2. **两阶段 DAG 建图**：模型先批量调 `task_create` 拿到真实 ID，再调 `task_update(task_id, add_blocked_by=[...])` 建立依赖边；
3. **传递性成环检测 (Cycle Detection)**：在添加依赖时沿图做回溯深度遍历，成环时立即拦截并抛错，防止死锁；
4. **单 `in_progress` 约束**：默认强制同一时刻至多一个任务处于 `in_progress`，保证 Agent 执行注意力高度聚焦；
5. **下游任务自动解锁 (Unblocking)**：当某任务标记 `completed` 时，自动计算并返回前置依赖已全部清空的 pending 任务列表 `unblocked`；
6. **并发互斥锁**：Store 内部由 `asyncio.Lock` 保护，支持多工具并发调用时状态绝对一致。

---

## 四、标准 4 增量 CRUD 工具族与 `todo_write`

通过工厂函数 `make_task_tools(store)` 导出 5 个标准工具（全部声明 `is_parallel_safe=True`）：

| 工具名 | 核心入参 | 返回内容 | 说明 |
| :--- | :--- | :--- | :--- |
| `task_create` | `subject`, `description`, `active_form`, `metadata` | `{"task": {"id", "subject", "status"}}` | 创建新任务 |
| `task_update` | `task_id`, `status`, `add_blocked_by`, `remove_blocked_by` 等 | `{"task": {...}, "unblocked": ["task_2"]}` | 增量更新与解锁回显 |
| `task_get` | `task_id` | 完整任务 JSON（含长 description 与 metadata） | 单任务详情查询 |
| `task_list` | `include_deleted` | 紧凑摘要列表（省略 description，极省 Token） | 全看板列表查询 |
| `todo_write` | `todos: list[dict]` | 最新看板渲染结果 | 批量便签覆盖写入 |

---

## 五、上下文看板自动投影 (`Task Board View`)

在 `Agent.run()` 的模型视图准备期（`BeforeModelCall` 决策点前），如果 `TaskStore` 中存在未完成的任务：

1. 框架自动调用 `store.render_board()` 渲染为全量紧凑 Markdown 看板；
2. 包装为 `<TASK_BOARD>\n...\n</TASK_BOARD>`；
3. 临时附加至大模型当轮的视图中（注入 System 消息末尾）。

```xml
<TASK_BOARD>
[x] task_1: 设计数据库表 (completed)
[>] task_2: 编写 API 接口 (in_progress - writing endpoints)
[ ] task_3: 编写单元测试 (pending, blocked by: [task_2])
</TASK_BOARD>
```

### 核心收益

- **0 API 工具往返消耗**：模型每轮睁眼即可看到当前进展与阻塞关系，无需花费轮次主动调 `task_list`；
- **Session 零污染**：投影仅存在于内存视图，不持久化到 Session JSONL 文件，保障历史记录绝对真实纯净。

---

## 六、后台异步执行引擎 (`BackgroundRunner`) 与孤儿进程防御

### 1. 异步调度与通知收割

在 `packages/my-coding-agent` 中，`bash` 工具支持 `run_in_background: bool = False` 参数：

1. 模型传 `run_in_background=True` 时，`BackgroundRunner` 启动后台异步子进程，立即返回 `[Background task bg_000001 started for command: '...']`；
2. 主 Agent 立即收到占位结果，继续推进其他工作；
3. 当子进程执行结束，`BackgroundRunner` 自动组装通知并送入已有的 `MessageQueue`：

   ```xml
   <task_notification id="bg_000001">
   Background task bg_000001 (pytest -q) completed (exit code 0):
   22 passed in 1.4s
   </task_notification>
   ```

4. 在两层循环的安全边界（`Outer Loop` 或 `Inner Loop` 安全点），通知被自动消费、原子落盘并驱动下一轮模型总结。

### 2. 对齐 Pi 规范的孤儿进程防御

- `BackgroundRunner` 记录所有活动子进程；
- 注册 `atexit` 清理钩子；
- 当 `agent.abort()`、系统 `SIGINT/SIGTERM` 或进程退出时，自动对所有活动子进程执行 `terminate()` / `kill()`，**彻底杜绝后台僵尸进程**。

---

## 七、架构不变式与测试覆盖

- **Never-Throw Guarantee**：工具异常与后台失败全部结构化捕获；
- **Crash-Safe Atomic Persistence**：`tasks.json` 采用原子替换；
- **100% 离线确定性单测**：全套 299 项测试在 FakeLLM 与离线子进程下全部绿灯通过。
