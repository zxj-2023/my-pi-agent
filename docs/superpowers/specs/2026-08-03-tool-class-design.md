# 设计文档：工具层重构为类模式 —— Tool 类 + ToolResult + ToolRegistry

- **日期**：2026-08-03
- **状态**：待实现
- **位置**：`my_agent_core/tools.py`（重写）+ `my_agent_core/registry.py`（新增）+ `my_agent_core/agent.py`（改造）
- **前置**：`2026-08-03-pydantic-tool-schema-design.md`（pydantic 化已完成，本规格在其之上重构结构）
- **设计参考**：pig-mono 旧版 `pig_agent_core/tools.py`（Tool 类 + tool 装饰器）与 `registry.py`（简单版 ToolRegistry）——注意：pig-mono 新版 `tools/` 包已放弃 Tool 类、改用 handler/schema 分离注册，本规格**不学**新版（那是生产级演进，YAGNI）

## 1. 背景与动机

现状 `tools.py` 是「dataclass `Tool` + 自由函数」结构：`tool()` 装饰器、`schemas_for`、`call_tool`、`_clean_schema`、`_format_validation_error`。pydantic 化后 schema 生成与校验已收敛到 `Tool.model`，但结构仍是数据/行为分离。

用户决定重构为 pig-mono 旧版的**类模式**（自包含对象），动机：为后续阶段做准备（阶段 2 `before_tool` 中间件、阶段 7 动态工具、coding agent 层工具集）。

**目标**：

- `Tool` 改为类：自包含 `to_openai_schema()` / `execute()` / `__call__`，对外 API 更接近对象打包风格
- 独立 `ToolRegistry`（新增 `registry.py`）：持有工具集合、查表、批量生成 schema、执行——对应路线图阶段 7 动态工具（`register_tool`/`unregister_tool`）
- 新增 `ToolResult`：结构化结果（ok/data/error），对应路线图「工具结果结构化」项
- 保留已验证的决策：pydantic 动态建模、宽松 bool/int、`extra="forbid"`、fail-loud、永不抛
- 删除 `schemas_for` / `call_tool` 两个自由函数（彻底更换，agent.py 改用新 API）

## 2. 已确认的决定（澄清记录）

| 问题 | 决定 |
|---|---|
| 重构范围 | 核心类化：Tool 类（__init__/to_openai_schema/execute/__call__）+ tool() 装饰器支持 name/description/params_model 覆盖。**不含**描述符（__get__/__set_name__）与 async——等 coding agent 层需要再加 |
| 旧自由函数 | 彻底更换：`schemas_for` / `call_tool` 删除，agent.py 改用新 API |
| 错误语义 | 保持永不抛：`Tool.execute` 错误转 `ToolResult(ok=False, error=...)`，不抛异常 |
| 返回值 | `Tool.execute` 返回 `ToolResult` 对象（ok/data/error），而非 str |
| 分发职责 | 选项 B：`ToolRegistry.execute(tool_call)` 收**完整 tool_call**，内部 `json.loads` + 查表 + 执行；agent 循环只做「调用 + 配对写回」，最干净 |
| Registry 位置 | 独立 `my_agent_core/registry.py`，`agent.py` 创建并使用它（替代手写 `tools_by_name` 字典） |
| 参考取舍 | 学 pig-mono **旧版**形态（Tool 类 + 简单 registry）；**不学**新版 tools/ 包（handler/schema 分离、懒加载、超时、重试、fallback、确认门、审计、指标——全为生产级，YAGNI） |

## 3. 组件改动

### 3.1 `my_agent_core/tools.py`（重写）

**删除**：`schemas_for`、`call_tool`、`_format_validation_error`（自由函数）——`_format_validation_error` 改为模块级私有函数（只被 `Tool.execute` 用，保留可测试性）。

**`Tool` 类**（core 类化）：

```python
class Tool:
    """一个可被模型调用的工具：函数本体 + 参数模型 + 协议转换。"""

    def __init__(self, func, *, name=None, description=None, params_model=None):
        self.func = func
        self.name = name or func.__name__
        self.description = description or (inspect.getdoc(func) or "")
        self.params_model = params_model or self._create_params_model(func)

    def _create_params_model(self, func) -> type[BaseModel]:
        # 从签名动态建模（现逻辑原样搬入），含 fail-loud 三拒绝与 _clean_schema
        ...

    def to_openai_schema(self) -> dict[str, Any]:
        # 单个工具 → OpenAI tools 参数（原 schemas_for 的单元素逻辑）
        return {"type": "function", "function": {
            "name": self.name,
            "description": self.description,
            "parameters": self.params_model.model_json_schema(),
        }}

    def execute(self, args: dict) -> ToolResult:
        # 校验 + 执行，永不抛（错误全部转 ToolResult）
        try:
            validated = self.params_model.model_validate(args)
        except ValidationError as exc:
            return ToolResult(ok=False, error=_format_validation_error(exc))
        try:
            result = self.func(**validated.model_dump())
        except Exception as exc:
            return ToolResult(ok=False, error=f"Error executing tool '{self.name}': {exc}")
        return ToolResult(ok=True, data=result)

    def __call__(self, *args, **kwargs):
        return self.func(*args, **kwargs)
```

**`tool()` 装饰器**：支持 `@tool` 与 `@tool(name=..., description=..., params_model=...)` 两种用法（pig-mono 的 `if func is None` 工厂模式）：

```python
def tool(func=None, *, name=None, description=None, params_model=None):
    def decorator(f):
        return Tool(func=f, name=name, description=description, params_model=params_model)
    if func is None:
        return decorator
    return decorator(func)
```

**保留**：`_clean_schema`（递归删 title/additionalProperties）、`_format_validation_error`（改为模块级私有）。
**不保留**：`_NUMERIC_GUARDS` 及 bool/int 守卫（宽松 bool/int 决策已定，见 `2026-08-03-pydantic-tool-schema-design.md` §3.3）。

### 3.2 `my_agent_core/registry.py`（新增）

```python
@dataclass
class ToolResult:
    """工具执行结果：成功/失败 + 数据或错误消息。"""
    ok: bool
    data: Any = None
    error: str | None = None

    def serialize(self) -> str:
        """转成写入 messages 的字符串。失败时返回错误文本。"""
        if self.ok:
            return str(self.data)
        return self.error or "Unknown error"


class ToolRegistry:
    """工具注册表：持有工具集合，按名字查表与执行。"""

    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def get_schemas(self) -> list[dict[str, Any]]:
        return [t.to_openai_schema() for t in self._tools.values()]

    def execute(self, tool_call: Any) -> ToolResult:
        """收完整 tool_call（选项 B）：内部解析 JSON + 查表 + 执行，永不抛。"""
        name = tool_call.function.name
        try:
            args = json.loads(tool_call.function.arguments)
        except (json.JSONDecodeError, TypeError):
            return ToolResult(ok=False, error=f"Invalid JSON arguments for tool '{name}'")
        target = self._tools.get(name)
        if target is None:
            available = ", ".join(sorted(self._tools))
            return ToolResult(ok=False, error=f"Unknown tool '{name}'. Available: {available}")
        return target.execute(args)
```

### 3.3 `my_agent_core/agent.py`（改造）

- 创建 `ToolRegistry`，`register` 全部工具（替代 `{t.name: t for t in tools}`）
- `schemas = registry.get_schemas()`（替代 `schemas_for(tools)`）
- 循环里 `result = registry.execute(tc)`，`messages.append({"role": "tool", "tool_call_id": tc.id, "content": result.serialize()})`（替代 `call_tool` + 无条件写回）

### 3.4 `main.py`（不动）

`@tool` 用法不变，回归验证即可。

## 4. 错误处理（三层，永不抛）

| 层 | 错误 | 处理 |
|---|---|---|
| `Tool.execute` | 校验失败（缺必填/类型不符/多余参数） | `ToolResult(ok=False, error=逐条消息)` |
| `Tool.execute` | 工具函数自身异常 | `ToolResult(ok=False, error="Error executing tool 'X': ...")` |
| `ToolRegistry.execute` | 坏 JSON | `ToolResult(ok=False, error="Invalid JSON arguments for tool 'X'")` |
| `ToolRegistry.execute` | 未知工具名 | `ToolResult(ok=False, error="Unknown tool 'X'. Available: ...")` |
| `agent.py` | 全部 | 无脑 `result.serialize()` 写回，不分支 |

错误消息格式沿用 pi 风格（`Validation failed for tool "X":` + 逐条），消息用 pydantic 原文。

## 5. 数据流（改动后全景）

```
装饰期：
  @tool(func) → Tool 类（_create_params_model 动态建模 → self.params_model）
             → 默认值/覆盖 name/description/params_model

运行期：
  registry = ToolRegistry(); registry.register(t)...   # main/agent 注册
  schemas = registry.get_schemas()  → 请求 tools 字段  → 模型
  模型 → tool_call{name, arguments(JSON字符串)}
       → registry.execute(tool_call)      # 收 protocol 对象
           → json.loads → 查表 → Tool.execute(args dict)
           → 校验+强转 → func(**validated) → ToolResult(ok/data/error)
       → result.serialize() → 写回 messages（role:"tool" 配对 tool_call_id）
```

## 6. 文档修订清单

| 文件 | 修订点 |
|---|---|
| `CLAUDE.md` | architecture 描述：tools.py（Tool 类 + tool 装饰器）改；新增 registry.py（ToolRegistry + ToolResult）；agent.py 用 registry |
| `my_agent_core/README.md` | 项目结构加 registry.py；设计取舍/原理描述更新；「添加新工具」示例不变（@tool 用法兼容） |
| `docs/.../2026-08-01-my-agent-framework-design.md` | §4.4 替换文本中 `call_tool` 引用 → `registry.execute`；`execute_one` 管道描述更新 |
| 本规格 | 新文档，取代 pydantic 规格中关于结构的部分（pydantic 规格继续有效，涉及 schema 生成与校验细节） |

## 7. 测试清单（测试先行，全部离线）

**`tests/test_tools.py` 迁移（现有 20 个）**：
- schema 生成 8 个（#1-#8）：`f.parameters` → `f.to_openai_schema()["function"]["parameters"]`
- `schemas_for` 形状测试 → `registry.get_schemas()`
- `call_tool` 系列 → `registry.execute(tool_call)`（`make_tool_call` 不变）
- 新增：`name`/`description` 覆盖、`params_model` 覆盖、`__call__` 直接调用、`@tool(name=...)` 工厂用法

**`tests/test_registry.py`（新增）**：
- `register`/`get`/`unregister`/重复注册覆盖
- `get_schemas` 形状
- `execute`：坏 JSON、未知工具、成功、强转、缺必填、默认值、工具异常（回归）
- `ToolResult.serialize`：成功/失败

**集成**：
- `uv run python -m pytest -q` 全绿
- 真实运行 `uv run python -m my_agent_core.main`：703 / 当前时间 / 两城市天气

## 8. 非目标（明确不做）

- 描述符绑定（`__get__`/`__set_name__`）、async `aexecute`——等 coding agent 层需要再加
- 懒加载/超时/重试/fallback/确认门/审计/指标/URL 校验——生产级，不做
- `ToolResult.serialize` 的结构感知截断（pig-mono `base.py` 的 4000 字符 shrink）——等 context 管理阶段需要再加
- `main.py` 不动