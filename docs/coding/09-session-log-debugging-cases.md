# 会话日志故障排查实战手册与典型案例库 (`docs/coding/09-session-log-debugging-cases.md`)

- **定位**：基于真实会话磁盘数据（`.jsonl`）与双轨日志（`.debug.log` + `.events.jsonl`）的线上故障排查指南与经典案例复盘
- **核心方法**：三轨分立交叉验证法、毫秒级时间差推导（Delta Time Analysis）、双向配对不变式校验
- **关联规范**：[05-rpc-bridge-protocol.md](05-rpc-bridge-protocol.md), [08-observability-and-debug-mode.md](08-observability-and-debug-mode.md), [../core/11-dynamic-steering.md](../core/11-dynamic-steering.md)

---

## 一、排查方法论：基于三轨日志的“证据链闭环分析法”

在传统的黑盒 Agent 调试中，开发者往往只能通过屏幕表现去“猜”问题，频繁改代码试错，不仅效率低下，而且容易引入隐蔽的副作用。
`my-pi-agent` 实现了严格的分会话可观察性。定位任何故障时，必须**同时收集并交叉对比以下三个独立数据源**：

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        用户会话目录 (~/.my-pi-agent)                   │
├───────────────────────────────────┬────────────────────────────────────┤
│ sessions/<slug>-<hash>/           │ logs/<slug>-<hash>/                │
│   ├── <session-id>.jsonl          │   ├── <session-id>.debug.log       │
│   └── (持久化消息树/终审事实)       │   │   (微秒级时间戳/耗时/Token指标)     │
│                                   │   └── <session-id>.events.jsonl    │
│                                   │       (前端通信强类型事件全量流)    │
└───────────────────────────────────┴────────────────────────────────────┘
```

### 1. 三份日志的各自职责与定罪依据

1. **`sessions/.../<id>.jsonl`（终审事实层，Source of Truth）**：
   - **特点**：只有通过了五大 Hook、原子落盘并且未被中止逻辑丢弃的消息，才会追加到该文件中；
   - **用途**：排查大模型 API 400（断头 ToolCall、孤儿 Tool 消息）、上下文截断、会话树分支损坏等。若 session 里没有，说明底层从未将该数据视为历史上下文。
2. **`logs/.../<id>.debug.log`（时序耗时层，Milestone Timings）**：
   - **特点**：记录 Agent 各阶段（`AGENT_START`, `TURN_START`, `LLM_RESPONSE`, `TOOL_CALL_START`, `TOOL_CALL_END`, `AGENT_END`）的精确时间戳、微秒级耗时与单次 Token 增量；
   - **用途**：排查“卡住”、“响应慢”、“死等”。通过相邻两行时间差（$\Delta t$），直接定位到底是网络阻塞、模型思考慢，还是本地子进程未被杀死。
3. **`logs/.../<id>.events.jsonl`（通信事件流，Streaming Events）**：
   - **特点**：记录 Python 内核通过 stdio JSON-RPC 向 Node.js TUI 前端发射的所有事件（`message_start`, `message_update`, `message_end`, `tool_execution_*` 等）；
   - **用途**：排查界面渲染异常（重复气泡、绿勾/红叉错乱、乱码、孤儿文字残留）。**凡是屏幕上看到的东西，必定在该文件中有对应的 Event**。

### 2. 四大排查核心纪律

- **纪律 1：绝不盲猜，拿相邻时间差（$\Delta t$）说话**：几毫秒通常是机器同步流转；几百毫秒是网络往返与本地工具执行；几十秒通常意味着等待超时、子进程挂起或卡死；**两个事件间隔 1ms 则往往意味着强因果同步级联**；
- **纪律 2：三轨比对找矛盾**：比对“磁盘存了什么”与“界面画了什么”。若界面有而磁盘无（如残存的孤儿词），必定是前端未及时清理未成型的流式组件；若磁盘有而界面无，必定是事件反序列化或过滤逻辑异常；
- **纪律 3：不变式离线快检**：遇到对话挂起或大模型报错，第一时间写单行脚本扫描 `jsonl` 检查“带 tool_calls 的 assistant 后面是否严格紧跟对应 tool 消息”；
- **纪律 4：编写测试守株待兔**：在动手修改核心代码前，必须编写能稳定复现该日志特征的单元测试（红），修复后再将其变绿，杜绝重蹈覆辙。

---

## 二、典型实战案例复盘库

---

### 案例 1：即时转向（Steering）在首轮启动时的时序倒挂与语义歧义

- **涉及会话**：`01a0cc76-0776-7fc5-9b9e-413f6b5a070f`、`01a0ccce-6b92-7a28-8bb0-377d39df60ab`
- **问题现象**：用户输入 `帮我读取一下progress` 后任务刚启动，用户突然发现不对，立刻在输入框打入 `暂停` 并敲回车试图打断。结果模型非但没有暂停，反而回复：“好的，我来帮你读取 progress 并处理暂停...”，将两条完全相反的指令合并成复合句理解。

#### 1. 日志现场提取与还原

在 `01a0ccce.debug.log` 中记录了以下时序：
```text
[14:20:10.100] [AGENT_START] prompt="帮我读取一下progress"
[14:20:10.105] [STEER_RECEIVED] text="暂停"
[14:20:10.106] [TURN_START] iteration=1
[14:20:11.350] [LLM_RESPONSE] in_tokens=14200 out_tokens=45
```
查看当时发给大模型的首轮请求消息体（通过离线还原）：
```json
[
  {"role": "user", "content": "帮我读取一下progress"},
  {"role": "user", "content": "暂停"}
]
```

#### 2. 根因分析
- **急躁收割机制（Eager Draining）**：旧版 `loop.py` 在进入第 1 轮大模型推理前，有一段 `if message_queue.has_steering(): pending_messages.extend(...)` 逻辑。导致用户在敲完主任务后不到 50ms 内注入的 `暂停`，在第 1 轮工具还没来得及运行时，就被提前捞出来并排塞进了首轮提示词；
- **模型认知偏差**：大模型同时看到“帮我读取”与“暂停”，判定这是一句复合语义，不仅没有停下，反而开始执行文件读取工具。
- **对齐 Pi 原厂时序契约**：在 Pi 的设计规范中，Steering 指令的交付必须位于**当前轮工具批次执行完毕之后、次轮推理发起之前（Turn-Boundary Delivery）**；首轮推理必须保持原初提问的纯洁性。

#### 3. 解决方案与实施
1. **修改 `src/my_agent_core/loop.py`**：
   - 增加 `_is_first_turn_pending` 标志位。若存在初始 Prompts，第 1 轮推理严格仅消费初始任务；
   - 运行期进入的 Steering 消息暂留在队列中，直到第 1 轮工具执行完毕后，才与工具结果一并呈递给模型；
2. **TUI 挂载待发区呈现 (`interactive-mode.ts`)**：
   - 用户敲回车后，输入框立即清空，在输入框上方挂载 `Steering: 暂停`（灰暗色，不提前塞入聊天区）；
   - 支持按 `Alt+Up` / `Alt+Q` 将未交付的插话弹回输入框修改；
   - 只有当内核完成本轮工具并在次轮通过 `message_start` 交付时，才移入主聊天记录。

#### 4. 验证效果
编写 `tests/core/test_agent_steering.py` 中的 `test_steer_queued_before_run_delivers_after_turn1_tools`。断言首轮 LLM 收到的 user messages 仅包含初始任务，次轮才包含工具结果与“暂停”，模型精准感知打断并回复“已响应转向指令，停止后续操作”。

---

### 案例 2：Windows 下 Bash 退化至 cmd.exe、GBK 乱码与失败工具画绿勾

- **涉及会话**：`01a0d11e-56e5-7558-8caf-8135447aced4`
- **问题现象**：
  在 Windows 终端启动后，输入 `你了解一下这个项目`，TUI 呈现如下极其违和的画面：
  ```text
   ✓ bash (command=find src -name "*.py" | head -100) (0.0s)

   Command failed with exit code 255:
   'head' ڲⲿҲǿеĳ

   ļ

   执行已中断。
   Windows
  ```
  工具执行明明崩了，却画了绿色的 `✓`；报错全是乱码；用户按 Esc 中断后，屏幕上突兀地多出一个孤儿词 `Windows`。

#### 1. 日志现场提取与还原

- 查看 `01a0d11e.events.jsonl`：
  ```json
  {"type": "tool_execution_end", "toolCallId": "call_01_...", "toolName": "bash", "result": "Command failed with exit code 255: 'head' ڲⲿ...", "isError": false}
  {"type": "turn_start", "iteration": 2}
  {"type": "message_start", "message": {"role": "assistant", "content": ""}}
  {"type": "message_end", "message": {"role": "assistant", "content": "Windows", "metadata": {"stop_reason": "cancelled"}}}
  {"type": "agent_end", "iterations": 2, "stop_reason": "cancelled"}
  ```
- 查看 `01a0d11e.jsonl`：
  磁盘持久化文件最后一条消息为第 1 轮工具的报错，**压根没有包含 `"Windows"` 这一条消息**。

#### 2. 根因分析
1. **Windows 下未探查 Git Bash**：`bash.py` 内部直接使用了 `asyncio.create_subprocess_shell`，在 Windows 下默认被操作系统派发给了 `cmd.exe /c`。而 `cmd.exe` 根本没有 `ls` 和 `head`，导致报错退出（Exit Code 255）；
2. **GBK 乱码（Mojibake）**：`cmd.exe` 报错文本按系统 GBK (CP936) 编码吐出，而 `bash.py` 使用了写死的 `decode("utf-8", errors="replace")` 硬解，导致中文变为乱码；
3. **失败误判为成功**：当 `exit_code != 0` 时，`bash.py` 直接返回了字符串。`@tool` 装饰器将无异常的字符串直接封装成了 `ToolResult(ok=True)`，进而发射了 `isError: false`，导致 TUI 前端绘制了绿勾 `✓`；
4. **中断残留孤儿文本**：第 2 轮模型刚吐出 `"Windows"`，用户按了 Esc。TUI 虽在接收到按键时打了 `执行已中断。`，但紧随其后的 `message_end` 带着被丢弃的 `"Windows"` 到达时，前端未将其移除，反而新建了一个气泡挂在中断通知后面。

#### 3. 解决方案与实施
1. **对标 Pi 实现 Git Bash 智能探查 (`src/my_coding_agent/tools/bash.py`)**：
   - 增加 `_resolve_shell()`：自动检测用户已安装的 Git Bash（如 `D:\gitbash\Git\bin\bash.exe`，`%ProgramFiles%\Git\bin\bash.exe` 等）；
   - 以 `bash.exe -c <cmd>` 模式执行，注入 `LANG=C.UTF-8` 与 `LC_ALL=C.UTF-8`；
2. **防御性双解机制 (`_decode_stream_bytes`)**：
   - UTF-8 优先解码，一旦遇 `UnicodeDecodeError` 立即回退至 `locale.getpreferredencoding()`（如 GBK/CP936），彻底杜绝乱码；
3. **失败退出码显式标红**：
   - 当 `exit_code != 0` 时，显式返回 `BashResult(ok=False, data=msg, error=msg)`，确保 `is_error=True`，让 TUI 渲染红色 `✗` 与 `(失败)`；
4. **前端中断安全清理 (`tui/src/interactive/interactive-mode.ts`)**：
   - 用户按 Esc/Ctrl+C，或收到 `stop_reason === "cancelled" / "aborted"` 时，立即从 `chatContainer` 中安全移除正在流式的 `currentStreamingAssistant`，杜绝孤儿单字污染视口。

#### 4. 验证效果
- 在 Windows 环境下执行 `find src -name "*.py" | head -100` 顺利跑通，退出码为 0，输出整洁；
- 编写 `test_bash_command_failure_exit_code` 验证非零退出码下 `res.ok is False`；
- 编写 TUI 测试 `InteractiveMode removes incomplete streaming assistant message on Escape interrupt and cancelled events`，验证中断后残片自动消失，全绿通过。

---

### 案例 3：中断假死（死等 29.8 秒）与管道错误掩盖（`pytest | tail`）

- **涉及会话**：`01a0d14f-2d24-7ffa-a083-5d9d81269056`
- **问题现象**：
  在修复案例 2 之后，用户在会话中执行 `你好`。大模型决定执行 `python -m pytest -q 2>&1 | tail -15`。命令开始跑之后用户按 `Escape` 试图中断，但**终端完全无响应，死死卡住等了整整 30 秒**！直到 30 秒后测试跑完才停住，停住后用户无奈又输入了 `"暂停一下"`；同时，该命令虽然测试失败了，却依然画了绿勾 `✓`。

#### 1. 日志现场提取与还原

提取 `01a0d14f.debug.log` 中的毫秒级时间戳记录：
```text
[10:48:59.397] [TOOL_CALL_START] tool=bash id=call_00_t4qpI0T1dS02VM5DP7sO3972 args={"command": "... pytest -q 2>&1 | tail -15", "timeout": 600}
[10:49:29.189] [TOOL_CALL_END] tool=bash duration=29791ms status=OK
[10:49:29.192] [TURN_END] duration=31026ms
[10:49:29.192] [AGENT_END] stop_reason=cancelled iterations=3
[10:49:29.193] [AGENT_START] prompt="暂停一下"
```
提取 `01a0d14f.events.jsonl` 第 75 行：
```json
{"type": "tool_execution_end", "toolName": "bash", "result": "=== short test summary info ===\r\nFAILED tests/coding/test_bash_tool.py...", "isError": false}
```

#### 2. 根因分析
1. **29.8 秒时间黑洞分析**：
   - `10:48:59.397` 工具启动；
   - `10:49:29.189` 工具结束，耗时整整 **29,791ms**；
   - `10:49:29.192`（3毫秒后）记录了 `stop_reason=cancelled`；
   - `10:49:29.193`（1毫秒后）用户输入了 `"暂停一下"`。
   - **推导结论**：用户绝不可能在第 1 毫秒瞬间看到结果并打字。真实情况是用户早就按了 Esc，但后台子进程根本没有停下，而是**硬生生跑了近 30 秒直到 pytest 自然跑完**！用户等烦了以为没停住，才补敲了 `"暂停一下"`；
2. **为什么杀不死子进程？**：
   - 排查 `src/my_coding_agent/tools/bash.py` 签名发现：`async def bash(...)` 根本没有声明 `signal` 参数；
   - 在 `src/my_agent_core/tools/core.py` 中，框架检查 `self._accepts_signal = "signal" in sig.parameters`，因为未声明，`CancellationToken` 从未传给 `bash`；
   - 当用户按 Esc 时，内核把 `signal` 置为取消，但 `bash.py` 还在盲目执行 `await proc.wait()`，子进程完全不受控；
3. **管道退出码被吞没（Masked Exit Code）**：
   - `pytest` 虽然报了 `FAILED`（退出码 1），但末尾管道是 `tail -15`；
   - 在标准 Bash 中，管道 `A | B` 的退出码只取最后一个命令（`B`）的结果。`tail` 成功退出了（0），导致整体退出码被篡改为 0，再次误画了绿勾 `✓`。

#### 3. 解决方案与实施
1. **`CancellationToken` 回调通知机制 (`src/my_agent_core/loop.py`)**：
   - 为 `CancellationToken` 增加 `add_callback(cb)` 接口，支持在取消时立刻广播回调；若已取消则同步立即执行；
2. **`bash.py` 显式接入 `signal` 并瞬时斩断进程树**：
   - 参数列表声明 `signal: Any | None = None`；
   - 进程启动后立即绑定 `signal.add_callback(_abort_proc)`；
   - 一旦用户在 TUI 按下 Esc，在 1ms 内直接调用 `taskkill /F /T /PID` 杀死 Windows 下的完整子进程树，使 `proc.wait()` 瞬间退出并返回 `Tool call interrupted by user`；
3. **前置注入 `set -o pipefail` 穿透管道错误**：
   - 在 Git Bash 模式下，执行前置追加 `set -o pipefail\n`；
   - 保证管道中哪怕任意一个前置命令报错，整条管道都能如实向上反馈非零退出码；
4. **工具描述 POSIX 规范化**：
   - 将工具描述明确定义为 `(POSIX / Git Bash syntax; do not use cmd.exe syntax like 'dir' or 'cd /d')`，杜绝大模型在 Windows 下盲目生成 `cd /d`。

#### 4. 验证效果
- 编写单元测试 `test_bash_signal_cancellation_kills_process_immediately`：模拟执行 30 秒休眠脚本并中途 cancel，测试在 **< 1.0 秒** 内瞬时杀死进程树并成功退出（修复前会僵死 30 秒导致断言失败）；
- 编写 `test_bash_pipefail_propagates_error`：验证 `python -c "sys.exit(42)" | cat` 如实返回失败与退出码 42；
- 全库 717 个 Python 测试与 69 个 TUI 测试 100% 绿灯全通。

---

## 三、排查速查表与常见症状索引

| 现象 / 症状 | 对应排查切入点 | 检查指标与日志特征 | 常见根因与解决手段 |
| :--- | :--- | :--- | :--- |
| **界面卡住 / Spinner 转不停** | `debug.log` 检查最近一条 `[TOOL_CALL_START]` | 观察最后一条工具日志与当前时间的 $\Delta t$ | 工具未接入 `signal` 导致无法响应取消；或子进程在等交互式 stdin（需确保 `stdin=DEVNULL`）。 |
| **工具失败了但界面显示绿勾 `✓`** | `events.jsonl` 查看 `tool_execution_end` | 查看事件 JSON 中的 `"isError"` 是否为 `false` | 工具函数返回了普通字符串而未返回 `ToolResult(ok=False)`；或 Bash 管道末尾命令吞噬了退出码（需 `pipefail`）。 |
| **中文报错显示为乱码（`ڲ...`）** | `jsonl` 检查 `tool` 消息 content | 出现典型的 GBK 乱码字符（`\ue8ec` 等） | Windows 子进程以 ANSI/CP936 输出，Python 代码硬解 UTF-8。需做防御性回退双解。 |
| **大模型 API 报 400（Invalid Tool Call）**| `jsonl` 检查 `assistant` 与 `tool` 序列 | 运行不变式检测脚本，检查是否存在未闭合的 tool_call_id | `tool_history.py` 转录本修复未覆盖；中途崩溃未写入配对的 `Tool call interrupted by user`。 |
| **中断后屏幕残留孤儿单词** | `events.jsonl` 对比 `jsonl` 记录 | `events` 里有 `message_end (cancelled)`，而 `jsonl` 里没有 | TUI 前端在收到取消事件时未从 DOM/Container 中卸载正在流式的 `AssistantMessageComponent`。 |
| **提问后内容被渲染了两次** | `events.jsonl` 检索 `message_start (role="user")` | 查看前端用户提问气泡挂载时机 | 前端在 `handleUserInput` 时挂了一次，收到内核回传的常规提问事件时又挂了一次。必须仅对出队的 Steering/Follow-up 补发气泡。 |
