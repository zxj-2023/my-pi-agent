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
- 支持大文件分页（`offset` / `limit` 行级切片），防止单次读取几万行文件冲垮 LLM 上下文。

### 3. `write(path, content)`

- 创建或覆盖写入文件；
- 自动递归创建缺失的父目录。

### 4. `edit(path, old_text, new_text)`

- 外科手术式精确修改；
- 校验 `old_text` 在目标文件中必须**全局唯一存在**（若出现多次或未出现均拒绝并报错），彻底防止错位误替换。

### 5. `bash(command, timeout)`

- 在当前工作区执行 Shell 命令并捕获 stdout/stderr；
- 内置高危命令黑名单与执行超时保护（默认 120 秒）。
