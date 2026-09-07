# 核心框架清理与关键缺陷修复设计文档

(Core Framework Cleanup and Defect Repair Specification)

- **日期**：2026-08-30
- **目标代码库**：`packages/my-agent-core`
- **来源**：两路并行 Subagent 对抗式审查（Deslop Pass 与 Verbosity Pass）审查结论
- **核心原则**：安全性优先、消灭写放大与死代码、保持全量 304 项离线测试 100% 绿灯。

---

## 一、审查背景与总览 (Background & Overview)

在完成统一 Task 系统与后台异步执行引擎后，我们组织了两个独立的专业审查子 Agent，对 `packages/my-agent-core/src/my_agent_core/` 进行了深度的静态分析与对抗性审查。

审查确认了现有架构中优秀的四层上下文纯视图变换、Crash-safe 原子刷盘、因果并发调度等核心长板，但同时也精准揪出了 **3 个 P0 阻断级致命缺陷** 以及 **4 个 P1 级性能写放大与假特性缺陷**。

本规范旨在将这些问题的成因、风险、修复代码与验证标准全面形式化，作为后续精确修复的技术依据。

---

## 二、P0 阻断级缺陷与修复规格 (P0 Blocker Defects)

### 2.1 P0-1: `background.py` 在 Unix/macOS 下的自杀式进程组强杀缺陷

#### 1. 缺陷成因与代码证据

在 `packages/my-agent-core/src/my_agent_core/background.py:68-76` 中：

```python
proc = await asyncio.create_subprocess_shell(
    command,
    cwd=str(cwd),
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
)
```

未传入 `start_new_session=True`（或 `process_group=0`）。在 POSIX 系统（Linux, macOS）中，由 shell 派生的子进程默认继承父进程的进程组，即：
$$\text{os.getpgid(proc.pid)} == \text{os.getpgrp()}$$
而在清理逻辑 `_kill_process_tree`（第 45 行）中：

```python
if os.name == "nt":
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], ...)
else:
    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
```

一旦触发 `cancel_all()`、`agent.abort()` 或 `atexit` 退出清理，`os.killpg` 会直接向**当前 Python 宿主/测试主进程所在的一整个进程组**广播发送 `SIGKILL`，导致宿主被当场自杀秒杀，无法进行任何异常捕获与清理。

#### 2. 修复规格与代码方案

1. **子进程独立会话隔离**：在 POSIX 系统下，启动子进程时显式开启独立会话（`start_new_session=True`），使其成为独立进程组组长；
2. **防自杀防御护盾**：在调用 `os.killpg` 前，增加绝对防御断言，严禁向自身所在进程组发信号。

```python
# background.py 修复方案：
async def run_process(self, command: str, cwd: Path | str, description: str = "") -> str:
    ...
    async def _worker() -> None:
        kwargs = {}
        if os.name != "nt":
            kwargs["start_new_session"] = True
            
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **kwargs,
        )
        ...

def _kill_process_tree(proc: asyncio.subprocess.Process | None) -> None:
    if proc is None or proc.returncode is not None or not proc.pid:
        return
    with contextlib.suppress(Exception):
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            pgid = os.getpgid(proc.pid)
            # 防御断言：绝对不允许向自身当前进程组发送 SIGKILL
            if pgid != os.getpgrp():
                os.killpg(pgid, signal.SIGKILL)
```

---

### 2.2 P0-2: `ExtensionAPI.on` 将异步 Hook 封装为普通同步函数导致协程悬挂与拦截失效

#### 1. 缺陷成因与代码证据

在 `packages/my-agent-core/src/my_agent_core/extensions/core.py:47-52` 中：

```python
def _register(h: Callable[..., Any]) -> Callable[..., Any]:
    def wrapped(event: Event): # <--- 普通同步 def 函数
        return h(event, self)

    self.agent.hooks.register(event_cls, wrapped)
    return h
```

若用户写了一个异步扩展钩子 `@api.on(TurnEnd) async def my_hook(event, api): ...`：
由于 `wrapped` 是普通同步函数，`asyncio.iscoroutinefunction(wrapped)` 恒为 `False`。
当 `HookRegistry.emit()` 触发事件时（`events.py:196-200`）：

```python
if asyncio.iscoroutinefunction(cb):
    result = await cb(event)
else:
    result = cb(event) # 走同步分支！
if result is not None:
    return result
```

它直接同步调用 `wrapped(event)`，返回值是一个未被 await 的协程对象 `coroutine`。

- **后果 1**：控制台疯狂抛出 `RuntimeWarning: coroutine '...' was never awaited`，扩展的异步逻辑实际上**从未被执行**；
- **后果 2**：协程对象在布尔判定下 `result is not None` 为真，但 `isinstance(result, HookResult)` 为假，导致任何拦截指令（如改写参数、阻止工具调用）全部失灵。

#### 2. 修复规格与代码方案

在 `_register` 内动态检测 `inspect.iscoroutinefunction(h)`，若为异步函数，则注册一个真正的 `async def wrapped` 协程函数。

```python
# extensions/core.py 修复方案：
def _register(h: Callable[..., Any]) -> Callable[..., Any]:
    if inspect.iscoroutinefunction(h):
        async def wrapped(event: Event):
            return await h(event, self)
    else:
        def wrapped(event: Event):
            return h(event, self)

    self.agent.hooks.register(event_cls, wrapped)
    return h
```

---

### 2.3 P0-3: `TaskStore` 与 `MemoryStore` 读异常时静默重置导致数据覆写丢失

#### 1. 缺陷成因与代码证据

在 `task_store.py:53-56` 中：

```python
try:
    data = json.loads(self.file_path.read_text(encoding="utf-8"))
    ...
except (json.JSONDecodeError, OSError, TypeError, ValueError):
    pass # 损坏文件或空文件容错，保留初始空状态
```

在 `memory.py:63-65` 中：

```python
except Exception:
    entries = []
```

若目标文件存在但由于短暂的权限问题（如被编辑器短暂独占锁定导致 `PermissionError`）或并发读取冲突，内存状态会被**静默重置为空**。
随后一旦触发任何 `create()`、`add()` 或 `save()`，系统将把这个空状态全量原子写入磁盘，**彻底冲掉用户历史积累的任务工单或记忆数据**！

#### 2. 修复规格与代码方案

1. 区分“文件不存在/空白文件”与“文件非空读取损坏”；
2. 若文件非空且读取解析失败，绝不静默吞掉，而是安全地将损坏文件重命名备份为 `tasks.json.corrupted.bak`，并在日志中输出清晰警告后再初始化。

---

## 三、P1 级性能瓶颈与架构缺陷修复规格 (P1 Defects)

### 3.1 P1-1: `context.py` 的 L3 大工具结果落盘在每次迭代中无条件全量重写（严重写放大）

#### 1. 缺陷成因与代码证据

在 `context.py:114-118` 中：

```python
try:
    results_dir.mkdir(parents=True, exist_ok=True)
    tid = str(m.metadata.get("tool_call_id", i)) if m.metadata else str(i)
    path = results_dir / f"{tid}.txt"
    path.write_text(m.content, encoding="utf-8") # 每次迭代无条件重写！
except OSError:
    continue
```

`Agent.run()` 在每一次 ReAct 迭代调用大模型前，都会调用 `view = await self._ctx.prepare(self.messages)`。
由于 `prepare()` 是非破坏性的纯视图转换，大于 20KB 的大工具结果依然完整保存在 `self.messages` 中。在一次包含 20 轮交互的任务中，该大文件会被重复全量写入磁盘 20 次！

#### 2. 修复规格与代码方案

在写入前增加存在性判定：

```python
if not path.exists():
    path.write_text(m.content, encoding="utf-8")
```

一行代码即可消除 95% 以上的无谓磁盘 I/O。

---

### 3.2 P1-2: `Tool.timeout` 属于未生效的假参数

#### 1. 缺陷成因与代码证据

在 `tools/core.py:41` 和 `@tool` 装饰器中，接受了 `timeout: float | None = None`，并赋值给 `self.timeout`。
但深入查看执行体 `Tool.execute()`（第 115~140 行），无论在异步分支还是同步分支，**没有任何代码引用 `self.timeout`**！这属于典型的 AI-Slop 假特性。当工具出现死锁或网络卡死时，整个 Agent 循环将无限挂起。

#### 2. 修复规格与代码方案

在 `Tool.execute()` 中正式接入 `asyncio.wait_for`，并在超时时优雅包装为 `ToolResult(ok=False, error=...)`：

```python
# tools/core.py 修复方案：
async def _execute_with_timeout(coro):
    if self.timeout is not None and self.timeout > 0:
        return await asyncio.wait_for(coro, timeout=self.timeout)
    return await coro

try:
    if self.is_async:
        result = await _execute_with_timeout(self.func(**bound_args))
    else:
        result = await _execute_with_timeout(asyncio.to_thread(self.func, **bound_args))
except asyncio.TimeoutError:
    return ToolResult(ok=False, error=f"Tool '{self.name}' timed out after {self.timeout}s")
```

---

### 3.3 P1-3: `Session.get_current_path_messages()` 丢失类型过滤导致数据泄漏

#### 1. 缺陷成因与代码证据

对比 `session.py` 中的两个查询方法：

- `get_full_history_messages()`（第 218 行）：严格检查了 `if e.type == "message":`；
- `get_current_path_messages()`（第 185 行）：**没有任何过滤**，直接将树路径上的所有条目当成消息返回！
如果树上挂载了 `compaction` 类型的条目，`get_current_path_messages()` 会将其误认为普通文本消息塞入上下文，引发格式错乱。

#### 2. 修复规格与代码方案

在 `get_current_path_messages()` 中补齐类型检查：

```python
return [
    Message(role=e.role, content=e.content, metadata=e.metadata)
    for e in path_entries
    if e.type == "message" # 关键类型约束
]
```

---

### 3.4 P1-4: 工具参数在 Agent 与 Registry 之间的重复 JSON 编解码优化

#### 1. 缺陷成因与代码证据

在 `agent.py` 的工具派发循环中：

1. `_prepare_tool` 先做 `args = json.loads(...)`（第 616 行）；
2. 传给 `registry.execute_batch` 时，又拼成 `"arguments": json.dumps(args)`（第 486 行）；
3. `registry.py` 收到后，在 `execute_tool_call` 又做了一次 `args = json.loads(...)`（第 34 行）。
单次工具调用经历 3 次重复 JSON 编解码。

#### 2. 修复规格与代码方案

让 `registry.execute_tool_call` 和 `Tool.execute` 直接支持接收已解析的 `dict` 参数，去除中间无效的 `json.dumps`。

---

## 四、P2 级代码冗余与过度设计清理规格 (P2 Cleanup)

1. **P2-1: 修复 `skills.py` 文档与代码优先级矛盾**：
   - 修正注释，明确 frontmatter `name` 的优先级高于父目录名；
2. **P2-2: `ContextManager.prepare()` 重复计算字符长度优化**：
   - 将 `_chars_of(view)` 与 `estimate_tokens(view)` 的连续两次全量序列化合并为一次；
3. **P2-3: `ExtensionManager.load()` 规范化日志**：
   - 将裸 `print(f"Failed to load...")` 替换为标椎的 `logger.warning(...)`。

---

## 五、实施顺序与验证契约 (Execution Plan)

修复工作按照“先修 P0 致命隐患，再除 P1 性能与假参数，最后清理 P2 冗余”的顺序推进：

1. **Step 1（P0 修复）**：
   - 修复 `background.py` 中的独立进程组会话隔离；
   - 修复 `extensions/core.py` 中的异步 Hook 协程包装；
   - 增强 `task_store.py` 磁盘异常防护。
2. **Step 2（P1 修复）**：
   - 给 `context.py` 的 L3 写入增加 `if not path.exists()`；
   - 给 `tools/core.py` 补齐 `asyncio.wait_for` 超时驱动；
   - 给 `session.py` 的 `get_current_path_messages` 增加 `e.type == "message"` 过滤。
3. **Step 3（全量回归验证）**：
   - 运行全量 `uv run python -m pytest -q`，必须确保已有 **304 个离线测试全部绿灯**；
   - 为 `Tool.timeout` 真实生效与异步 Hook 执行补齐针对性单元测试。
