# Skills 技能机制设计规范 (`my_agent_core.skills`)

- **定位**：声明式 Agent 技能发现与渐进式披露管理引擎 (`packages/my-agent-core/src/my_agent_core/skills.py`)
- **核心类**：`Skill`, `SkillManager`
- **关键 API**：`get(name)`, `list()`, `format_prompt()`, `format_invocation(name, instructions)`

---

## 一、架构设计与定位

Skills 机制为 Agent 提供了声明式加载特定领域操作规范（SOP）的能力。
`my-agent-core` 的 Skills 系统严格贯彻 **渐进式披露（Progressive Disclosure）** 的 Token 经济学：

- **初始化阶段**：只把极简的技能名和简介注入 System Prompt（0 工具调用，单技能仅占几十 Token）；
- **执行阶段**：由宿主或用户通过 `invoke_skill` 显式将操作正文装载进入上下文。

```text
               .agents/skills/ (技能根目录)
               ├── code-review/
               │   └── SKILL.md  (YAML Frontmatter + 操作指令正文)
               └── git-commit/
                   └── SKILL.md
                         │
                         ▼
                   SkillManager
                         │
         ┌───────────────┴───────────────┐
         ▼                               ▼
  【阶段 1: 启动清单注入】         【阶段 2: 显式触发装载】
  format_prompt()                  format_invocation("code-review")
  生成 <available_skills> 清单块   包装 <skill name="code-review">正文</skill>
  注入首条 System Message          作为一条 user 消息注入模型上下文
```

---

## 二、核心类与机制

### 1. `Skill` 数据实体

```python
@dataclass
class Skill:
    name: str           # 技能标识符 (目录名或 meta.name)
    description: str    # 技能简介 (用于模型初筛判断)
    content: str        # 完整的 Markdown 操作正文
    file_path: Path     # 磁盘源文件绝对路径
```

### 2. `SkillManager` 仓储能力

- **三态目录发现**：
  - `dirs=None`（默认）：自动探测 `<cwd>/.agents/skills/`；
  - `dirs=[]`：显式禁用；
  - `dirs=[...]`：指定外部路径扫描。
- **`extra_dirs` 动态扩展**：支持接收 `PluginManager` 提取的插件技能目录，无缝聚合插件技能；
- **单 Skill 插件简写支持**：若某目录下直接存在 `SKILL.md`（而非 `<name>/SKILL.md` 子目录），自动提取其为单技能。

---

## 三、`SKILL.md` 规范与容错解析

```markdown
---
name: code-review
description: 针对 Python/TypeScript 项目执行代码审查与并发安全检查
---

## 审查检查单
1. 检查是否存在未捕获的异常；
2. 检查全局状态并发安全性；
3. 检查单测覆盖率。
```

- **守门规则**：解析时若文件缺失 `description` 字段，视为无效技能跳过；
- **编码安全**：采用 `utf-8-sig` 读取，兼容 Windows BOM 头。
