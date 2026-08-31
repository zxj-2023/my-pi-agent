# Subagents 与 SubagentTask 任务委派设计规范 (`my_agent_core.subagents` & `subagent_tasks`)

- **定位**：声明式多智能体发现与受控任务委派调度引擎 (`packages/my-agent-core/src/my_agent_core/subagents.py`, `subagent_tasks.py`)
- **核心类**：`Subagent`, `SubagentManager`, `SubagentTask`, `SubagentTaskManager`, `make_task_tool`
- **主要实现**：`subagents.py`, `subagent_tasks.py`（保留 `tasks.py` 别名兼容）, `tools/builtin/task.py`

---

## 一、架构设计与定位

当面对复杂分工任务时，单一 Agent 会因为上下文过载而降低推理质量。
`subagents` 与 `subagent_tasks` 模块提供了一套声明式、强隔离的子智能体任务委派机制：

1. **声明式子代理发现**：在 `.agents/agents/*.md` 中以 Markdown 格式声明各领域专家专员；
2. **单工具桥接（Tool as Bridge）**：大模型无需理解底层通信协议，仅通过标准工具 `task(prompt, agent_type)` 即可委派任务；
3. **独立子会话树沙箱隔离**：子代理的完整对话历史保存在独立子会话文件中，主会话保持纯净；
4. **与项目看板（`TaskItem` / `TaskStore`）概念清晰分离**：`SubagentTask` 专指运行时子代理执行句柄，项目工程工单由 `TaskItem` / `TaskStore` 统一管理。

```text
  主 Agent ReAct 循环
         │
         ▼ 大模型发起委派: task(prompt="审查代码", agent_type="reviewer")
  ┌───────────────────────────────────────────────────────────────────┐
  │ SubagentTaskManager.start_task(prompt, "reviewer")                │
  ├───────────────────────────────────────────────────────────────────┤
  │  1. 查表 SubagentManager 获取 reviewer.md 提示词配置               │
  │  2. 创建独立子会话: <session_dir>/subagents/agent-task_xxx.jsonl   │
  │  3. 【防递归与沙箱隔离】:                                          │
  │     - 过滤掉父工具中的 task、memory 与 task_* 看板工具             │
  │     - 显式传入 subagent_dirs=[], plugin_dirs=[], memory_dir=False, │
  │       task_store=False                                            │
  │  4. 实例化 Child Agent 并在独立沙箱中执行 run(prompt)              │
  │  5. 捕获子代理最终总结文本 ➔ 返回给主 Agent 作为 tool 观察结果    │
  └───────────────────────────────────────────────────────────────────┘
```

---

## 二、核心类与数据结构

### 1. `Subagent` 与 `SubagentManager`

- **声明格式 (`.agents/agents/reviewer.md`)**：

  ```markdown
  ---
  description: 负责审查代码规范与测试覆盖率
  model: gpt-4o (可选，缺省继承父模型)
  tools: [read, edit] (可选白名单)
  disallowed_tools: [bash] (可选黑名单)
  skills: [code-review] (可选关联技能)
  ---

  你是一名资深代码审查员，严格按照检查单逐行评估代码质量...
  ```

- **`SubagentManager`**：扫描目录并按名索引所有子代理定义，拼装清单注入主 System Prompt。

### 2. `Task` 与 `TaskManager`

- **`Task` 状态机**：`RUNNING` ➔ `COMPLETED` / `ERROR`（状态互斥，携带 `result` 或 `error`）；
- **`TaskManager`**：管理并发任务计数器、派发子会话并驱动子 Agent。

### 3. `make_task_tool` 工具桥

将 `TaskManager` 包装为 OpenAI 标准 Function Calling 工具：

```json
{
  "name": "task",
  "description": "Delegate a subtask to a specialized subagent...",
  "parameters": {
    "type": "object",
    "properties": {
      "prompt": { "type": "string" },
      "agent_type": { "type": "string" }
    },
    "required": ["prompt", "agent_type"]
  }
}
```

---

## 三、核心设计不变式与安全防护

1. **子代理防递归与死锁防护（Anti-Recursion Invariant）**：
   - 子代理绝不能再次获得 `task` 工具，也不能重新扫描 `subagent_dirs` 或 `plugin_dirs`；
   - 彻底杜绝子代理尝试再次委派子任务导致的无限递归爆炸。
2. **父会话零历史污染**：
   - 子代理在执行过程中产生的大量中间推理、工具调用及大文件读取，全部封存在 `subagents/` 子目录中；
   - 主会话只记录一条最终的 `task` 工具返回结果。
3. **独立错误隔离**：
   - 子代理崩溃或抛出异常时，`TaskManager` 捕获并封装为 `TaskStatus.ERROR`，主 Agent 可在下一轮获取错误提示并决定是否更换策略。
