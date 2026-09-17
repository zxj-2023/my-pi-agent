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
| **`ToolCallHook`** | 工具执行前权限校验 | 挂载 `PermissionGate`，针对高危 Shell 命令（如 `rm -rf`）弹窗确认 |
| **`ToolResultHook`** | 工具执行后对结果进行脱敏或修正 | 统一屏蔽敏感秘钥或将大输出转写为持久化文件摘要 |
