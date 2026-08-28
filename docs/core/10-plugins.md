# Claude Code 风格 Plugin 插件系统设计规范 (`my_agent_core.plugins`)

- **定位**：Claude Code 官方标准插件聚合分发与自包含资源解构系统 (`packages/my-agent-core/src/my_agent_core/plugins.py`)
- **核心类**：`PluginAuthor`, `PluginManifest`, `Plugin`, `PluginManager`
- **主要实现**：`plugins.py`

---

## 一、架构设计与定位

Plugin 插件系统对齐 Claude Code 官方插件规范，定位为 **“自包含资源聚合分发包（Bundle & Dispatcher）”**。
用户通过一个插件文件夹即可同时打包技能、子代理与外部工具，由 `PluginManager` 统一扫描、解析并解构分发给底层管家：

```text
               Claude Code 插件目录 (my-plugin/)
               ├── .claude-plugin/plugin.json (或 .plugin/ 或根目录 SKILL.md)
               ├── skills/
               ├── agents/
               └── .mcp.json
                         │
                         ▼
                   PluginManager
                         │
         ┌───────────────┼───────────────┐
         ▼               ▼               ▼
  get_skill_dirs() get_subagent_dirs() get_mcp_config_paths()
         │               │               │
         ▼               ▼               ▼
   SkillManager   SubagentManager    MCP 客户端
  (自动注入技能)  (自动注册专员)    (自动连接工具)
```

---

## 二、核心类与数据结构

### 1. 身份证与弹性作者解析 (`PluginAuthor` & `PluginManifest`)

- **`PluginAuthor`**：通过 `from_value` 弹性解析 `"Anthropic <support@anthropic.com>"` 字符串与 `{"name": "...", "email": "..."}` 字典；
- **`PluginManifest`**：包含 `name`、`version`（默认 `"1.0.0"`）、`description`、`author`、`homepage`、`license`、`keywords` 等标准元数据。

### 2. `Plugin` 实体与属性探针

- **多级查找与兜底推断 (`Plugin.from_directory`)**：
  查找顺序：`.claude-plugin/plugin.json` ➔ `.plugin/plugin.json` ➔ `./plugin.json` ➔ 目录名智能兜底推断；
- **资源计算属性（Properties）**：
  - `skills_dir`：优先 `skills/`，次选 `commands/`，根目录单 `SKILL.md` 简写直接返回插件根；
  - `agents_dir`：`agents/` 目录；
  - `mcp_config_path`：`.mcp.json` 配置文件。

### 3. `PluginManager` 调度总管

- **三态扫描**：`None`（自动探测 `.agents/plugins`）/ `[]`（显式禁用）/ `list[Path]`（指定路径）；
- **单点故障隔离（Never-Crash）**：单个插件 JSON 损坏或异常只记 Warning，绝不崩溃主 Agent。

---

## 三、核心设计不变式

1. **零重复造轮子（No Reinventing the Wheel）**：
   - `PluginManager` 仅专注做“发现与拆包”，底层的执行 100% 复用已有的 `SkillManager`、`SubagentManager` 与 `ExtensionManager`。
2. **子代理递归探测隔离**：
   - 在 `TaskManager` 创建子 Agent 时，显式配置 `plugin_dirs=[]`、`subagent_dirs=[]`、`memory_dir=False`，防止子代理重新探测插件导致工具冲突。
3. **Windows BOM 容错**：
   - 强制使用 `utf-8-sig` 解析 `plugin.json`，解决 Windows 记事本编码兼容问题。
