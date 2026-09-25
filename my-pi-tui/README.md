# my-agent-tui

`my-pi-agent` 的高质感交互终端表现层（基于 `@earendil-works/pi-tui` 的 Node.js / TypeScript 前端微内核）。

已正式发布至 npm 全球仓库：[`my-pi-agent`](https://www.npmjs.com/package/my-pi-agent)。

---

##  安装与使用

### 1. 全局安装使用（推荐）

```bash
# 全局安装 CLI
npm install -g my-pi-agent

# 在任意目录下启动交互式终端
my-pi-agent
# 或使用快捷别名
my-agent
```

### 2. 免安装秒级拉起 (npx)

```bash
npx my-pi-agent
```

### 3. 命令行参数 (CLI Options)

```text
Usage:
  my-agent [options] [prompt]

Options:
  -c, --continue          一键续接当前项目最近一次历史会话
  -r, --resume [id]       启动时直接打开交互式会话选择器或恢复指定会话
  --new-session           强制开启全新会话 (默认)
  -n, --name <title>      启动时直接为该会话命名
  -m, --model <model>     指定生效模型 (如 deepseek-chat, gemini-3.8-flash)
  --thinking <level>      指定思考深度等级 (off/minimal/low/medium/high/max)
  --no-session            内存无痕沙箱模式 (不持久化 session 文件)
  -d, --debug             启用事件级 Debug 日志落盘模式
  -w, --workspace <dir>   指定工作区目录 (默认: 当前目录)
  --mode <mode>           权限安全模式: review (默认) | yolo | strict
  -h, --help              查看帮助说明
```

---

## 核心特性（100% 像素级对齐 Pi 原厂终端）

- **Pi 原厂终端渲染微内核**：
  基于 Mario Zechner 的 `@earendil-works/pi-tui` 终端引擎（`TuiMainScreen`），以字符差量重绘驱动，保留终端原生可滚动的长历史与鼠标滚轮平滑翻看。
- **CSI 2026 同步垂直屏障**：
  在渲染前发射 `\x1b[?2026h`，渲染完成后发射 `\x1b[?2026l`，彻底根除高频输出时的字符撕裂与屏幕闪烁。
- **输入框边框实时嵌入转圈 (`CustomEditor`)**：
  100% 移植 Pi 原厂定制编辑器，重写 `renderTopBorder`。在模型思考或工具执行期间，输入框顶部边框实时挖槽嵌入 Braille 10 帧高频旋转指示器（`── ⠸ Working ──`），完成或中断时平滑自愈复原为干净横线。
- **思考预算深度自适应轮转与边框变色**：
  支持 `Shift+Tab` / `Ctrl+T` 快捷键原地循环切换思考深度（`off` ➔ `low` ➔ `medium` ➔ `high` ➔ `max`）。根据当前模型能力（Gemini / OpenAI o-series / Claude / DeepSeek）自动夹逼适配，并联动输入框边框颜色动态变换（蓝/紫/绿等）。
- **三大交互式模态选择器**：
  - **`ModelSelector`**：支持拼音/模糊拼写过滤，自动展示已配置 Provider，支持 `Ctrl+S` 持久化保存默认模型；
  - **`SessionSelector`**：多级 DAG 分支连接符展示（`│ `, `├─ `, `└─ `），支持 `Ctrl+D` 二次确认安全删除历史会话与活跃会话保护；
  - **`ThinkingSelector`**：图形化列出并切换推理深度。
- **可折叠卡片系统 (`Ctrl+O`)**：
  - **Thinking Block**：模型流式思考过程折叠预览，按 `Ctrl+O` 一键展开查看完整思维链；
  - **Compaction Card**：上下文压缩摘要卡片（`[compaction] Compacted from X tokens (Ctrl+O to expand)`），避免多千字长文本冲刷视口；
  - **Tool Execution**：圆角细线卡片展示工具参数、执行进度、100ms 增量输出与耗时统计。
- **动态即时插话与排队追问 (Steering & Ctrl+Q Follow-up)**：
  - 智能体运行期输入普通文本或 `/steer <msg>` 敲回车，自动作为 Steering 转向指令送入内核；
  - 智能体运行期按下 **`Ctrl+Q`**，自动将输入框内容作为 Follow-up 排队追问，待当前任务彻底完成后自动顺延执行；
  - 输入框上方实时灰显呈现 `Steering: ...` 与 `Follow-up: ...` 待发状态，支持 `Alt+Q` / `Alt+Up` 或 `Esc` 中断一键全量召回编辑并清空内核排队；
- **全屏与分会话调试诊断 (`/debug` 与双轨日志)**：
  - 输入 `/debug` 一键导出终端渲染现场快照与当前会话的专属 `.debug.log` 和 `.events.jsonl` 日志绝对路径。
- **输入行即时宏扩展管道 (`MacroEngine`)**：
  - `!cmd`：本地 Shell 命令同步执行并自动追加至模型上下文（以 `!` 开头键入时边框即时响应黄色预警）；
  - `!!cmd`：静默执行探查命令，打上 `exclude_from_context` 标记，彻底排除在模型上下文之外（0 Token 消耗）；
  - `/skill:<name>`：动态加载并展开本地或全局技能规范；
  - `/<template>`：带引号参数解析与 `$1` / `$@` 模板展开。
- **财务级双行状态底栏 (`FooterComponent`)**：
  紧凑呈现当前工作区、会话分支、模型名、思考等级，以及分级 Token 消耗、成本核算、上下文窗口占比与 Prompt Cache 命中率（`CH%`）。

---

## 本地开发与构建

```bash
# 1. 安装依赖
npm install

# 2. 编译 TypeScript
npm run build

# 3. 运行 TUI 自动化测试套件 (69 tests, 100% 绿灯全通)
npm test

# 4. 本地启动交互终端
npm start
```
