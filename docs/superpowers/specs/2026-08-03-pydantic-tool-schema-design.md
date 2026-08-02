# 设计文档：工具层 pydantic 化 —— 用 pydantic 取代手写 TYPE_MAP

- **日期**：2026-08-03
- **状态**：待实现
- **位置**：`my_agent_core/tools.py`（+ 依赖与相关文档）
- **取代关系**：`2026-08-01-my-agent-framework-design.md` §4.4（手写 `validate_arguments`）、
  §7 测试清单 #1/#6 的相关描述、错误表「装饰器遇到不支持的标注/默认值」行，由本文档取代
- **依赖**：新增 `pydantic>=2.0` 直接依赖（`openai` SDK 本就传递依赖它，无新增传递负担）

## 1. 背景与动机

现状（`tools.py` 第 15~20 行）用一张四行 `TYPE_MAP` 把 Python 类型标注翻译成
JSON Schema 类型名，只支持 `int`/`float`/`str`/`bool` 四种标量，且明确拒绝默认值参数。
当初这么做的理由是「手写 schema 生成与校验保持最简」。

项目澄清（本次）：「不依赖框架」指**不依赖 langchain/langgraph 这类 agent 框架**，
pydantic 这类通用库允许使用。手写映射表的局限（无 list/dict/Optional/嵌套、无默认值、
无校验强转）已构成真实约束，应由 pydantic 接管 schema 生成与参数校验。

**目标**：

- 工具参数类型获得 pydantic 全集表达力（list / dict / Optional / Literal / 嵌套模型等），
  支持默认值与 `Optional`
- schema 生成与参数校验收敛到**同一份 pydantic 模型**，消除两处维护
- 对外 API（`@tool` 装饰器用法、`Tool`、`schemas_for`、`call_tool` 签名）零变化
- `call_tool` 「永不抛异常、错误转字符串喂回模型」的契约不变

## 2. 已确认的决定（澄清记录）

| 问题 | 决定 |
|---|---|
| 对外 API 形态 | 保持 `@tool` 装饰器不变，仍写普通函数 + 类型标注；pydantic 只在内部使用 |
| 参数校验 | 模型传来的参数也用 pydantic 校验 + 类型强转（`"37"` → `37`），与 schema 生成共用同一模型 |
| 默认值 / Optional | 支持。有默认值的参数在 schema 中标为可选；原「拒绝默认值」限制废除 |
| 实现路线 | 方案 A：`create_model` 从函数签名动态建模，一个 model 两用（schema + 校验） |
| 旧文档 | 同步修订到位：CLAUDE.md、README、框架设计文档冲突处一并改 |

被否决的备选：显式 BaseModel 定义参数（样板代码多，违背最小风格）；
`TypeAdapter` + 动态 TypedDict（默认值无处安放）；
`validate_call` + 独立 schema（两套机制各管各的，又回到两处维护）。

## 3. 组件改动（tools.py）

### 3.1 删除

- `TYPE_MAP` 整张映射表
- 装饰器里手写的参数遍历校验（现第 43~57 行）

### 3.2 `Tool` dataclass 新增字段

```python
@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]   # 由 pydantic 模型生成的 JSON schema
    func: Callable[..., Any]
    model: type[BaseModel]       # ← 新增：参数模型，schema 生成与运行期校验共用
```

### 3.3 `@tool` 装饰器新逻辑

```python
def tool(func: Callable[..., Any]) -> Tool:
    hints = get_type_hints(func)
    fields: dict[str, Any] = {}
    for param_name, param in inspect.signature(func).parameters.items():
        # fail-loud 三拒绝（均在装饰时/import 阶段抛 TypeError）：
        #   ① 无类型标注的参数
        #   ② *args（VAR_POSITIONAL）
        #   ③ **kwargs（VAR_KEYWORD）
        default = ... if param.default is inspect.Parameter.empty else param.default
        fields[param_name] = (hints[param_name], default)

    try:
        model = create_model(
            f"{func.__name__}_Args",
            __config__=ConfigDict(extra="forbid"),   # 多余参数 → 校验错误
            **fields,
        )
        schema = _clean_schema(model.model_json_schema())
    except Exception as exc:   # 无法生成 schema 的类型 → 装饰时明确失败
        raise TypeError(f"tool '{func.__name__}': cannot build schema: {exc}") from exc

    return Tool(
        name=func.__name__,
        description=inspect.getdoc(func) or "",
        parameters=schema,
        func=func,
        model=model,
    )
```

要点：

- **`extra="forbid"`**：让 pydantic 模型天然覆盖原手写校验器三规则中的「多余参数」；
  「缺必填」「类型不符」是 pydantic 本职。
- **bool/int 区分**（2026-08-03 实现期修正）：实测 pydantic v2 lax 模式**接受**
  bool→int/float（与最初「v2 默认严格区分」的假设相反），故 `@tool` 对裸 `int`/
  `float` 标注包一层 `BeforeValidator` 显式拒绝 bool（复合标注如 `Optional[int]`
  不递归处理，属已知边界）；JSON schema 不受影响。
- **`_clean_schema`**：约 5 行的递归函数，删除 pydantic 输出中各级 `title` 键
  （模型名与字段名的 title 对模型是纯噪音），其余结构（`$defs`、`anyOf`、
  `default` 等）原样保留。
- **零参数工具**：`create_model` 无字段调用合法，schema 为
  `{"type": "object", "properties": {}}`（pydantic 不输出空 `required`，
  与旧版 `"required": []` 语义等价）。
- **默认值**：`(ann, default)` 使 pydantic 自动把该参数移出 `required` 并写入
  `"default"` 键；`Optional[X]` 无默认值时仍必填（允许传 null），`= None` 时可选。

### 3.4 `call_tool` 新逻辑

三段容错结构原样保留，中间「裸调 `func(**args)`」换成「先过 pydantic 校验」：

```python
def call_tool(tool_call: Any, tools_by_name: dict[str, Tool]) -> str:
    # ① 未知工具名 → 描述性字符串（不变）
    # ② json.loads 失败 → 描述性字符串（不变）
    try:
        validated = target.model.model_validate(args)   # 校验 + 类型强转
    except ValidationError as exc:
        return _format_validation_error(name, exc)      # ③ 逐条错误消息
    try:
        result = target.func(**validated.model_dump())
    except Exception as exc:                            # ④ 工具异常 → 字符串（不变）
        return f"Error executing tool '{name}': {exc}"
    return str(result)
```

`schemas_for` 一行不改（只是 `Tool.parameters` 的内容来源变了）。

## 4. 校验错误消息格式

沿用框架设计文档 §4.4 规划的 pi 风格逐条列出，**消息文本直接用 pydantic 原始
`err['msg']`**，不维护自己的错误类型映射表（那等于再造一个 TYPE_MAP）：

```
Validation failed for tool "get_weather":
  - city: Field required
  - retries: Input should be a valid integer
  - verbose: Extra inputs are not permitted
```

`_format_validation_error` 只做两件事：遍历 `exc.errors()`，取 `loc` 首段作字段名、
`msg` 作描述，拼成上式。字段定位只取 `loc[0]`（顶层参数名），嵌套内部的深层路径
不展开——学习项目保持消息简单直接。

## 5. 数据流（改动后全景）

```
装饰期（import 时）：
  @tool func ──create_model──▶ Tool.model ──model_json_schema──▶ Tool.parameters
                                  │                  （删 title 后存入）
                                  ▼
                            fail-loud：无标注 / *args / **kwargs /
                            无法建模的类型 → TypeError

运行期（每轮循环）：
  schemas_for(tools) ──▶ 请求 tools 字段 ──▶ 模型
  模型 ──▶ tool_call{name, arguments(JSON字符串)}
        ──▶ json.loads ──▶ model_validate（校验+强转，失败→逐条消息）
        ──▶ func(**validated.model_dump()) ──▶ str(result) 写回 messages
```

## 6. 文档修订清单（随实现同步完成）

| 文件 | 修订点 |
|---|---|
| `pyproject.toml` | `dependencies` 加 `pydantic>=2.0`，`uv sync` 验证 |
| `CLAUDE.md` | 依赖表述加 pydantic（「no agent-framework dependency」保留）；工具参数规则改为「pydantic 全集 + 默认值；无标注 / `*args` / `**kwargs` 装饰时拒绝」 |
| `my_agent_core/README.md` | 开头依赖表述；「所有协议细节全部手写」改为「schema 生成与参数校验委托 pydantic，调度、容错、协议解析仍手写」；第 92 行类型列表；「添加新工具」示例加一个带默认值/列表参数的工具 |
| `docs/.../2026-08-01-my-agent-framework-design.md` | §4.4 改为「复用 `Tool.model` 校验 + 逐条错误格式化」；错误表对应行更新；§7 #1/#6 用例描述更新 |
| `my_agent_core/README.md` v1 路线 | 阶段 2.2「手写 validate_arguments」改为「接入 `Tool.model`，复用 tools.py 的 `_format_validation_error`」 |

路线图定位：本改动是**阶段 1 开始前的独立改造**，不属于七阶段；阶段 1-2「纯新增、
旧代码不动」的原则不受影响（阶段 2.2 反而因校验逻辑前移而变轻）。

## 7. 测试清单（测试先行，全部离线、无需 API key）

新建 `tests/test_tools.py`（tests/ 首个 `.py` 文件）。

**装饰期（schema 生成）**

1. 基本类型 `int/str/float/bool` → schema 类型名为 integer/string/number/boolean
2. 零参数工具 → `{"type": "object", "properties": {}}`，无 `required`
3. 默认值参数 → 不进 `required`，schema 含 `default`
4. `Optional[int]`（无默认值）→ anyOf 形式且仍必填；`Optional[int] = None` → 可选
5. 复杂类型 `list[str]`、`dict[str, int]`、`Literal`、嵌套 `BaseModel` → schema 正确
6. schema 各级均无 `title` 键
7. 无类型标注 → 装饰时抛 `TypeError`；`*args` / `**kwargs` → 抛 `TypeError`
8. `name` / `description` 取自函数名 / docstring

**运行期（call_tool）**

9. 正常调用返回 `str(result)`
10. 类型强转：`"37"` → `37` 生效
11. 缺必填 / 类型不符（`"abc"` → int）/ 多余参数 → `Validation failed for tool "X":`
    逐条消息
12. bool/int 严格区分：int 参数传 `true` → 校验失败（钉死 pydantic v2 行为）
13. 默认值参数不传 → 函数收到默认值
14. 回归：未知工具名、非法 JSON、工具自身异常 → 字符串行为与现状一致；
    `call_tool` 永不抛

**集成**

15. `schemas_for` 输出形状回归不变
16. 真实运行 `uv run python -m my_agent_core.main`：三个问题答案符合预期
    （703 / 当前时间 / 两城市天气）

## 8. 非目标（明确不做）

- 不改 `agent.py` 的 ReAct 循环与消息状态设计
- 不支持 `*args` / `**kwargs` 形式的工具参数（明确拒绝）
- 不做自定义错误文案映射（沿用 pydantic 原始消息）
- 不做 schema 的 `strict` 模式 / OpenAI `strict: true` 适配（兼容端点支持不一，
  留待真实需要时再议）
- 不动 `main.py` 的三个 demo 工具（验证回归即可；README 示例另行更新）
