# my-pi-agent 对齐 Pi 原厂交互选择器 (Interactive Selectors) 架构设计规范

**Document ID:** `docs/coding/17-pi-interactive-selectors-and-tui-parity-design.md`  
**Status:** Approved  
**Author:** AI Architecture Team  
**Date:** 2026-03-31  

---

## 1. 背景与对齐愿景 (Vision & Background)

在 `@earendil-works/pi-coding-agent` 中，诸如 `/resume`、`/model`、`/thinking`、`/settings` 等斜杠命令，**绝不会把长篇列表以静态纯文本的方式刷入聊天历史区**。

相反，Pi 拥有一个独特的 **`showSelector` 动态视口抽换架构**：
当用户输入不带参数的交互命令时，底部的 `editor`（输入框）会被临时原地替换为一个具备**模糊搜索、方向键高亮、快捷键过滤、Enter 确定、Esc 取消**的**交互式选择器组件 (Selector Component)**。选择完毕或按 Esc 退出后，输入框恢复原位并重获输入焦点。

本文档基于对 Pi 原厂源码（`dist/modes/interactive/`）的深度排查，系统梳理当前 `my-pi-agent` 的交互差距（Gap Analysis），并制定一套 100% 对齐原厂的选择器架构与组件实现规范。

---

## 2. 核心架构：视口插槽抽换机制 (`showSelector`)

### 2.1 容器挂载拓扑纠偏 (`editorContainer`)

在主屏 `TuiMainScreen` 的自顶向下层级中，输入区域不能直接挂载裸的 `Editor`，而必须挂载一个名为 `editorContainer` 的包装槽位容器：

```text
┌──────────────────────────────────────────────────────────┐
│ 1. HeaderComponent (顶部极简启动横幅)                       │
├──────────────────────────────────────────────────────────┤
│ 2. ChatContainer (消息流动区: User / Assistant / Tools)  │
├──────────────────────────────────────────────────────────┤
│ 3. editorContainer (动态插槽容器) ─────────────────────┐ │
│    [平常态] 挂载: Editor 输入框 (带上下水平边框)         │ │
│    [选择态] 抽换为: SelectorComponent (交互选择列表)     │ │
│    (用户按 Enter 确认 或 Esc 取消后，自动换回 Editor)    │ │
│ ───────────────────────────────────────────────────────┘ │
├──────────────────────────────────────────────────────────┤
│ 4. FooterComponent (双行自适应状态栏: 路径分支 + 指标模型) │
└──────────────────────────────────────────────────────────┘
```

### 2.2 `showSelector(create)` 状态机与生命周期

```typescript
export interface ActiveSelector {
  component: Container;
  focus: Focusable;
  dispose?: () => void;
}

public showSelector(create: (done: () => void) => ActiveSelector): void {
  const token = {};
  let dispose: (() => void) | undefined;

  const done = () => {
    dispose?.();
    // 防回调竞态保护：避免过期的选择器破坏后续激活的选择器
    if (this.activeSelectorToken !== token) return;
    this.activeSelectorToken = undefined;
    this.activeSelectorDispose = undefined;
    
    // 恢复 Editor 并归还终端焦点
    this.editorContainer.clear();
    this.editorContainer.addChild(this.editor);
    this.tui.setFocus(this.editor);
    this.tui.requestRender();
  };

  const created = create(done);
  dispose = created.dispose;

  this.disposeActiveSelector();
  this.activeSelectorToken = token;
  this.activeSelectorDispose = dispose;

  // 原地抽换槽位
  this.editorContainer.clear();
  this.editorContainer.addChild(created.component);
  this.tui.setFocus(created.focus);
  this.tui.requestRender();
}
```

---

## 3. Pi 与 my-pi-agent 全面功能差距排查 (Gap Analysis)

通过对 Pi 官方 12 个交互选择器的逆向排查，对照当前 `my-pi-agent`：

| 核心命令 / 功能 | Pi 官方交互表现 | my-pi-agent 现状 | 差距与改进点 |
| :--- | :--- | :--- | :--- |
| **`/resume`** | 调起 `SessionSelectorComponent`：<br>• `↑`/`↓` 上下高亮选择<br>• 输入关键字即时模糊搜索<br>• `Tab` 切换本目录 ↔ 全局会话<br>• `Ctrl+P` 切换显示完整路径<br>• `Enter` 恢复会话，`Esc` 退出 | 纯文本打印最多 15 个会话的列表，用户必须重新手动输入 `/resume <id>`。 | **差距极大**：缺少动态交互选择列表，体验割裂。需实现 `SessionSelectorComponent`。 |
| **`/model`** | 调起 `ModelSelectorComponent`：<br>• 输入框实时模糊搜索<br>• 标注 Provider 标签（`[openai]`）、上下文大小（`· 128k`）<br>• 当前生效模型带 `✓` 标记<br>• `Ctrl+S` 设为全局默认 | 纯文本打印当前模型，提示用户通过 `/model <name>` 切换。 | **差距极大**：用户无法直观浏览可用模型。需实现 `ModelSelectorComponent`。 |
| **`/thinking`** | 调起 `ThinkingSelectorComponent`：<br>• 7 级深度选择（`off` ~ `max`）<br>• 每级标注 Token 预算估算说明<br>• 当前等级带 `✓`<br>• `Shift+Tab` 可在会话内就地循环 | 纯文本输出可选等级名称列表。 | **差距较大**：缺少单选交互列表与说明。需实现 `ThinkingSelectorComponent`。 |
| **`/tree`** | 调起 `TreeSelectorComponent`：<br>• 全键盘交互 DAG 漫游<br>• `←`/`→` 折叠展开，`e` 重命名，`c` 拷贝节点，`Enter` 瞬切节点 | 纯文本打印 ASCII DAG 树，不可选、不可漫游。 | 需逐步迁移至可交互式会话树漫游器。 |
| **`/settings`** | 调起 `SettingsSelectorComponent`：<br>• 包含自动压缩、思维链深度、主题切换、图表渲染等交互式勾选开关与子菜单 | 纯文本打印 3 条关于 `settings.json` 文件路径的说明。 | 需接入可配置项交互列表。 |

---

## 4. 首期 3 大核心选择器详细设计规范

为兼顾用户最常用的核心路径与最佳性价比，第一期全力交付最关键的 3 大选择器：

### 4.1 会话选择器组件 (`SessionSelectorComponent`)

- **文件位置**：`tui/src/components/session-selector.ts`
- **视觉排版**：
  - 顶部与底部：`DynamicBorder` 柔和细分割线；
  - 头部状态行：`Resume Session` (加粗)，右侧 `◉ Current Folder | ○ All`；
  - 提示行：`Tab scope · Ctrl+P path · Enter resume · Esc cancel`；
  - 搜索输入框：`Input` 组件，支持输入时即时过滤；
  - 单行会话列表（最多 10 行滑动窗口）：
    - 选中光标：`›`，未选中 `  `；
    - 当前活动会话文字：高亮 `accent`；
    - 用户命名会话文字：高亮 `warning` (黄色)；
    - 右侧元数据：`[路径] [CWD] [消息数] [相对时间]`；
    - 选中行整行以 `theme.bg("selectedBg", ...)` 沉浸式高亮。

### 4.2 模型选择器组件 (`ModelSelectorComponent`)

- **文件位置**：`tui/src/components/model-selector.ts`
- **视觉排版**：
  - 顶部与底部：`DynamicBorder`；
  - 顶部提示：`Only showing models from configured providers. Use /login to bind credentials.`；
  - 搜索框：支持分词模糊搜索（如 `open 4o` 或 `deepseek`），置顶 `default` 关键字；
  - 候选列表（最多 10 行）：
    - 选中行前缀：`→`；
    - 当前生效模型前缀：`✓`；
    - 格式：`{id} [{provider}] · {contextWindow}k {defaultBadge}`；
    - 底部展示选中模型的完整商业名称与说明；
  - 按键控制：`↑`/`↓` 移动、`Enter` 临时生效、`Ctrl+S` 设为默认、`Esc` 取消。

### 4.3 思考深度选择器组件 (`ThinkingSelectorComponent`)

- **文件位置**：`tui/src/components/thinking-selector.ts`
- **视觉排版**：
  - 7 级标准等级：
    - `off`: `No reasoning`
    - `minimal`: `Very brief reasoning (~1k tokens)`
    - `low`: `Light reasoning (~2k tokens)`
    - `medium`: `Moderate reasoning (~8k tokens)`
    - `high`: `Deep reasoning (~16k tokens)`
    - `xhigh`: `Extra-high reasoning (~32k tokens)`
    - `max`: `Maximum reasoning`
  - 当前生效等级标有 `✓`，默认等级追加 `· default`；
  - 底部提示：`Enter to select · Ctrl+S to set as default · Escape to cancel`。

### 4.4 辅助动态分割线 (`DynamicBorder`)

- **文件位置**：`tui/src/components/dynamic-border.ts`
- 宽度自适应横向细线组件，自动根据终端窗口当前 `width` 绘制 `─`，与 Pi 官方 100% 一致。

---

## 5. 后端 RPC 内核适配 (`rpc_server.py`)

为了支持前端选择器动态拉取真实数据，Python RPC 服务器需要提供完备的数据接口：

1. `session_list(all_projects: bool)`：返回所有会话的 id、名称、修改时间、消息条数、cwd 及物理路径（已支持）；
2. `session_resume(session_id: str)`：恢复指定会话（已支持）；
3. `model_list()`：返回当前所有已配置 Provider 的可用模型清单及上下文窗口大小（新增/完善）；
4. `thinking_set(level: str)`：调整思考深度（已支持）。
