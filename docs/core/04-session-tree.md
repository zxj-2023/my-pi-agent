# 树状会话与原子持久化设计规范 (`my_agent_core.session`)

- **定位**：崩溃安全的树状对话历史与分支存储引擎 (`packages/my-agent-core/src/my_agent_core/session.py`, `session_store.py`)
- **核心类**：`SessionEntry`, `SessionTree`, `Session`, `SessionStore`
- **主要实现**：`session.py`, `session_store.py`

---

## 一、架构设计与定位

会话管理负责持久化 Agent 发生的所有对话、工具调用与系统状态。`my-agent-core` 的会话系统设计强调三大特性：

1. **树状分支结构（Tree-structured History）**：每条消息带 `id` 与 `parent_id`，天然支持指针回溯与分支衍生；
2. **崩溃安全原子落盘（Crash-Safe Atomic Write）**：逐条原子刷盘，断电或进程被杀绝不损坏文件；
3. **Workspace 天然物理隔离**：会话文件统一持久化在工作区私有目录下，跨项目天然不可见。

```text
                           SessionStore (会话仓库)
                     管理 <workspace>/.my_agent_core/sessions/
                                     │
                                     ▼
                                  Session
               (持有会话文件路径、元数据与当前指针 current_id)
                                     │
                                     ▼
                                SessionTree
               (持有内存 Entry 树字典: dict[str, SessionEntry])
                                     │
                 ┌───────────────────┼───────────────────┐
                 ▼                   ▼                   ▼
            SessionEntry        SessionEntry        SessionEntry
            id: "msg_1"         id: "msg_2"         id: "msg_3"
            parent_id: None     parent_id: "msg_1"  parent_id: "msg_2"
            role: "user"        role: "assistant"   role: "tool"
```

---

## 二、核心类与机制

### 1. `SessionEntry`（原子会话节点）

```python
@dataclass
class SessionEntry:
    id: str                 # 唯一消息 ID (如 uuid/时间戳哈希)
    parent_id: str | None   # 父节点 ID (树状拓扑关系)
    role: str               # "user" | "assistant" | "tool" | "compaction"
    content: str            # 纯文本正文
    tool_call_id: str | None = None
    tool_calls: list[dict] | None = None
    created_at: float = field(default_factory=time.time)
```

### 2. `SessionTree`（内存树拓扑）

- **`get_current_path_entries()`**：从 `current_id` 开始沿着 `parent_id` 链条向上回溯，返回当前主线路径上的所有有序条目；
- **`rewind(target_id)`**：将 `current_id` 指针回退到历史某一节点。历史旧分支完整保留在树中，绝不物理删除；
- **`fork(target_id)`**：从指定节点截取历史路径，克隆生成全新的独立 `SessionTree`。

### 3. `Session`（会话门面与持久化）

- **`add_message(role, content, ...)`**：创建新节点挂在 `current_id` 之后，将 `current_id` 推进到新节点，并**立即触发原子写盘**；
- **`save()`**：将整个树的所有 Entry 逐行序列化为标准 JSONL 格式；
- **崩溃安全原子落盘**：

  ```python
  tmp_fd, tmp_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
  with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
      for entry in self.tree.entries.values():
          f.write(json.dumps(entry.to_dict()) + "\n")
      f.flush()
      os.fsync(f.fileno())  # 强制刷入物理扇区
  os.replace(tmp_path, str(path))  # 操作系统级原子替换
  ```

---

## 三、`SessionStore` 与 Workspace 目录隔离

`SessionStore` 负责在 `<workspace>/.my_agent_core/sessions/` 目录下创建、检索、枚举与管理所有 `.jsonl` 文件：

- **`create_session(metadata)`**：生成以时间戳和 UUID 命名的持久化会话；
- **`open_session(session_id)`**：加载已有会话；
- **子代理独立目录**：子代理的会话统一存放在 `<session_dir>/subagents/`，与主会话天然隔离。
