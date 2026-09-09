# 树状会话与原子持久化设计规范 (`my_agent_core.session`)

- **定位**：崩溃安全的树状对话历史与分支存储引擎 (`packages/my-agent-core/src/my_agent_core/session/`)
- **核心类**：`SessionEntry`（9 种多态实体）, `SessionTree`, `SessionState`, `SessionStorage`, `JsonlSessionStorage`, `Session`, `SessionStore`, `SessionMeta`
- **主要实现**：`session/` 子包 (`entries.py`, `tree.py`, `memory.py`, `storage.py`, `jsonl.py`, `session.py`, `store.py`)

> 💡 **模块化与只追加演进注记 (Phase 18)**：
> 在阶段 18 的架构演进中，原单文件 `session.py` 与 `session_store.py` 已彻底拆解下沉为领域高内聚的 `session/` 统一子包：
>
> 1. `entries.py`：9 种强类型判别多态实体（Message / Thinking / ToolCall / ToolResult 等）；
> 2. `tree.py`：纯内存 DAG 算法（支持 `seen` 集合死锁环路检测与最近公共祖先 LCA 计算，零 I/O）；
> 3. `memory.py`：`SessionState` 不可变事件溯源折叠投影（`from_entries` 纯函数）；
> 4. `storage.py`：纯异步只追加 `SessionStorage` 抽象协议与 `InMemorySessionStorage` 驱动；
> 5. `jsonl.py`：`JsonlSessionStorage` 追加驱动、跨进程文件锁与未完成 `.tmp` 碎片自愈；
> 6. `session.py`：高级 `Session` 与 `SessionTree` 树状分支会话门面；
> 7. `store.py`：工作区天然物理隔离的会话仓库管理器 `SessionStore`（支持短前缀模糊寻址）。
> 同时，存储机制由旧版“全量覆写整个 JSONL”升级为业界标准的**只追加（Append-only）纯异步协议**，外层冗余单体文件已全部物理清除。
> 详细设计规格参见：[13. Tau 对齐与核心框架深度重构设计文档](13-tau-alignment-architecture-redesign.md)。

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

## 三、`SessionStore` 与 Workspace 目录隔离 (`session/store.py`)

`SessionStore` 负责在 `<workspace>/.my_agent_core/sessions/` 目录下创建、检索、枚举与管理所有 `.jsonl` 文件：

- **`create() / create_session()`**：生成以时间戳和 UUID 命名的持久化会话；
- **`open(id_or_prefix) / open_session(id_or_prefix)`**：根据全 ID 或短前缀模糊匹配加载已有会话；
- **`list() -> list[SessionMeta]`**：扫描目录并按 `created_at` 倒序返回会话元信息列表；
- **`delete(id_or_prefix)`**：安全物理删除会话文件；
- **`fork(id_or_prefix, entry_id)`**：从某会话的指定节点分叉出独立演化的新会话；
- **子代理独立目录**：子代理的会话统一存放在 `<session_dir>/subagents/`，与主会话天然隔离。
