# 可观察性与调试诊断体系规范 (`my_coding_agent.tracer`)

- **定位**：面向生产环境与复杂自主 Agent 开发的全链路事件驱动可观察性与调试诊断系统。
- **源码对应**：`src/my_coding_agent/tracer.py`、`src/my_agent_core/events.py`、`tui/src/interactive/interactive-mode.ts`。

---

## 一、背景与设计理念

### 1. 为什么传统的断点与黑盒测试无法解决 Agent 调试痛点？
自主 Coding Agent 与确定性传统程序存在本质差异：
1. **多轮累积效应（Stochastic Drift）**：单个 LLM 请求与工具执行虽然均返回 `200 OK`，但在 5 轮迭代后可能发生意图偏移，陷入同一参数死循环；
2. **终端全屏 UI 独占（TUI Isolation）**：`my-pi-agent` 表现层采用 `@earendil-works/pi-tui` 的 CSI 2026 同步渲染管道，`stdout` 被 JSON-RPC 协议完全独占，直接 `print()` 日志会引发界面撕裂或协议解析崩溃；
3. **不可变事实追溯**：当模型生成畸形代码或错误调用工具时，开发者需要“事后黑匣子”精准追溯模型当时的 Prompt、前缀缓存状态与真实工具入参。

### 2. 对标官方 Pi (`@earendil-works/pi-coding-agent`)
- **官方 Pi 的做法**：
  - 在 `src/config.ts` 定义 `getDebugLogPath()`，指向 `~/.pi/agent/pi-debug.log`；
  - 提供隐藏命令 `/debug`，将当前终端 ANSI 渲染行与最后一次发送给模型的 `messages` 写入该文件；
  - 在子进程 RPC 模式（`rpc-client.ts`）下，仅将 `stderr` 作为辅助捕获。
- **`my-pi-agent` 的超越与深化**：
  - 拥有 12 个强类型不可变生命周期事件（`events.py`）与 5 个控制流决策钩子（`hooks.py`）；
  - 建立“**全自动事件时序落盘（`debug.log`）** + **彩色终端瀑布流（`ConsoleTracer`）** + **交互式瞬时快照（`/debug`）** + **异常死循环看门狗（`Watchdog`）**”四维一体的调试架构。

---

## 二、双模调试架构设计

```text
               ┌─────────────────────────────────────────────────────────┐
               │         启动激活: --debug / -d 或 MY_AGENT_DEBUG=1       │
               └────────────────────────────┬────────────────────────────┘
                                            │
                             ┌──────────────┴──────────────┐
                             ▼                             ▼
                    【TUI / RPC 生产交互态】        【无头脚本 / 单元测试态】
                             │                             │
                             ▼                             ▼
              ~/.my-pi-agent/logs/debug.log         控制台彩色时序瀑布流
              (支持另开终端 tail -f 实时观测)           (标准错误流 sys.stderr 打印)
                             │
                             ▼
                    交互式隐藏命令 /debug
              (一键导出 debug-dump.json 运行时快照)
```

### 1. 核心设计原则
1. **零侵入（Non-Invasive）**：核心 ReAct 状态机（`loop.py`）保持纯函数特性，100% 通过 `agent.subscribe(tracer)` 旁路接入，监听器内部所有异常被 `contextlib.suppress(Exception)` 吸收，调试器故障绝不影响 Agent 核心执行。
2. **毫秒级性能剖析**：基于事件内置的保序时间戳（`event.timestamp`），精确计算：
   - **TTFT (Time to First Token)**：首个流式 Token 响应延迟；
   - **Tool Execution Duration**：单工具纯执行物理耗时；
   - **Turn End-to-End Latency**：单轮循环端到端耗时。
3. **环境隔离自愈**：统一受控于 `paths.logs_dir`（`~/.my-pi-agent/logs/`），自动创建目录，绝不污染项目工作区。

---

## 三、调试系统三大核心组件

### 1. 事件时序日志追踪器 (`DebugEventTracer`)
当用户通过 `--debug` 启动或设置 `MY_AGENT_DEBUG=1` 时激活：

```python
class DebugEventTracer:
    """监听全部不可变生命周期事件，计算毫秒级时序耗时并持久化为易读的 debug.log。"""
    
    def __init__(self, log_path: Path, console_output: bool = False):
        self.log_path = log_path
        self.console_output = console_output
        self._tool_starts: dict[str, float] = {}
        self._turn_start_ts: float = 0.0

    def __call__(self, event: Event) -> None:
        # 针对 AgentStart, TurnStart, ToolExecutionStart/End, MessageEnd, AgentEnd
        # 格式化时间戳 [YYYY-MM-DD HH:MM:SS.mmm] 并写入文件
```

**日志样例输出**：
```log
[2026-09-17 16:10:01.210] [AGENT_START] session=01a0af.. workspace=D:/code/python/my-pi-agent
[2026-09-17 16:10:01.215]   ↳ UserInput: "请帮我读取 package.json 的版本号"
[2026-09-17 16:10:01.220] [TURN_START] iteration=1
[2026-09-17 16:10:02.450] [LLM_RESPONSE] duration=1230ms model=deepseek-flash in_tokens=1250 out_tokens=38
[2026-09-17 16:10:02.455]   ↳ Thinking: "用户需要读取 package.json，我将调用 read 工具..."
[2026-09-17 16:10:02.460] [TOOL_CALL_START] call_id=call_01 tool=read
[2026-09-17 16:10:02.462]   ↳ Args: {"path": "package.json"}
[2026-09-17 16:10:02.482] [TOOL_CALL_END] call_id=call_01 tool=read status=OK duration=20ms
[2026-09-17 16:10:02.483]   ↳ Result: {"name": "my-pi-agent", "version": "0.1.0"} (340 bytes)
[2026-09-17 16:10:02.490] [TURN_END] iteration=1 duration=1270ms
[2026-09-17 16:10:03.200] [AGENT_END] stop_reason=end_turn total_iterations=2 total_cost=$0.0003
```

### 2. 交互式隐藏快照命令 (`/debug`)
对标 Pi 官方设计，在 TUI 中输入 `/debug`：
- **动作**：向 RPC 提交 `debug_dump` 请求；
- **输出文件**：`~/.my-pi-agent/logs/debug-dump.json`；
- **包含内容**：
  1. 当前完整消息列表（`messages`）；
  2. 当前系统提示词（`system_prompt`）；
  3. 当前激活的全部工具列表（`registered_tools`）；
  4. SessionTree DAG 当前分支节点与父子依赖拓扑；
  5. 累计 Token 统计与上下文容量占比。
- **界面提示**：在终端弹出通知：`✓ 调试快照已导出至 ~/.my-pi-agent/logs/debug-dump.json`。

### 3. 异常死循环检测看门狗 (`AnomalyWatchdog`)
在长循环或大任务执行时，自动检测潜在异常并输出高亮警告（不强行中断，或可配置熔断阈值）：
- **工具死循环探测（Repeated Tool Calls）**：同一工具以完全相同的序列化参数连续调用超过 3 次；
- **连续工具故障探测（Tool Error Cascade）**：连续 5 次工具执行返回 `is_error=True`；
- **上下文激增警报（Context Explosion）**：单轮输入 Token 增幅超过预设阈值（如 >50k tokens）。

---

## 四、使用与调试指南

### 1. 交互模式下使用日志实时调试
开启两扇终端窗口：
- **窗口 1（启动 Agent）**：
  ```bash
  npm start -- --debug
  # 或
  $env:MY_AGENT_DEBUG="1"; npm start
  ```
- **窗口 2（实时监控事件日志）**：
  ```powershell
  Get-Content "$HOME\.my-pi-agent\logs\debug.log" -Wait -Tail 30
  ```

### 2. 纯 Python 脚本/单测中实时打印
```python
import asyncio
from pathlib import Path
from my_coding_agent.agent import CodingAgent
from my_coding_agent.tracer import DebugEventTracer
from my_agent_llm import LLM, Config

async def main():
    llm = LLM(Config(provider="deepseek", model="deepseek-flash"))
    agent = CodingAgent(workspace=Path("."), llm=llm, session="test.jsonl")
    
    # 挂载控制台彩色时序追踪器
    agent.subscribe(DebugEventTracer(console_output=True))
    
    await agent.run("读取 package.json")

asyncio.run(main())
```

---

## 五、不变式与安全边界

1. **Stdout 洁净不变式（Clean Stdout Invariant）**：
   在任何情况下，`tracer.py` 绝不允许向 `sys.stdout` 输出任何非 JSON-RPC 文本。
2. **Log File Rotation（日志防爆机制）**：
   `debug.log` 超过 10MB 时自动回滚重命名为 `debug.log.1`，仅保留最近 3 个备份文件。
3. **脱敏保护（Sanitization）**：
   在序列化工具参数或环境数据时，凡包含 `API_KEY`、`token`、`secret`、`password` 等关键词的敏感字段值，自动替换为 `***REDACTED***`。
