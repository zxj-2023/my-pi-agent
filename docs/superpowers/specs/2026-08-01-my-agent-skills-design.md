# 设计文档：my_agent_core skill 机制 —— 发现、按需加载、显式调用

- **日期**：2026-08-01
- **状态**：待实现
- **位置**：`my_agent_core/`，依赖框架文档（`@tool` / `Agent` / system prompt 组装）
- **设计参考**：`D:/code/python/pi/packages/agent/src/harness/skills.ts`、
  `packages/coding-agent/src/core/skills.ts`（pi 的两套 skill 实现）

## 1. 背景与目标

调查结论（pi 的 skill 机制）：skill 是**按需注入的指令集**，机制只有三样——

1. **发现**：递归扫描目录，`SKILL.md` = skill 根（不再下钻）；frontmatter 提供
   `name` / `description` / `disable-model-invocation`；校验按 agentskills.io
   规范（name：小写 a-z0-9-、≤64、须与父目录名一致；description：必填、≤1024）；
   容错——警告不阻塞，缺 description 才跳过；
2. **列清单（渐进式披露）**：`formatSkillsForPrompt` 往 system prompt 注入的
   **只有 name + description 的 XML 清单**，并指示模型"任务匹配时用 read 工具
   自己加载 skill 文件"——**没有专门的 skill 工具**，启动时只花小 token，
   正文用到才载入；
3. **显式调用**：`harness.invokeSkill(name, instructions)` 把正文包成
   `<skill name location>…正文…</skill>` + 附言，当成一轮 prompt 执行。

循环与 Agent 核心不知道 skill 的存在——skill 只经 system prompt 清单与
（按需读取 / 显式注入）两个通道进入模型视野。

**用户决定**：做全套四件——发现加载、system prompt 清单、`read_skill` 工具
（模型自主按需加载）、`invoke_skill` 显式调用。

### 1.1 已确认的需求（澄清记录）

| 问题 | 决定 |
|---|---|
| 范围 | 四件套全做（`read_skill` 是灵魂：没有它就退化成静态 prompt 填塞，无 token 经济学） |
| skill 文件格式 | agentskills.io 规范（SKILL.md + frontmatter），生态文件可直接复用 |
| frontmatter 解析 | 手写极简解析（`key: value` 行，只认三个键），**不引 PyYAML 依赖** |
| 动态刷新 | 不做——skills 在 `Agent` 初始化时固定；配置变更新会话生效 |

### 1.2 非目标（YAGNI）

- ignore 文件（`.gitignore`/`.ignore`）、符号链接去重、user/project 分层作用域
  （v1 只有"目录列表"一个来源维度）
- 按 turn 动态刷新 skill 资源（pi 的 `turnState.resources`）
- skill 附带文件（目录内辅助资源 + 正文路径引用）——需要文件工具配套，入 §9
- slash 命令 / TUI 入口（显式调用就是 `invoke_skill` API）

## 2. 架构

```
skills.py —— 数据模型 + 发现 + 格式化
  load_skills(dirs) → (skills, diagnostics)
  format_skills_for_prompt(skills) → XML 清单块
  format_skill_invocation(skill, instructions) → <skill> 包装文本
  read_skill_tool(skills) → Tool（read_skill(name) 单工具）
        │
Agent(..., skill_dirs=[...]) —— 初始化时组装
  ① load_skills → ② system = 用户的 system_prompt + 清单块
  ③ tools = [read_skill] + 用户 tools → ④ skills/诊断 公开可读
Agent.invoke_skill(name, instructions) —— 显式：包装文本当 user 消息跑一轮
```

### 2.1 与 pi 的角色对应

| my_agent_core | pi | 取舍说明 |
|---|---|---|
| `Skill` dataclass | `Skill` 接口（harness/types.ts:64） | 同字段；砍 `baseDir`/`sourceInfo`（无分层作用域） |
| `load_skills` 发现规则 | `loadSkills` / `loadSkillsFromDir` | 同：SKILL.md = skill 根不下钻、根级 `.md`、递归子目录。异：无 ignore 文件、无符号链接处理、无 user/project 分层 |
| 手写 frontmatter 解析 | yaml 库 `parseFrontmatter` | 只认 `name`/`description`/`disable-model-invocation` 三个 `key: value` 行；其余键忽略（向前兼容） |
| 校验规则 | 规范校验（validateName/validateDescription） | 同规则同态度：name 不合规 → 警告但加载；description 缺失 → 跳过；冲突 → 先到先得 + collision 诊断 |
| `format_skills_for_prompt` | `formatSkillsForPrompt`（skills.ts:335） | XML 清单同款；**差异**：pi 列 `location`（文件路径，模型按路径 read），本项目列 name（`read_skill(name)` 按名取），不暴露路径 |
| `read_skill` 工具 | 无对应物（pi 复用通用文件 read 工具） | my_agent_core v1 无文件工具 → 按名单工具：更简、无路径遍历问题 |
| `format_skill_invocation` | `formatSkillInvocation`（harness/skills.ts:38） | 同款 `<skill name="…" location="…">` 包装 + 附言 |
| `Agent.invoke_skill` | `harness.invokeSkill`（agent-harness.ts:713） | 同：包装成一轮 prompt 执行；含 `disable-model-invocation` 的 skill 也可显式调 |
| 初始化时固定 | `turnState.resources` 可每 turn 刷新 | 简化：不做动态刷新（§2.2-4） |

### 2.2 关键设计决策

1. **渐进式披露是灵魂**。system prompt 只进清单（每 skill 几十 token），
   正文经 `read_skill` 按需取——与 context 管理设计直接协同：初始上下文小，
   压缩压力低。
2. **`read_skill` 按名索引，不按路径**。无路径遍历安全问题，schema 只有一个
   `name` 参数；正文取自**加载时的内存对象**而非重读磁盘——会话内所用即所加载，
   行为可预期（也利于测试断言）。
3. **frontmatter 手写解析**。spec 常用字段就三个，行级 `key: value` 足够；
   值两端的引号剥掉；未知键忽略。零依赖，符合项目一贯风格。
4. **清单拼在 system prompt 尾部，整体随 session 持久化**。框架组装
   `system = 用户部分 + 清单块`，这份组装结果是 transcript 的 system 消息。
   按 session 文档决策 3（恢复时文件为准）：**skill 配置变更需新会话生效**。
   与 pi 的 per-turn 刷新刻意不同，v1 明确不做。
5. **诊断容错**。一切加载问题（目录不存在、读失败、frontmatter 坏、name 不合规、
   冲突）→ 诊断列表，不抛不阻塞启动（pi 立场）。
6. **`disable-model-invocation`**：标记的 skill 不进清单（模型看不见），
   但 `invoke_skill` 仍可显式调用（pi 同款语义）。

## 3. skill 文件格式（面向使用者）

```
my_skills/                     # 传给 Agent(skill_dirs=["my_skills"])
├── code-review/
│   └── SKILL.md               # 目录含 SKILL.md → 一个 skill，name 默认取目录名
└── quick-notes.md             # 根级 .md → 一个 skill，name 默认取文件名（去 .md）
```

```markdown
---
name: code-review                          # 可省略：SKILL.md 取目录名，根 .md 取文件名
description: Use when reviewing code ...   # 必填，模型靠它判断何时加载
disable-model-invocation: false            # 可省略，默认 false
---
（skill 正文：模型 read_skill 后看到的完整指令）
```

与 pi 的一个小差异（改进）：根级 `.md` 的 name fallback 取**文件名**（pi 取
父目录名，导致多个根 .md 无 frontmatter name 时必然冲突）。

## 4. 组件接口

### 4.1 `skills.py`（新增，~150 行）

```python
@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    content: str                     # frontmatter 之下的正文
    file_path: Path                  # 诊断/调试用；不暴露给模型
    disable_model_invocation: bool = False

@dataclass(frozen=True)
class SkillDiagnostic:
    level: str                       # "warning" | "collision"
    message: str
    path: str

def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """手写解析：首部 ---\\n key: value 行 \\n--- → (字段 dict, body)。
    无 frontmatter → ({}, 全文)。值剥两端引号；未知键保留但不使用。"""

def load_skills(dirs: list[str | Path]) -> tuple[list[Skill], list[SkillDiagnostic]]:
    """发现 + 解析 + 校验（规则见 §2.1/§3）。容错：警告不阻塞；
    缺 description → 跳过该 skill；name 冲突 → 先到先得 + collision 诊断。
    隐藏目录（. 开头）跳过。目录不存在 → warning 诊断。"""

def format_skills_for_prompt(skills: list[Skill]) -> str:
    """visible（非 disable_model_invocation）skills → XML 清单块；
    空 → 空串。含引导语：任务匹配 description 时用 read_skill 工具按名加载。"""

def format_skill_invocation(skill: Skill, instructions: str = "") -> str:
    """'<skill name="…" location="…">\\n{content}\\n</skill>' + 附言（同 pi）。"""

def read_skill_tool(skills: list[Skill]) -> Tool:
    """生成 read_skill(name: str) -> str 工具（经 @tool 机制）：
    命中（含 disable_model_invocation 的）→ 返回正文；
    未命中 → 错误字符串 + 可用名字清单（走标准工具错误路径喂回模型）。"""
```

### 4.2 `Agent` 集成（agent.py 修改）

```python
class Agent:
    def __init__(self, ..., skill_dirs: list[str | Path] | None = None):  # ← 新增
        """skill_dirs=None → 无 skill 机制（向后兼容，既有测试不受影响）。
        非 None → load_skills(skill_dirs)：
          system = (system_prompt or "") + format_skills_for_prompt(skills)
          tools  = [read_skill_tool(skills)] + 用户 tools
          self.skills / self.skill_diagnostics 公开可读。
        注意：system 组装结果随 session 持久化（决策 4）。"""

    skills: list[Skill]                  # 公开可读（无 skill_dirs 时 []）
    skill_diagnostics: list[SkillDiagnostic]

    def invoke_skill(self, name: str, instructions: str = "") -> str | None:
        """显式调用：按名查 skills（含 disable_model_invocation），
        format_skill_invocation 包装 → self.run(包装文本) 跑一轮。
        未知名字 → ValueError（列可用名字）。"""
```

### 4.3 与既有机制的交互

- **session**：system 消息（含清单块）创建时落盘；恢复时文件为准 →
  skill 配置变更新会话生效（决策 4）
- **context 管理**：清单块随 system 永驻（压缩不动 system）；`read_skill`
  返回的正文是普通 tool 消息，正常参与压缩
- **事件**：无新事件——`read_skill` 是普通工具，`ToolCallStart/End` 天然覆盖
- **中间件 / max_iterations**：天然适用（read_skill 走六段管道，可被
  `before_tool` 拦截、`after_tool` 改写——比如截断超长正文）

## 5. 数据流

```
Agent(skill_dirs=["my_skills"]) 初始化
  load_skills → [Skill(code-review), Skill(quick-notes)]
  system = "You are a helpful assistant.\n\n...<available_skills>
              <skill><name>code-review</name><description>Use when...</description></skill>
              ...</available_skills>"
        │
agent.run("Review this function for bugs: ...")
  模型看到清单，判断匹配 code-review 的 description
        ↓ 发起工具调用
  read_skill("code-review") → 返回 SKILL.md 正文（审查清单指令）
        ↓ tool 消息写回 transcript
  模型按正文指令继续（可能再调别的工具）→ 最终给出结构化审查结果

显式路径：
agent.invoke_skill("code-review", "重点看并发安全")
  → run('<skill name="code-review" ...>正文</skill>\n\n重点看并发安全')
```

## 6. 错误处理

| 故障 | 位置 | 处理 |
|---|---|---|
| skill 目录不存在 / 读失败 / frontmatter 坏 | `load_skills` | warning 诊断，跳过该条目，不阻塞 |
| description 缺失 | `load_skills` | 跳过该 skill（+ warning），pi 同款 |
| name 不合规（正则 / 长度） | `load_skills` | warning 但照常加载（pi 同款） |
| name 冲突 | `load_skills` | 先到先得 + collision 诊断（记胜者与败者路径） |
| `read_skill` 名字未命中 | 工具错误路径 | 错误字符串 + 可用名字清单，模型可自我纠正 |
| `invoke_skill` 名字未知 | `Agent` | `ValueError`（列可用名字）——显式 API 失败要响 |
| `skill_dirs=[]` | `Agent` | 无清单块、无 read_skill 工具（等价未启用） |

## 7. 测试与验收标准

### 7.1 离线测试（`tests/test_skills.py` + Agent 集成用例，FakeLLM 驱动）

| # | 测试 | 验证点 |
|---|---|---|
| 1 | `parse_frontmatter` | 有/无 frontmatter；引号剥离；body trim；未知键保留 |
| 2 | 发现规则 | 目录 skill（SKILL.md）+ 根级 .md + 递归子目录；含 SKILL.md 的目录不下钻（其子目录的 SKILL.md 不加载） |
| 3 | name 推导 | frontmatter 优先；SKILL.md → 目录名；根 .md → 文件名（去 .md） |
| 4 | 校验与容错 | 缺 description → 跳过；name 不合规 → 警告且加载；冲突 → 先到先得 + collision 诊断；坏目录 → warning |
| 5 | `disable-model-invocation` | 不进 `format_skills_for_prompt` 清单；`invoke_skill` 仍可调用 |
| 6 | `format_skills_for_prompt` | XML 结构逐行正确；空列表 → 空串 |
| 7 | `read_skill` 工具 | 命中返回正文（内存对象一致）；未命中 → 错误串含可用名字 |
| 8 | Agent 组装 | `skill_dirs` → system 含清单块、tools 首位是 read_skill、`agent.skills` 正确；`skill_dirs=None` → system/tools 无变化（既有测试全绿） |
| 9 | 端到端自主加载 | FakeLLM：第一轮发 `read_skill("code-review")`、第二轮最终回答 → transcript 含正文 tool 消息、回答如预期 |
| 10 | `invoke_skill` | 追加的 user 消息 = `<skill …>正文</skill>` + 附言；未知名字 → `ValueError` |
| 11 | 诊断暴露 | 构造含坏 skill 的目录 → `agent.skill_diagnostics` 有对应记录 |

### 7.2 验收标准（步骤 → 验证方式）

```
实现 skills.py（模型+发现+格式化+read_skill_tool） → #1-#7 通过
Agent 集成（skill_dirs 组装）                      → #8、#9、#11 通过
invoke_skill                                       → #10 通过
全量                                               → uv run pytest -q 全绿（三份既有设计测试不回归）
真实验证（需 .env）                                → 写两个 SKILL.md（其一 disable-model-invocation），
                                                   问一个匹配 description 的问题 → 模型自主 read_skill
                                                   后按正文指令作答；invoke_skill 显式调用隐藏 skill 成功
```

## 8. 与其他设计文档的联动

- **框架文档**（同步修订）：`system_prompt` 参数语义澄清——启用 `skill_dirs`
  时框架在其尾部追加清单块（§4.5 备注 + 修订记录）；无其他契约变化
  （`read_skill` 只是普通 `@tool` 工具，`invoke_skill` 是 Agent 新方法）
- **session 文档**：无改动；交互关系见本文档 §2.2-4（system 整体持久化，
  恢复时文件为准 → skill 配置变更新会话生效）
- **context 文档**：无改动（清单在 system 永驻；正文是普通 tool 消息）

## 9. 演进路线（pi 对应物）

1. **skill 附带文件**：skill 目录内的辅助资源，正文以相对路径引用
   （pi 的 `References are relative to …` 机制）——依赖文件工具
2. **分层作用域 + ignore 文件**：user 级 / project 级目录 + `.gitignore`
   语义（pi 完整发现逻辑）
3. **动态刷新**：每 turn 或文件变更后重载（pi `turnState.resources`）
4. **REPL `/skill` 命令**：交互式显式调用入口（依赖交互层）

## 10. 修订记录

- 2026-08-01：初版。用户决定：四件套全做（发现 + 清单 + read_skill 工具 +
  invoke_skill）；frontmatter 手写解析不引依赖；agentskills.io 格式兼容；
  不做动态刷新。关键决策：按名索引（非路径）、system 整体持久化（skill 配置
  变更新会话生效）、诊断容错不阻塞。
