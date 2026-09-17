# 编码文件工具与工作区路径解析规范 (`my_coding_agent.tools`)

- **定位**：产品层专属编码文件工具集 (`src/my_coding_agent/tools/`)
- **核心函数**：`build_coding_tools(workspace)`, `resolve_path`
- **七大核心工具**：`read`, `write`, `edit`, `bash`, `grep`, `find`, `ls`

---

## 一、架构设计与定位

编码文件工具是软件开发 Agent（Coding Agent）专属的业务工具。
我们严格坚守 **“业务与框架彻底分层”** 的原则：

- 框架层 `my-agent-core` 保持纯净通用（不内置任何具体文件工具）；
- 产品层 `my-coding-agent` 提供经过严格安全沙箱校验的文件读写与执行工具。

```text
                  CodingAgent 实例化
                         │
                         ▼
        build_coding_tools(workspace_dir)
                         │
         ┌───────────────┼───────────────┬───────────────┬───────────┐
         ▼               ▼               ▼               ▼           ▼
       read            write           edit            bash     grep/find/ls
   (安全读取文件)  (原子写入文件)  (局部精确替换)  (安全流式执行) (搜索与列举)
         │               │               │               │           │
         └───────────────┴───────┬───────┴───────────────┴───────────┘
                                 │
                                 ▼
                   resolve_path(workspace, target)
                 (Pi 规范宽松 CWD 相对路径解析)
```

---

## 二、七大核心工具与路径规范

### 1. `resolve_path`：工作区路径宽松解析（100% 对齐 Pi 原厂规范）

所有文件工具统一通过 `resolve_path(workspace, target)` 展开：

- 遵循 Pi 原厂设计哲学：Coding Agent 运行于用户工作区，默认基于当前工作目录（CWD）宽松相对解析，不预设阻碍开发的人工虚拟沙箱牢笼；
- 支持相对路径与绝对路径无缝自愈映射，确保跨项目和单体多目录重构时平滑稳定。

### 2. `read(path, offset, limit)`

- 安全读取文本内容，带行号前缀（如 `123 | const a = 1;`）；
- 支持大文件分页（`offset` / `limit` 行级切片，默认 2000 行 / 50KB 双重截断保护），防止单次读取巨量文件冲垮 LLM 上下文；
- **精细化报错**：越界时返回明确提示（如 `Offset 200 is beyond end of file ('app.py' has only 80 lines total)`），引导模型自我纠错。

### 3. `write(path, content)`

- 创建或覆盖写入文件，自动递归创建缺失的父目录；
- **`FileMutationQueue` 单文件锁保护**：标记为 `is_parallel_safe=True`，由内部路径锁自动排队，不同文件完全并发；
- 写入后回显写入字节数或行数。

### 4. `edit(path, edits)`

- 外科手术式精确修改，支持单个或批次多块替换；
- **多模型入参容错（对标 Pi 原厂 prepareEditArguments）**：
  - 自动探测并反序列化 JSON 字符串或包装单个 dict，杜绝 Opus/GLM 等模型因格式偏差触发的 Schema 报错；
- **逆序精准替换与 Unified Diff 回显**：
  - 若 `old_text` 未找到：返回目标文件总行数并提示模型核对空白字符或先 `read`；
  - 若命中多处（`count > 1`）：明确提示命中次数，要求模型提供更多上下文以确保唯一匹配；
  - 修改完成后自动生成彩色 Unified Diff 供终端审查或上下文记录。

### 5. `bash(command, timeout)`

- 在当前工作区执行 Shell 命令并捕获 stdout/stderr；
- 内置高危命令黑名单与执行超时保护（默认 120 秒）；
- **100ms 增量流式回传（`on_update`）**：采用异步行流读取，每 100ms 向前端广播最新输出片段，彻底告别长任务黑盒；
- **超时自动捕获 Partial Output**：命令超时时保留子进程已输出的最后 2000 字符日志。

### 6. `grep(pattern, path, glob, context, ignore_case, literal, limit)`

- 原生跨平台正则与文本搜索，全面对齐 Pi 原厂参数命名与行为；
- 支持前后上下文行（`context` 参数，匹配行以 `:` 标记，上下文行以 `-` 标记）；
- 支持大小写忽略（`ignore_case`）、纯文本字面量（`literal`）以及路径通配符过滤（`glob`）；
- 内置 50KB 字节截断保护。

### 7. `find(path, pattern, limit)`

- 极速文件通配符搜索，自动过滤 `.git`、`node_modules` 等无关构建产物目录；
- 默认 1000 项结果上限与 50KB 截断保护。

### 8. `ls(path, limit)`

- 对标 Pi 原厂第 7 个内置工具，列出目标目录下的文件与子文件夹；
- 默认 500 条目上限与 50KB 字节截断；
- 目录条目自动添加 `/` 后缀，字母大小写不敏感排序，支持显示隐藏文件（dotfiles）。

---

## 三、`FileMutationQueue` 细粒度单文件并发锁

为了在大模型批量重构多个文件时实现**极致性能与并发安全**，我们引入了 `FileMutationQueue`：

```text
                  大模型单轮发起多文件并发操作
                             │
     ┌───────────────────────┼───────────────────────┐
     ▼                       ▼                       ▼
edit("src/a.py")        edit("src/b.py")        edit("src/a.py")
     │                       │                       │
     ▼ 申请 a.py 锁          ▼ 申请 b.py 锁          ▼ 申请 a.py 锁 (被占用)
 [ 抢到 a.py 锁 ]        [ 抢到 b.py 锁 ]        [ 排队等待 a.py 锁释放 ]
     │                       │                       │
   ⚡ 执行编辑 a.py          ⚡ 执行编辑 b.py          │ (等待中...)
     │ (并发进行!)           │ (并发进行!)           │
     ▼                       ▼                       ▼
 [ 释放 a.py 锁 ]        [ 释放 b.py 锁 ] ──────► [ 唤醒: 执行第二个 a.py 编辑 ]
```

- **实现机制**：按规范化绝对路径动态分配 `asyncio.Lock`；
- **收益**：修改不同文件全员并发（$O(1)$ 极速），修改同一文件安全排队（零数据覆盖）。
