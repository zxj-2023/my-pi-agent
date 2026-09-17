# 工作区编码工具集与并发控制规范 (`my_coding_agent.tools`)

- **定位**：产品层编码专属工具体系与工作区防护 (`src/my_coding_agent/tools/`, `mutation_queue.py`, `file_reference.py`)
- **设计标杆**：`@earendil-works/pi-coding-agent`、`tau_coding`
- **核心能力**：7 大核心工作区工具、Pi 宽松 CWD 路径解析、细粒度单文件并发锁、提示词 `@` 文件快照直通注入

---

## 一、架构全景与分层定位

在 `my-pi-agent` 中，遵循 **“框架通用微内核，业务专属工程化”** 的分层原则：

1. 通用框架层 `my-agent-core` 保持纯粹，不绑定任何特定业务的文件工具；
2. 产品层 `my_coding_agent` 为软件工程专属打造了 7 大工作区工具，并通过单文件并发锁与提示词扩展提供安全高效的代码修改能力。

```text
                               CodingAgent
                                    │
       ┌────────────────────────────┼────────────────────────────┐
       ▼                            ▼                            ▼
【7 大核心工作区工具】       【细粒度单文件并发锁】        【提示词 @ 文件解析】
- read (分页切片/截断保护)    - FileMutationQueue          - FileReferenceParser
- write (原子覆写/创建父目录) - 基于物理规范化路径         - 2000行/50KB 双重截断
- edit (精确匹配/多块替换)    - 跨文件完全并发             - 经 UserInputHook 直通
- bash (异步/树终止/增量流)   - 同文件排队隔离             - <referenced_file> 注入
- grep (原生跨平台正则检索)
- find (智能 Glob 匹配)
- ls (目录列举/大小写不敏感)
       │                            │                            │
       └────────────────────────────┼────────────────────────────┘
                                    ▼
                     resolve_path(workspace, target)
                 (100% 对齐 Pi 原厂宽松 CWD 路径解析规范)
```

---

## 二、七大核心工具设计与行为规范

所有工具均通过 `build_coding_tools(workspace, mutation_queue, background_runner)` 工厂函数批量装配，统一使用 Pydantic Schema 定义入参与类型校验，严格遵守 **Never-Throw** 契约（任何异常均拦截转换为 `ToolResult(ok=False, error=...)`，避免 LLM 崩溃）。

### 1. `resolve_path`：工作区路径宽松解析哲学

```python
def resolve_path(workspace: Path | str, target: str | Path) -> Path:
    """遵循 Pi 原厂设计哲学的工作区路径解析器。"""
    p = Path(target)
    if p.is_absolute():
        return p.resolve()
    return (Path(workspace) / p).resolve()
```

- **工作区（CWD）是基准点，而非人工虚拟沙箱**：
  在真实工程研发中，开发者需要跨模块引用同级目录、读取环境配置（如 `~/.gitconfig`）或查看存放在临时目录的编译日志。严格的人工沙箱（如拦截 `../`）会打断正常重构与 Monorepo 开发。
- **透明度与版本控制防线**：
  安全防线建立在透明的 Tool Call 参数审计与 Git 变更审查之上，而非应用层字符串拦截。

### 2. `read(path, offset, limit)`

- **行级切片与大文件防护**：支持 `offset`（1-based 起始行）与 `limit`（读取行数），默认最大 2000 行 / 50KB 截断保护，直接输出纯文本代码行；
- **自愈提示**：当行偏移超出文件末尾时，返回 `Offset X is beyond end of file (file has only Y lines)`，精准引导 LLM 自我纠错；
- **二进制检测**：自动探测并拒绝读取非文本二进制文件。

### 3. `write(path, content)`

- **原子全量覆写**：支持创建新文件或覆写已有文件，自动递归创建缺失的多级父目录；
- **并发锁保护**：通过 `FileMutationQueue` 获取文件物理路径锁，保证多工具并发调用时的读写安全；
- **回显统计**：返回成功写入的字符数与行数统计。

### 4. `edit(path, edits, old_text, new_text)`

- **多模型入参容错与单/多块兼容（对标 Pi 原厂 `prepareEditArguments`）**：
  - **单块便捷传参**：支持直接通过 `old_text` 与 `new_text`（同时兼容驼峰 `oldText` / `newText`）实施单块替换；
  - **多块与非结构化容错**：自动兼容反序列化 JSON 字符串、单个字典包裹或字典列表，彻底消除各类大模型由于 Schema 偏差导致的参数报错；
- **逆序精准替换与非重叠校验**：
  - 针对多段编辑，自动校验区间是否重叠；
  - 严格校验唯一匹配：若 `old_text` 未命中，返回目标文件总行数并建议先使用 `read`；若命中多处（`count > 1`），返回具体重复次数并提示提供更多上下文；
  - 按文件中出现的逆向偏移量顺序实施替换，避免前序替换改变后续代码偏移；
- **Unified Diff 回显**：替换成功后自动生成 Unified Diff 变更差异，供前端终端高亮与上下文记录。

### 5. `bash(command, timeout, run_in_background)`

- **增量流式回传（100ms `on_update`）**：
  底层采用 `asyncio.create_subprocess_shell`，通过异步行流读取 stdout/stderr，每 100ms 向前端事件流推送 partialResult，避免长耗时命令出现黑盒卡顿；
- **后台作业与任务系统集成**：
  支持 `run_in_background=True`，联动内核 `background_runner` 异步拉起长耗时服务进程（如编译构建、开发服务器），并返回任务 ID 供后续查询或终止；
- **高危命令硬拦截**：
  静态拦截破坏性高危指令（包含 `rm -rf /`, `rm -rf /*`, `mkfs`, `dd if=/dev/zero`, `:(){ :|:& };:`, `shutdown`, `reboot`, `init 0` 等）；
- **完整进程树终止**：
  当超时（默认 120 秒）或用户按 `Esc` 中断时，Windows 下调用 `taskkill /F /T /PID`，POSIX 下调用 `os.killpg`，彻底铲除孙子进程孤儿残留；
- **大日志外溢保护**：
  输出超过 2000 行或 50KB 时自动截断，并将全量原始日志外溢持久化至系统临时文件（`%TEMP%/bash_output_*.log`）。

### 6. `grep(pattern, path, glob, context, ignore_case, literal, limit)`

- **原生跨平台搜索**：纯 Python 实现，全面对齐 Pi 原厂参数；
- **上下文行支持**：通过 `context` 参数输出匹配行前后的上下文（匹配行标记 `:`，上下文行标记 `-`）；
- **高级过滤**：支持通配符过滤（`glob`）、忽略大小写（`ignore_case`）、纯文本字面量（`literal`），默认 50KB 截断保护。

### 7. `find(path, pattern, limit)`

- **极速通配符查找**：基于 `Path.rglob`，自动忽略 `.git`、`.venv`、`node_modules` 等无关构建产物；
- **截断与排版**：默认 1000 项结果上限与 50KB 字节截断。

### 8. `ls(path, limit)`

- **目录与结构浏览**：对标 Pi 原厂第 7 个内置工具，列出目标目录下的文件与子目录；
- **排版规范**：目录名自动追加 `/` 后缀，字母大小写不敏感排序，包含隐藏文件（dotfiles），上限 500 项 / 50KB。

---

## 三、`FileMutationQueue` 细粒度单文件并发锁

为了在大模型单轮输出多个并发工具调用（Tool Batch Execution）时，兼顾**执行效率**与**并发安全**，产品层实现了 `FileMutationQueue`：

```python
class FileMutationQueue:
    """细粒度单文件并发锁管理器。"""
    def __init__(self) -> None:
        self._locks: dict[Path, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()

    @asynccontextmanager
    async def acquire(self, file_path: Path | str) -> AsyncIterator[None]:
        norm_path = Path(file_path).resolve()
        async with self._global_lock:
            if norm_path not in self._locks:
                self._locks[norm_path] = asyncio.Lock()
            lock = self._locks[norm_path]
        async with lock:
            yield
```

- **锁粒度**：以物理规范化绝对路径（`resolve()`）为锁键；
- **并发表现**：修改不同文件完全并行（$O(1)$ 无阻塞）；并发修改同一文件时自动排队等待，保证原子性。

---

## 四、`FileReferenceParser` 提示词 `@` 文件快照直通注入

对标 Pi / Pig-Mono 的 `@path/to/file` 交互规范，产品层提供在用户输入时直接附加源码快照的能力：

```text
用户输入: "请重构 @src/app.ts 并修复拼写错误"
                   │
                   ▼
       UserInputHook 拦截处理 (FileReferenceParser)
                   │
                   ▼
实际传给模型的 Prompt:
"请重构 @src/app.ts 并修复拼写错误

<referenced_file path="src/app.ts">
export class App { ... }
</referenced_file>"
```

1. **正则提取**：使用 `r"@([\w\-./]+\.\w+)"` 提取工作区文件路径，去重并保持出现顺序；
2. **安全边界与双重截断**：
   - 校验文件存在性与文本类型（二进制文件自动忽略）；
   - 严格执行 2000 行 / 50KB 双重截断保护，超出时追加 `[File truncated at 2000 lines]` 警告；
3. **架构接入点**：在 `CodingAgent.__init__` 中注册至框架的 `UserInputHook`，在消息写入 Session 和发起模型请求前完成无缝扩展。
