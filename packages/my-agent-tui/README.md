# packages/my-agent-tui

`my-pi-agent` 的高质感交互终端表现层（基于 `@earendil-works/pi-tui` 的 Node.js / TypeScript 前端 Shell）。

## 核心特性

- **Pi 原厂渲染引擎**：基于 `@earendil-works/pi-tui` 的 `TuiMainScreen` 差量重绘器，保留原生终端历史与鼠标滚轮翻看；
- **CSI 2026 同步屏障**：垂直原子刷新，彻底消灭字符撕裂与屏幕闪烁；
- **24-bit TrueColor 卡片系统**：移植 Pi 官方 `dark.json` 柔和调色盘，消息气泡与圆角卡片；
- **动态思考折叠块 (Thinking Block)**：流式大模型思考过程展示，`Ctrl+O` 随时展开/折叠；
- **就地更新工具卡片**：圆角细线卡片（`╭─ ⚙️ read ... ─╮`）、点阵 Spinner 微动效、执行完成变绿与耗时提示；
- **富文本多行编辑器与 IME 光标锚定**：支持中文输入法硬件光标精准对齐，候选框永不乱跳；
- **stdio JSON-RPC 双向流**：与 Python 无头业务内核 `my-coding-agent` 深度集成，支持 `Esc` 瞬时打断与键入即时转向。

## 启动与运行

```bash
cd packages/my-agent-tui
npm install
npm run build
npm start
```
