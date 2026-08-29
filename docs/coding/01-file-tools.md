# 编码文件工具与工作区安全沙箱设计规范 (`my_coding_agent.tools`)

- **定位**：产品层专属编码文件工具集 (`packages/my-coding-agent/src/my_coding_agent/tools.py`)
- **核心函数**：`build_coding_tools(workspace)`, `_safe_path`
- **四大工具**：`read`, `write`, `edit`, `bash`

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
         ┌───────────────┼───────────────┬───────────────┐
         ▼               ▼               ▼               ▼
       read            write           edit            bash
   (安全读取文件)  (原子写入文件)  (局部精确替换)  (安全子进程执行)
         │               │               │               │
         └───────────────┴───────┬───────┴───────────────┘
                                 │
                                 ▼
                   _safe_path(workspace, target)
                 (严格拦截 ../ 路径穿越攻击)
```

---

## 二、四大核心工具与安全防线

### 1. `_safe_path`：路径逃逸防御

所有文件工具必须强制通过 `_safe_path` 校验：

- 将目标路径解析为绝对物理路径；
- 检查目标路径是否严格位于 `workspace` 根目录之内；
- 拦截 `../../etc/passwd` 等任何形式的路径穿越攻击，越界直接返回安全错误。

### 2. `read(path, offset, limit)`

- 安全读取文本内容；
- 支持大文件分页（`offset` / `limit` 行级切片），防止单次读取几万行文件冲垮 LLM 上下文；
- **精细化报错**：越界时返回明确提示（如 `Offset 200 is beyond end of file ('app.py' has only 80 lines total)`），引导模型自我纠错。

### 3. `write(path, content)`

- 创建或覆盖写入文件，自动递归创建缺失的父目录；
- **`FileMutationQueue` 单文件锁保护**：标记为 `is_parallel_safe=True`，由内部路径锁自动排队，不同文件完全并发。

### 4. `edit(path, old_text, new_text)`

- 外科手术式精确修改；
- **多重匹配与未找到精准提示**：
  - 若 `old_text` 未找到：返回目标文件总行数并提示模型核对空白字符或先 `read`；
  - 若命中多处（`count > 1`）：明确提示命中次数，要求模型提供更多上下文以确保唯一匹配；
- **`FileMutationQueue` 单文件锁保护**：标记为 `is_parallel_safe=True`，不同文件并发编辑极速完成。

### 5. `bash(command, timeout)`

- 在当前工作区执行 Shell 命令并捕获 stdout/stderr；
- 内置高危命令黑名单与执行超时保护（默认 120 秒）；
- **超时自动捕获 Partial Output**：命令超时时自动保留子进程已输出的最后 2000 字符日志，杜绝信息黑盒。

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
