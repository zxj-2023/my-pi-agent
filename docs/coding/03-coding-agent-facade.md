# CodingAgent 产品门面与提示词装配规范 (`my_coding_agent.agent`)

- **定位**：面向工程研发助手的顶层产品门面与环境组装层 (`src/my_coding_agent/agent.py`, `prompt.py`)
- **设计标杆**：`tau` (`tau_coding`)、`@earendil-works/pi-coding-agent`
- **核心能力**：Dual API（批处理与流式生成器）、自动化项目上下文注入（`<project_context>`）、资深工程师系统提示词组装、五大专职 Hook 接入

---

## 一、架构全景与 Dual API 设计

在调用模型设计上，`my-coding-agent` 融合了 **Tau 的 Pythonic 异步生成器** 与 **Pi 的极简批处理门面**，提供标准的双接口设计（Dual API）：

```python
class CodingAgent:
    """产品级编码智能体门面。"""

    def __init__(
        self,
        *,
        workspace: str | Path,
        llm: LLM,
        session: Session,
        system_prompt: str | None = None,
        extra_tools: list[Tool] | tuple[Tool, ...] = (),
        permission_gate: PermissionGate | None = None,
        auto_load_mcp: bool = True,
        **kw,
    ):
        ...

    async def run_stream(self, user_input: str) -> AsyncIterator[AgentEvent]:
        """流式事件驱动入口（供 CLI/TUI、打字机输出、实时工具状态消费）。"""
        await self.ensure_mcp_loaded()
        async for event in self.agent.prompt_stream(user_input):
            yield event

    async def run(self, user_input: str) -> str:
        """批处理高阶入口（自动化脚本、CI/CD 跑测、快速单次执行）。"""
        await self.ensure_mcp_loaded()
        return await self.agent.run(user_input)
```

- **`run_stream`**：一等公民流式入口，产出包含 `agent_start`、`message_update`（正文与思考增量）、`tool_execution_start/update/end`、`turn_end`、`agent_end` 等全量结构化生命周期事件；
- **`run`**：上层开箱即用入口，内部消费 `run_stream` 并最终聚合并返回纯文本回复，杜绝调用端编写重复的事件累加样板代码。

---

## 二、系统提示词与 `<project_context>` 自动发现机制

系统提示词由 `build_default_coding_prompt(workspace)` 负责组装（位于 `src/my_coding_agent/prompt.py`），深度注入工业级研发最佳实践与当前工程的实时现状：

```text
                  build_default_coding_prompt(workspace)
                                    │
    ┌───────────────────────────────┼───────────────────────────────┐
    ▼                               ▼                               ▼
【资深研发行为准则】            【工作区上下文注入】            【声明式技能清单】
- 先读后改/最小修改原则          <project_context>               <available_skills>
- 保持编码风格与命名一致性       - Git 分支与状态信息            .agents/skills/ 目录下
- 杜绝占位代码与未确认重构       - 规范文件 (AGENTS.md)          各领域的 SOP 与工程指导
- 边界条件与测试驱动优先         - 架构说明 (README.md)
```

### 1. `<project_context>` 自动化探测与注入

产品层在启动或更新提示词时，会自动对当前工作区执行启发式扫描：

1. **项目规范文件发现**：
   优先读取 `AGENTS.md`、`CLAUDE.md` 或 `.cursorrules`。若存在，将其完整规范块包裹至 `<project_instructions path="...">` 标签中；
2. **项目架构说明发现**：
   读取根目录 `README.md`，提炼项目设计理念与目录布局；
3. **环境与 Git 状态感知**：
   感知当前 Git 分支名称与未提交变更文件列表，赋予模型初始环境感知力；
4. **截断与预算约束**：
   上下文内容自动施加单文件 100KB 上限约束，防止巨型文件挤占模型推理窗口。

### 2. 资深软件工程师核心提示词准则

- **Narrow & Correct**：首选最小化、高精度的微创手术式修改，严禁不加沟通的大范围重构；
- **Preserve Conventions**：严格延续工程现有的缩进、类型注解习惯与命名风格；
- **Verify Always**：任何代码修改必须优先执行针对性自动化测试验证，确保零回归。

---

## 三、五大专职 Hook 接入与安全扩展

`CodingAgent` 紧密协作于框架内核的 `HookRegistry`，支持在 ReAct 循环的关键切片注入业务门禁：

| 拦截点契约 | 触发时机与职责 | 产品层在 CodingAgent 中的落地 |
| :--- | :--- | :--- |
| **`UserInputHook`** | 拦截或改写用户输入文本 | 自动执行 `FileReferenceParser.expand`，提取 `@file` 并注入源码快照 |
| **`AgentStartHook`** | 拦截 Agent 启动并可重写 `system_prompt` | 允许针对特殊安全模式追加防逃逸指令 |
| **`BeforeModelCallHook`** | 在请求发送至 LLM API 前夕触发 | 监控模型上下文尺寸，触发廉价上下文压缩决策 |
| **`ToolCallHook`** | 工具执行前权限校验 | 挂载 `PermissionGate`，针对高危 Shell 命令与文件写操作触发安全审批 |
| **`ToolResultHook`** | 工具执行后对结果进行脱敏或修正 | 统一屏蔽敏感秘钥或将大输出转写为持久化文件摘要 |

---

## 四、业务安全权限门禁 (PermissionGate)

`PermissionGate`（位于 `src/my_coding_agent/permissions.py`）是基于 `ToolCallHook` 实现的无侵入安全审批中间件，能够在不破坏 ReAct 微内核纯函数性的前提下，对任何破坏性行为实施可拦截、可审计的交互审批。

### 1. 四大安全模式 (PermissionMode)

| 模式名称 | 模式标识 | 行为契约与安全等级 |
| :--- | :--- | :--- |
| **审查模式 (默认)** | `review` | 平衡生产力与安全。只读工具与安全 Shell 命令免批放行；所有文件修改（`write`/`edit`）与常规 Shell 命令触发用户确认 |
| **自主模式** | `autonomous` | 全自动静默模式。所有工具调用无感直接放行，适用于无人值守批处理或容器自动化任务 |
| **放行模式** | `yolo` | `autonomous` 的友好别名，CLI 传入 `--mode yolo` 时自动映射为 `autonomous` |
| **严格受限模式** | `strict` | 高安全性只读受限沙箱。即便是只读工具与安全命令也须逐项审批，严禁任何未授权文件写入 |

### 2. 免审批高速通道 (Fast Path)

为防止繁琐的确认打断流畅的研发体验，系统内置了经过实战检验的安全免审批通道：

- **只读工具白名单**：
  ```python
  READONLY_TOOLS = frozenset({"read", "grep", "find"})
  ```
  在非 `strict` 模式下，上述只读操作直接放行，零阻塞。
- **安全 Shell 命令前缀白名单**：
  ```python
  SAFE_BASH_PREFIXES = (
      "git status",
      "git diff",
      "git log",
      "pytest",
      "python -m pytest",
      "uv run",
  )
  ```
  在 `review` 模式下，凡是以只读状态探查或本地测试为目的的命令无需确认，直接执行。

### 3. 交互式审查与差异比对契约 (PermissionRequest)

当检测到非白名单的修改类操作或高危 Shell 指令时，`PermissionGate` 构造强类型审批实体：

```python
@dataclass(frozen=True)
class PermissionRequest:
    action: str  # 工具名称，如 "write", "edit", "bash"
    target: str  # 操作目标文件路径或完整待执行命令
    details: dict[str, Any] = field(default_factory=dict)
    preview: str | None = None  # 变更代码预览或 diff 快照
```

若注册了 `confirm_callback`（如在 TUI 中弹出确认模态框）：
1. 界面呈现操作目标与代码差异预览（针对 `write`/`edit`）；
2. 用户选择批准（`True`）则透明继续执行；
3. 用户选择驳回（`False`）则返回 `HookResult(block=True, reason=f"用户拒绝执行: {tool_name} on {target}")`，ReAct 循环捕获拦截结果，模型能够清晰感知并调整后续行动策略。
